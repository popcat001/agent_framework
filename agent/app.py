#!/usr/bin/env python3
"""
agent.py - Skill Loading + Context Compaction + TodoWrite

The agent can:
  - Track its own progress via a todo list, with nag reminders
  - Load specialized skills on demand
  - Compress context to run indefinitely

    Before each LLM call:
    [auto_compact if > threshold] -> LLM call

    Skill loading (two layers):
    Layer 1: skill names in system prompt
    Layer 2: full body injected via tool_result when load_skill is called
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agent.compaction import auto_compact, estimate_tokens
from agent.config import MODEL, client
from agent.constants import COMPACT_THRESHOLD, MAX_TOKENS, SKILLS_DIR, TOOLS_DIR
from agent.memory import SystemBuilder
from agent.skills import SkillLoader
from agent.todo import TodoManager
from agent.tool_loader import ToolLoader
from agent.tools import BASE_HANDLERS, PARENT_TOOLS


class AgentCancelled(Exception):
    """Raised inside ``Agent.run`` when its ``cancel_event`` is set — lets a
    caller (e.g. the WebSocket layer on stop/disconnect) abort an in-flight
    run between LLM/tool steps instead of leaving it running unattended."""


class Agent:
    def __init__(
        self,
        extra_tools: list | None = None,
        extra_handlers: dict | None = None,
        memory_tool_available: bool = False,
        skill_dirs: list[Path] | None = None,
        tool_dirs: list[Path] | None = None,
        system_prompt_path: Path | None = None,
    ):
        """Construct the agent.

        ``extra_tools`` / ``extra_handlers`` are the CLI-isolation seam: the
        framework's ``PARENT_TOOLS`` does not include the user-memory tools —
        the web wrapper supplies them at construction time, and CLI never
        does. ``memory_tool_available`` flips the ``{memory_guidance}``
        placeholder in ``prompts/system.md`` on (web) or off (CLI). All three
        kwargs default to the CLI-safe behavior.

        Memory-specific state (the per-turn provider and the prompt
        prefix/suffix assembly) lives on ``self.system`` (a
        :class:`~agent.memory.SystemBuilder`), not directly on ``Agent`` — see
        that class for the prompt-cache split rationale.
        """
        self.client = client
        self.skill_loader = SkillLoader(skill_dirs if skill_dirs is not None else SKILLS_DIR)
        self.todo = TodoManager()
        self.tool_loader = ToolLoader(tool_dirs if tool_dirs is not None else TOOLS_DIR)

        self.parent_tools = (
            PARENT_TOOLS + self.tool_loader.get_schemas() + list(extra_tools or [])
        )

        tool_handlers = {
            **BASE_HANDLERS,
            **self.tool_loader.get_handlers(),
            "load_skill": lambda **kw: self.skill_loader.get_content(kw["name"]),
            "todo":       lambda **kw: self.todo.update(kw["items"]),
            "compact":    lambda **kw: "Manual compression requested.",
        }
        if extra_handlers:
            tool_handlers.update(extra_handlers)
        self.tool_handlers = tool_handlers

        self.system = SystemBuilder(
            skill_descriptions=self.skill_loader.get_descriptions(),
            memory_tool_available=memory_tool_available,
            system_prompt_path=system_prompt_path,
        )

    def run(self, messages: list, on_event=None, cancel_event=None):
        """Agent loop with context compaction.

        Args:
            messages: Conversation history (mutated in place).
            on_event: Optional callback for streaming events. Called with dicts:
                {"type": "text_delta", "text": "..."}
                {"type": "tool_start", "name": "...", "input": {...}}
                {"type": "tool_result", "name": "...", "output": "..."}
                {"type": "llm_response", "response": <Message>}
                If None, falls back to print-based logging (REPL mode).
            cancel_event: Optional ``threading.Event``. When set, the loop
                raises :class:`AgentCancelled` at the next checkpoint (between
                rounds, mid-stream, and before tool execution) so a caller can
                abort a run that the user stopped or disconnected from.
        """
        # No-op callback keeps the hot path branch-free (vs ``if on_event:``).
        emit = on_event if on_event is not None else (lambda _e: None)

        def _check_cancel():
            if cancel_event is not None and cancel_event.is_set():
                raise AgentCancelled()

        rounds_since_todo = 0
        while True:
            _check_cancel()
            if estimate_tokens(messages) > COMPACT_THRESHOLD:
                print("[auto_compact triggered]")
                messages[:] = auto_compact(self.client, messages)

            # LLM call: always stream. messages.create() refuses non-streaming
            # requests whose max_tokens budget could exceed a 10-minute server
            # timeout (Sonnet at 64K trips this), so streaming is the only mode
            # that works at the current MAX_TOKENS. on_event is optional — it's
            # passed through to the streamer when present, ignored otherwise.
            # System prompt uses cache_control so it's cached across turns.
            response = self._call_llm_streaming(messages, on_event, self.system.render(), cancel_event)

            messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason != "tool_use":
                return

            tool_blocks = [b for b in response.content if b.type == "tool_use"]

            # Log all tool starts
            for block in tool_blocks:
                try:
                    params = ", ".join(f"{k}={str(v)[:500]}" for k, v in block.input.items())
                    print(f"> Tool Calling: {block.name}({params})")
                except Exception:
                    print(f"> Tool Calling: {block.name}")
                emit({"type": "tool_start", "tool_use_id": block.id, "name": block.name, "input": block.input})

            # Don't start a (possibly long) tool batch if the run was cancelled
            # while the LLM was still streaming its tool calls.
            _check_cancel()

            # Execute tool calls (parallel if multiple, sequential if single)
            if len(tool_blocks) > 1:
                with ThreadPoolExecutor(max_workers=min(len(tool_blocks), 8)) as pool:
                    outputs = list(pool.map(self._exec_tool, tool_blocks))
            else:
                outputs = [self._exec_tool(b) for b in tool_blocks]

            results = []
            manual_compact = False
            used_todo = False
            for block, output in zip(tool_blocks, outputs):
                output_str = str(output)
                if block.name == "compact":
                    manual_compact = True
                elif block.name == "todo":
                    used_todo = True
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": output_str})
                print(f"  Tool Call Output [{block.name}]: {output_str[:200]}")
                emit({"type": "tool_result", "tool_use_id": block.id, "name": block.name, "output": output_str})

            # Todo-nag: fire on moderately multi-step work (≥4 rounds), and
            # phrase the reminder so the model treats it as a side-note rather
            # than the user's new request. Without the explicit "do not respond
            # to this" guard, the model would stop mid-task and answer the
            # reminder ("I don't have any todos…") instead of finishing the
            # user's original question. 4 rounds keeps the progress panel
            # visible for typical analytical questions without over-nagging
            # truly single-step queries.
            rounds_since_todo = 0 if used_todo else rounds_since_todo + 1
            if rounds_since_todo >= 4:
                results.append({
                    "type": "text",
                    "text": (
                        "<system-reminder>If you are working on a multi-step task, "
                        "consider tracking it with the todo tool. Otherwise ignore "
                        "this notice and continue answering the user's original "
                        "question — do NOT mention todos in your reply.</system-reminder>"
                    ),
                })
                rounds_since_todo = 0  # reset so we don't fire again next turn
            messages.append({"role": "user", "content": results})
            if manual_compact:
                print("[manual compact]")
                messages[:] = auto_compact(self.client, messages)

    def _exec_tool(self, block) -> str:
        """Dispatch a single tool_use block to its handler."""
        if block.name == "compact":
            return "Compressing..."
        handler = self.tool_handlers.get(block.name)
        if handler is None:
            return f"Unknown tool: {block.name}"
        try:
            return handler(**block.input)
        except Exception as e:
            return f"Error: {e}"

    def _call_llm_streaming(self, messages, on_event, system=None, cancel_event=None):
        """Stream LLM response, optionally emitting text_delta events.

        ``on_event`` may be ``None`` for the CLI/REPL path — we still stream
        (the SDK requires it at the current MAX_TOKENS) but skip the per-delta
        callback and return only the assembled final message. When
        ``cancel_event`` is set mid-stream we raise :class:`AgentCancelled`
        so a long generation can be abandoned promptly.
        """
        system = system if system is not None else self.system.render()
        with self.client.messages.stream(
            model=MODEL, system=system, messages=messages,
            tools=self.parent_tools, max_tokens=MAX_TOKENS,
        ) as stream:
            for event in stream:
                if cancel_event is not None and cancel_event.is_set():
                    raise AgentCancelled()
                if on_event is not None and getattr(event, "type", None) == "content_block_delta" and hasattr(event.delta, "text"):
                    on_event({"type": "text_delta", "text": event.delta.text})
            return stream.get_final_message()

    def chat(self):
        """Interactive REPL."""
        history = []
        while True:
            try:
                query = input("\033[36magent >> \033[0m")
            except (EOFError, KeyboardInterrupt):
                break
            if query.strip().lower() in ("/exit", "/quit"):
                break
            if not query.strip():
                continue  # Skip empty input
            history.append({"role": "user", "content": query})
            self.run(history)
            # Find the most-recent assistant message and print its text blocks.
            for msg in reversed(history):
                if msg.get("role") != "assistant" or not isinstance(msg["content"], list):
                    continue
                text_parts = [b.text for b in msg["content"] if hasattr(b, "text") and b.text.strip()]
                if text_parts:
                    for t in text_parts:
                        print(f"\n⏺ {t}")
                    break
            print()


def main():
    Agent().chat()


if __name__ == "__main__":
    main()
