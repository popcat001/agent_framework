"""Async streaming wrapper around Agent.run() for WebSocket delivery.

Bridges the synchronous Agent.run(on_event=...) to async WebSocket streaming.
The agent loop lives in framework/agent/app.py — this file only handles:
  1. Running the blocking agent call in a thread executor
  2. Collecting events and replaying them as async WebSocket sends
  3. Extracting chart URLs from tool results
  4. Wiring user-memory tools into the agent (kept out of the framework's
     PARENT_TOOLS so the CLI never advertises them).
"""

import asyncio
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Coroutine

from config import PROJECT_ROOT

# Set WORKDIR for the agent framework before importing it
os.environ.setdefault("AGENT_WORKDIR", str(PROJECT_ROOT))

from agent.app import Agent, AgentCancelled
from agent.constants import USER_MEMORY_RECALL_DEFAULT_LIMIT
from agent_registry import get_agent_config

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=4)

_ALLOWED_CATEGORIES = ("preference", "fact", "feedback")

# Sentinel pushed onto the streaming queue to signal end-of-stream.
_STREAM_END = object()


def _env_flag(name: str, default: bool) -> bool:
    """Parse a boolean env var. Accepts 1/true/yes/on (case-insensitive)."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# Kill-switch for the user-memory feature. When ``USER_MEMORY_ENABLED=false``:
#   - StreamingAgentWrapper constructs ``Agent()`` with no memory kwargs,
#     so the three memory tools are not advertised, no handlers are wired,
#     and the guidance block is not injected into the system prefix.
#   - ``routers/chat.py`` skips the per-turn provider load and post-turn
#     flush, so no DB round-trips hit ``web_user_memory``.
#   - Any existing rows in ``web_user_memory`` are left untouched — flipping
#     the flag back on restores the prior behavior without data loss.
# Default is ``True`` so existing deployments get the feature automatically.
USER_MEMORY_ENABLED = _env_flag("USER_MEMORY_ENABLED", default=True)


# Kill-switch for chat history persistence. When ``CHAT_HISTORY_ENABLED=false``:
#   - No WebConversation or WebMessage rows are written or read.
#   - Message history is kept in-memory for the duration of the WebSocket
#     session only; it is lost when the connection closes.
#   - GET /api/conversations returns an empty list; mutation endpoints return 501.
#   - Conversation IDs are still minted (random UUIDs) and sent to the frontend
#     so the UI protocol is unchanged.
#   - Existing rows in web_conversations / web_messages are left untouched.
# Default is ``True`` so existing deployments are unaffected.
CHAT_HISTORY_ENABLED = _env_flag("CHAT_HISTORY_ENABLED", default=True)


# ---------------------------------------------------------------------------
# User-memory tool schemas (web only — NOT in framework/agent/tools.py)
# ---------------------------------------------------------------------------

USER_MEMORY_TOOL_SCHEMAS = [
    {
        "name": "remember_user",
        "description": (
            "Record a durable fact about the CURRENT user only (role, team, "
            "reporting scope, preferences, feedback). Persists across all of "
            "this user's future sessions but is invisible to other users. Use "
            "whenever the fact starts with 'I', 'my', 'we', or names a "
            "person-specific preference. Restating an existing fact refreshes "
            "its recency (bumps it to the top of the visible list); the tool "
            "returns 'Refreshed' — do not retry."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 500,
                    "description": (
                        "The fact to remember, in one self-contained sentence "
                        "(1-500 chars)."
                    ),
                },
                "category": {
                    "type": "string",
                    "enum": ["preference", "fact", "feedback"],
                    "description": (
                        "preference = stated preference; fact = stable fact "
                        "about the user; feedback = correction or guidance. "
                        "If none fits, do NOT call remember_user at all."
                    ),
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "recall_user",
        "description": (
            "Return up to `limit` most recent memories saved for the current "
            "user (default 100, hard max 500). Returns a JSON array string of "
            "{id, content, category, created_at, updated_at} — parse before "
            "using. Use when the user_memory block is capped and the fact you "
            "need might be among older memories hidden by the '(... N more "
            "...)' line."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                    "description": (
                        "Max number of memories to return. Default 100."
                    ),
                },
                "category": {
                    "type": "string",
                    "enum": ["preference", "fact", "feedback"],
                    "description": "Optional — filter to a single category.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "forget_user",
        "description": (
            "Delete a single user memory. Supply EITHER id (preferred) OR "
            "content_match (fuzzy). If content_match hits multiple memories, "
            "the tool returns a disambiguation list and deletes nothing — "
            "pick the right id and call again."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "minLength": 3,
                    "description": (
                        "UUID or 8-char prefix from the user_memory block "
                        "(min 3 chars)."
                    ),
                },
                "content_match": {
                    "type": "string",
                    "maxLength": 500,
                    "description": (
                        "Phrase to fuzzy-match against content. Server "
                        "returns candidates on ambiguity instead of deleting."
                    ),
                },
            },
        },
    },
]


class StreamingAgentWrapper:
    """One instance per (WebSocket, agent_id). Rebuilt when the user switches
    to a conversation bound to a different agent."""

    def __init__(self, agent_id: str | None = None):
        self.agent_id = agent_id
        cfg = get_agent_config(agent_id)
        # cfg may be None when no agents/ directory exists — fall back to the
        # framework's defaults (current single-agent behavior). When cfg is
        # present we pass its skill/tool dirs and per-agent system prompt.
        agent_kwargs: dict = {}
        if cfg is not None:
            self.agent_id = cfg.id
            agent_kwargs.update(
                skill_dirs=cfg.skill_dirs,
                tool_dirs=cfg.tool_dirs,
                system_prompt_path=cfg.system_prompt_path,
            )

        # Memory wiring is gated by the ``USER_MEMORY_ENABLED`` env flag. When
        # the flag is off, ``Agent()`` is constructed with no memory kwargs —
        # identical shape to the CLI path (no tools advertised, no handlers
        # registered, no guidance in the cached prefix).
        if USER_MEMORY_ENABLED:
            self._agent = Agent(
                extra_tools=USER_MEMORY_TOOL_SCHEMAS,
                extra_handlers={
                    "remember_user": self._handle_remember_user,
                    "recall_user":   self._handle_recall_user,
                    "forget_user":   self._handle_forget_user,
                },
                memory_tool_available=True,
                **agent_kwargs,
            )
        else:
            self._agent = Agent(**agent_kwargs)
            logger.info("user_memory.disabled_via_env_flag")

    # -- tool handlers ------------------------------------------------------
    # Handlers close over ``self._agent``; they read the current provider from
    # ``self._agent.system.user_memory``, which ``set_user_memory`` updates
    # before each turn. If no provider is attached (should never happen on
    # the web path, but guard against misuse) they return a sentinel string
    # rather than raising.

    def _handle_remember_user(self, **kw):
        provider = self._agent.system.user_memory
        if provider is None:
            return "User memory unavailable in this mode (CLI)."
        result = provider.add(kw["content"], kw.get("category"))
        logger.info(
            "user_memory.add user=%s len=%d",
            provider.user_id,
            len(kw.get("content") or ""),
        )
        return result

    def _handle_recall_user(self, **kw):
        provider = self._agent.system.user_memory
        if provider is None:
            return "User memory unavailable in this mode (CLI)."
        # Defensive coercion: the schema says integer, but Claude sometimes
        # emits stringified numbers and prompt-injected payloads can pass
        # garbage. Fall back to the default on failure rather than raising.
        raw = kw.get("limit", USER_MEMORY_RECALL_DEFAULT_LIMIT)
        try:
            lim = max(1, min(int(raw), 500))
        except (TypeError, ValueError):
            lim = USER_MEMORY_RECALL_DEFAULT_LIMIT
        cat = kw.get("category")
        if cat not in _ALLOWED_CATEGORIES:
            cat = None
        payload = json.dumps(
            provider.list(limit=lim, category=cat),
            default=str,
        )
        logger.info(
            "user_memory.recall user=%s limit=%d category=%s bytes=%d",
            provider.user_id, lim, cat, len(payload),
        )
        return payload

    def _handle_forget_user(self, **kw):
        provider = self._agent.system.user_memory
        if provider is None:
            return "User memory unavailable in this mode (CLI)."
        result = provider.remove(
            id=kw.get("id"),
            content_match=kw.get("content_match"),
        )
        logger.info(
            "user_memory.forget user=%s id=%s match=%s",
            provider.user_id,
            (kw.get("id") or "")[:8],
            (kw.get("content_match") or "")[:40],
        )
        return result

    # -- main streaming loop ------------------------------------------------

    async def run_streaming(
        self,
        messages: list[dict],
        send_event: Callable[[dict], Coroutine[Any, Any, None]],
        user_memory_provider=None,
        cancel_event=None,
    ):
        """Run the agent loop, streaming events via send_event callback.

        If ``user_memory_provider`` is supplied it is attached to the agent
        before the turn starts; the tool handlers above then see it via
        ``self._agent.system.user_memory``. When the ``USER_MEMORY_ENABLED``
        flag is off the provider is ignored (the memory tools are not
        registered, so nothing would read from it anyway).

        ``cancel_event`` is an optional ``threading.Event`` forwarded to
        ``Agent.run``; when set (WebSocket stop/disconnect) the run aborts at
        its next checkpoint. A cancelled run is treated as a graceful stop —
        we still emit the terminal ``done`` event so the client unlocks.
        """
        if USER_MEMORY_ENABLED and user_memory_provider is not None:
            self._agent.system.set_user_memory(user_memory_provider)

        loop = asyncio.get_event_loop()
        # Hand events from the worker thread to the event loop over an
        # asyncio.Queue. The worker pushes via loop.call_soon_threadsafe so
        # puts are serialized onto the loop thread (no shared-list races, no
        # O(n) pop(0)). A sentinel marks end-of-stream for clean shutdown.
        queue: asyncio.Queue = asyncio.Queue()

        def on_event(event: dict):
            """Synchronous callback from Agent.run() (worker thread)."""
            # Extract chart URL for tool results that produce HTML files
            if event.get("type") == "tool_result":
                output = event.get("output", "")
                # Try structured JSON with html_path
                try:
                    parsed = json.loads(output)
                    if isinstance(parsed, dict) and "html_path" in parsed:
                        filename = os.path.basename(parsed["html_path"])
                        event["chart_url"] = f"/files/{filename}"
                except (json.JSONDecodeError, ValueError, KeyError):
                    pass
                # Fallback: scan for tmp/*.html references in raw output
                if "chart_url" not in event:
                    match = re.search(r'tmp/[\w._-]+\.html', output)
                    if match:
                        filename = os.path.basename(match.group())
                        event["chart_url"] = f"/files/{filename}"
                # Truncate output for WebSocket transport
                if len(event.get("output", "")) > 2000:
                    event["output"] = event["output"][:2000]

            loop.call_soon_threadsafe(queue.put_nowait, event)

        def _run_blocking():
            # Always push the sentinel — even on exception — so the consumer
            # below terminates; the exception is re-raised via ``await task``.
            try:
                self._agent.run(messages, on_event=on_event, cancel_event=cancel_event)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, _STREAM_END)

        task = loop.run_in_executor(_executor, _run_blocking)

        # Drain the queue, coalescing runs of consecutive text_delta events
        # into a single send (fewer WebSocket frames; ordering preserved).
        while True:
            event = await queue.get()
            if event is _STREAM_END:
                break
            if not (isinstance(event, dict) and event.get("type") == "text_delta"):
                await send_event(event)
                continue
            parts = [event.get("text", "")]
            leftover = None
            while not queue.empty():
                nxt = queue.get_nowait()
                if isinstance(nxt, dict) and nxt.get("type") == "text_delta":
                    parts.append(nxt.get("text", ""))
                else:
                    leftover = nxt
                    break
            await send_event({"type": "text_delta", "text": "".join(parts)})
            if leftover is _STREAM_END:
                break
            if leftover is not None:
                await send_event(leftover)

        # Propagate any exception raised inside the worker thread. A cancelled
        # run is expected (user stop / disconnect) — swallow it and fall
        # through to ``done`` so the client unlocks rather than seeing an error.
        try:
            await task
        except AgentCancelled:
            logger.info("agent.run cancelled (stop/disconnect)")

        await send_event({"type": "done"})
