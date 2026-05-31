# Code Structure: `agent_framework`

## 🗂️ Project Layout

```
agent_framework/
├── config.py               # Anthropic client + model config (framework root)
└── agent/
    ├── app.py               # Core Agent class + REPL loop + agent loop
    ├── tools.py             # Tool schemas + handler implementations
    ├── compaction.py        # Context compression logic
    ├── config.py            # LLM client, model, system-prompt renderer
    ├── constants.py         # Shared constants (WORKDIR, COMPACT_THRESHOLD, memory caps)
    ├── skills.py            # SkillLoader (on-demand knowledge injection; multi-dir)
    ├── tool_loader.py       # ToolLoader (auto-discovers project tools; multi-dir)
    ├── memory.py            # SystemBuilder + user-memory provider (web-only)
    └── todo.py              # Todo list manager
```

---

## 🧩 Module Breakdown

### `agent/app.py` — Core Agent
The heart of the framework. The `Agent` class orchestrates the entire agentic loop:

- **`chat()`** — Interactive REPL that reads user input and calls `run()`.
- **`run(messages, on_event=None, cancel_event=None)`** — The main agentic loop with **2-layer context compression**:
  1. **Auto-compact** — triggered when token estimate exceeds `COMPACT_THRESHOLD`
  2. **Manual compact** — triggered when the agent calls the `compact` tool
- **Cancellation** — an optional `cancel_event` (`threading.Event`) is polled at checkpoints (between rounds, mid-stream, before tool execution); when set, `run()` raises `AgentCancelled` so a caller (e.g. the WebSocket layer on stop/disconnect) can abort an in-flight run.
- **Nag reminder** — If the agent hasn't called `todo` in 4+ rounds, a todo reminder is injected automatically.

> **Note:** The `task`/subagent system was removed (commit `3d53600`). The agent no longer spawns child agents; there is a single tool tier (see below).

---

### `agent/tools.py` — Tool Definitions & Handlers

Two tool sets:

| Tool Set | Tools | Notes |
|---|---|---|
| `BASE_TOOLS` | `bash`, `read_file`, `write_file`, `edit_file` | Filesystem + shell; handlers in `BASE_HANDLERS` |
| `PARENT_TOOLS` | `BASE_TOOLS` + `load_skill`, `todo`, `compact` | The agent's full toolset |

Safe path enforcement (`safe_path()`) resolves paths under `WORKDIR` for file operations.

---

### `agent/compaction.py` — Context Compression
Implements the compression strategy:
- **`auto_compact`** — Summarizes the conversation when tokens exceed the threshold
- **`estimate_tokens`** — Cheap token count estimation

---

### `agent/config.py` — LLM Configuration
- Holds the Anthropic `client` instance and `MODEL` name (`CLAUDE_MODEL` env var, default `claude-sonnet-4-6`)
- Defines `system_prompt()`, which renders the prompt template with skill descriptions (accepts a `template_path` override for per-agent prompts)

---

### `agent/constants.py` — Shared Constants
- `WORKDIR` — The root directory the agent is allowed to operate in
- `COMPACT_THRESHOLD` — Token count that triggers auto-compaction

---

### `agent/skills.py` — On-Demand Skill Loading
- `SkillLoader` manages a library of specialized knowledge snippets
- Skills are listed by name in the system prompt (Layer 1)
- Full skill content is only injected when `load_skill` is called (Layer 2), keeping the context lean

---

### `agent/todo.py` — Task Tracking
- `TodoManager` maintains a simple todo list with `pending`, `in_progress`, and `completed` states
- The agent is nudged to keep it up to date via the nag reminder system

---

## 🏛️ Architecture Summary

```
User Input
    │
    ▼
Agent.chat() [REPL]
    │
    ▼
Agent.run() [Loop]
    ├── cancel checkpoint (raises AgentCancelled if cancel_event set)
    ├── auto_compact() if needed ← compression
    ├── LLM Call (PARENT_TOOLS)
    ├── Tool dispatch
    │   ├── bash / read_file / write_file / edit_file  ← filesystem
    │   ├── load_skill   ← inject knowledge on demand
    │   ├── todo         ← track task progress
    │   └── compact      ← manual compression
    └── Nag reminder if todo neglected ≥ 4 rounds
```

---

## Key Design Principles
1. **Two-layer compression** — Auto + manual compaction keep the agent running without hitting context limits.
2. **Lazy skill loading** — Skills are loaded on demand to conserve context.
3. **Multi-dir skills/tools** — `SkillLoader` and `ToolLoader` take a list of dirs so each agent layers its own on top of the shared set.
4. **Nag mechanism** — Enforces discipline around todo tracking automatically.
5. **Cooperative cancellation** — `run()` polls a `cancel_event` at checkpoints so long runs abort promptly on stop/disconnect.
