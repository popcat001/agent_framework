# agent_framework — AI Agent Framework

A lightweight, extensible, production-ready framework for building conversational AI agents — with streaming web UI, auto tool/skill discovery, and single-config rebranding. The agent runs as an interactive REPL (standalone) or a streaming Web UI (when embedded as a submodule in a project repo). The framework can only run the REPL on its own — the Web UI requires a parent project to provide configuration, skills, and tools.

Ref: https://github.com/shareAI-lab/learn-claude-code

---

## Recent Updates

- **2026-05-31 — `MULTI_AGENT_ENABLED` kill-switch + configurable backend port.** Setting `MULTI_AGENT_ENABLED=false` bypasses the agents registry and per-agent ACL checks, so the server runs on framework defaults with no `agents/` directory required. `BACKEND_PORT` in `.env` is now read directly by `vite.config.ts` so the Vite proxy follows the backend port without a shell env var.
- **2026-05-28 — Reliability + security hardening.** WebSocket stop/disconnect now propagates a `cancel_event` into `Agent.run` (`AgentCancelled`) so abandoned runs stop instead of streaming into a dead socket; streaming switched from shared-list polling to an `asyncio.Queue` with coalesced text deltas; tool events carry `tool_use_id` so parallel same-named calls resolve independently; the `/files` route is path-traversal-checked; expired sessions surface a refresh modal (WS close + REST 401 share one signal). The `task`/subagent system was removed — the agent is a single tool tier.
- **2026-05-15 — Per-agent access control + Admin UI.** DB-backed 2-tier access control (L1 super-admin via env var, L2 agent-admin via `web_agent_admins` table). Unprovisioned users fall back to a configured default agent. `enabled` flag in `agent.yaml` hides agents from the sidebar without deleting files. Admin UI for managing grants shipped 2026-05-18.
- **2026-05-07 — Multi-agent architecture.** `SkillLoader`, `ToolLoader`, and `Agent` now accept a list of directories, so each agent layers its own skills/tools/system-prompt on top of the shared set. Powers the AGENTS sidebar in the web UI; tool-name collisions across dirs raise `ToolCollisionError` at startup.
- **2026-04-27 — Slack / Teams bot integration.** Bot-token auth (`RTB_BOT_SHARED_TOKEN`), `source` column on conversations tracking `web` / `slack` / `team` origin. Bot channels share the same agent loop as the web UI.
- **2026-04-21 — User-level memory.** Per-user persistent memory (preferences, facts, feedback) backed by `web_user_memory` Postgres table. Three agent tools: `remember_user`, `recall_user`, `forget_user`. Top 15 entries injected into system prompt each turn; older entries reachable on demand via `recall_user`. Kill-switch: `USER_MEMORY_ENABLED=false`.
- **2026-04-02 — Web UI.** Full React/Vite frontend with WebSocket streaming, conversation history, chart iframes, multi-agent sidebar, and Azure EasyAuth. The REPL and web UI share the same agent loop — no duplicated logic.

---

## Setup

```bash
# Install dependencies
uv sync

# Configure environment — set ANTHROPIC_FOUNDRY_API_KEY and ANTHROPIC_FOUNDRY_RESOURCE
cp .env.example .env
```

---

## Running (REPL)

```bash
uv run agent/app.py
```

```
agent >> write a FastAPI server with CRUD endpoints for a todo list
agent >> /exit
```

Type `/exit` or `/quit` to close the REPL.

> **Lightweight by design.** The REPL needs only `ANTHROPIC_FOUNDRY_API_KEY` / `ANTHROPIC_FOUNDRY_RESOURCE` — no Postgres, no chat-history persistence, and no user-memory tools. All of that is wired in by the web wrapper, not the framework core. If your project's tools hit a DB, they'll still need their own credentials, but the framework itself stays DB-free.

---

## Capabilities

### 1. Todo Tracking
The agent maintains a live todo list to plan and track multi-step tasks. It marks items `pending → in_progress → completed` as it works, and receives reminders to keep the list up to date.

### 2. Skill Loading
Skills are Markdown documents in `skills/<name>/SKILL.md` with YAML frontmatter. The agent sees a list of available skill names in its system prompt and can load the full content of any skill on demand via the `load_skill` tool — keeping the base context lean.

```
skills/
└── <name>/
    └── SKILL.md    ← YAML frontmatter (name, description, tags) + body
```

### 3. Context Compaction
Two-layer compression lets the agent run indefinitely without hitting context limits:

| Layer | Trigger | Action |
|-------|---------|--------|
| **Auto** | Estimated tokens > 50,000 | Summarises full conversation, saves transcript to `.transcripts/` |
| **Manual** | Agent calls `compact` tool | Same as auto, agent-initiated |

> **Note:** Micro compaction (truncating old tool results to keep only the 3 most recent) is disabled. Aggressively discarding tool results loses important context that the agent may need to reference later — a poor trade-off for token savings.

### 4. Shell Execution with Safety Filtering
The `bash` tool runs arbitrary shell commands in a subprocess (cwd = project root, 120-second timeout). A hardcoded blocklist prevents the most dangerous commands (`rm -rf /`, `sudo`, `shutdown`, `reboot`, `> /dev/`). Both stdout and stderr are captured and returned to the agent.

### 5. Dynamic Tool Loading
When embedded in a project repo, the `ToolLoader` auto-discovers all `.py` files in the project's `tools/` directory. Each file exports a `__tools__` list of function names. Function signatures and docstrings are introspected to generate Claude tool schemas automatically — no manual schema authoring required.

### 6. Parallel Tool Execution
When the LLM requests multiple tool calls in a single turn, they execute concurrently using a ThreadPoolExecutor (up to 8 workers). Single tool calls run sequentially to avoid thread overhead.

### 7. Streaming Event System
`Agent.run()` accepts an optional `on_event` callback that emits real-time events (`text_delta`, `tool_start`, `tool_result`) as the agent works. This is the foundation for the Web UI — the REPL and Web UI share the same agent loop, differing only in how events are consumed.

### 8. User Memory (Web UI only)
Per-user persistent memory — preferences, facts, and feedback the agent saves across conversations. Three tools the agent can call: `remember_user` (save or refresh), `recall_user` (fetch older entries beyond the always-visible top-15), `forget_user` (delete by id or fuzzy match). Registered only by the web wrapper via `extra_tools` / `extra_handlers` kwargs on `Agent()` — the REPL never advertises them, so its request shape stays byte-identical to pre-feature. The system prompt is split into a cached prefix and an uncached per-turn suffix so memory churn only invalidates the short tail. Stored in a `web_user_memory` Postgres table; per-user cap of 500 rows with eviction at flush. Kill-switch: `USER_MEMORY_ENABLED=false` disables the feature entirely without touching stored data.

### 9. Per-Agent Access Control (Web UI only)
DB-backed restrictions for who can see and use each agent. **Unprovisioned users (zero rows in `web_agent_access`) see only the configured default agent;** provisioned users get per-agent rules (every agent requires an explicit grant row — no public fallthrough). Kill-switch: `MULTI_AGENT_ENABLED=false` disables the agents registry and all ACL checks — the server runs on framework defaults with no `agents/` directory required.

**What users experience.** Restricted agents are hidden from the sidebar (`GET /api/agents` filters server-side). Denied API calls return `403`. Old conversations remain accessible after revoke — v1 only gates new conversation starts (retroactive cutoff is a deferred followup, see `plans/plan_agent_access_control_db.md`).

**Tiers** (resolution order, top wins):
1. `DEV_MODE=true` — bypass everything
2. **L1 super admin** — emails in `ADMIN_EMAILS` env var (comma-separated); sees and uses every agent; static, requires restart
3. **L2 agent admin** — rows in `web_agent_admins` (`agent_id`, `email`); implicit access to that agent + manages its grants (UI in Stage 2); dynamic
4. **Unprovisioned user fallback** — user has zero rows in `web_agent_access` → True only for the configured default agent
5. **Granted user** — rows in `web_agent_access` (`agent_id`, `email`); access to that one agent. Every other agent still requires its own explicit grant row — there is no "zero rows = public" fallthrough for provisioned users.
6. Otherwise → deny

**Default agent for unprovisioned users.** Configured via `DEFAULT_AGENT_FOR_UNASSIGNED` env var; falls back to the registry's `default: true` agent if unset. Set it in `.env` (local dev) or as an App Service environment variable (Azure portal → *Settings → Environment variables → App settings*, or `az webapp config appsettings set --settings DEFAULT_AGENT_FOR_UNASSIGNED=<agent-id>`). Restart to apply.

Both DB tables enforce `CHECK email = lower(email)` to prevent silent-typo mismatches. No cache — every change takes effect on the next request. Helpers: `agent_acl.can_user_access`, `list_accessible_agents`, `is_admin`, `is_agent_admin`, `default_agent_for_unassigned`. Slack/Teams aren't gated per-user — they're channel-bound, so access is managed via channel membership.

---

## Web UI

A streaming chat interface that runs the same agent loop as the REPL — no duplicated logic. **The Web UI requires a parent project repo** (see [Using as a Submodule](#using-as-a-submodule-in-a-project-repo)) to provide project-specific configuration, skills, tools, and branding. It cannot run from the framework alone.

### Tech Stack

| Layer | Stack |
|-------|-------|
| **Backend** | FastAPI, SQLAlchemy + asyncpg (PostgreSQL), Azure AD SSO (MSAL) |
| **Frontend** | React 19, TypeScript, Tailwind CSS, Vite, React Markdown |
| **Streaming** | WebSocket with event-based protocol |

### How It Works

The backend's `agent_wrapper.py` is a thin async bridge: it runs `Agent.run(on_event=callback)` in a thread executor and relays events to the frontend over a WebSocket. The frontend accumulates `text_delta` events into the response and renders `tool_start` / `tool_result` events inline.

### WebSocket Protocol

**Client → Server:**
```json
{ "type": "user_message", "conversation_id": "uuid|null", "content": "text" }
{ "type": "stop" }
```

**Server → Client:**

| Event | Description |
|-------|-------------|
| `text_delta` | Streamed chunk of response text (consecutive deltas are coalesced into one frame) |
| `tool_start` | Agent is calling a tool (`name` + `input` + `tool_use_id`) |
| `tool_result` | Tool output (`tool_use_id`, optional `chart_url`); the frontend matches results to calls by `tool_use_id` so parallel same-named calls resolve independently |
| `conversation_created` | New conversation ID assigned (first message only) |
| `assistant_persisted` | Backend committed the assistant message (carries its DB `message_id`) |
| `done` | Stream complete |
| `error` | Error description |

A client `{ "type": "stop" }` frame (or a disconnect) signals cancellation: the backend runs each turn as a background task and sets a `cancel_event` the agent loop polls, so a long LLM/tool run aborts promptly rather than streaming into a dead socket.

Charts are extracted from tool outputs and served via `/files/<chart>.html` for inline iframe rendering.

### Database Setup

The Web UI persists chat history, user memory, and report-chart blobs to PostgreSQL so state survives across sessions and across multi-instance deployments. The DB user must have `CREATE TABLE` permission — the following tables are created automatically on first startup if they don't exist:

| Table | Purpose |
|-------|---------|
| `web_users` | One row per user, keyed by Azure AD OID |
| `web_conversations` | One row per chat session, linked to a user |
| `web_messages` | All messages (user + assistant) stored as JSONB |
| `web_charts` | Chart blobs (e.g. report PNGs) served via `/files/<filename>` |
| `web_user_memory` | Per-user persistent memory (preferences, facts, feedback) |
| `web_agent_access` | Per-agent grants (`agent_id`, `email`) |
| `web_agent_admins` | Per-agent L2 admins (`agent_id`, `email`) |

No manual migration is needed — SQLAlchemy handles table creation automatically (see `web/backend/database.py:init_db()`). On every backend boot, `init_db()` also prunes expired rows from `web_charts`: any row whose `filename` starts with `report_` and is older than 360 days is deleted.

Required `.env` variables for the DB connection:

| Variable | Description |
|----------|-------------|
| `DB_HOST` | PostgreSQL host |
| `DB_PORT` | PostgreSQL port (typically `5432`) |
| `DB_NAME` | Database name |
| `DB_USER` | Database user (must have `CREATE TABLE`) |
| `DB_PASSWORD` | Database password (the legacy `DB_PWD` is also accepted) |

Projects may add their own tables on top of the framework's by defining ORM models at `<project>/web/backend/models_project.py`; `init_db()` auto-discovers and creates them alongside the framework tables.

### File Storage (`tmp/` folder)

The framework also reserves a project-root `tmp/` directory for files that don't belong in the DB — typically Plotly chart HTML written by tools or agent-generated bash plots. The folder is auto-created on backend startup and served via the same `/files/{filename}` route — DB lookup first, then disk fallback (`web/backend/main.py:serve_file()`). The disk path is containment-checked (`resolve()` + `is_relative_to(tmp_root)`) so encoded `../` filenames can't escape `tmp/`.

**Retention policy:** on every backend startup, `_prune_tmp_charts()` deletes any `tmp/*.html` whose mtime is older than 30 days. The default cutoff lives in `web/backend/main.py` and can be adjusted by passing `max_age_days` to the function.

**Deployment notes:**
- On Azure App Service Linux, `tmp/` resolves to `/home/site/wwwroot/tmp`, which is on Azure Files — persistent across restarts and shared across all instances on the plan, so a single sweep affects all instances.
- The sweep runs only at startup, so it relies on App Service worker recycles (deploys, idle restarts, scaling events) to fire periodically. If your container runs continuously for >30 days, add a daily background job to call `_prune_tmp_charts()` on a schedule.
- Concurrent prunes from multiple instances are safe — `OSError` from racing `unlink()` calls is swallowed.

### Running (from parent project root)

```bash
# Install dependencies
uv sync --extra web
cd framework/web/frontend && npm install && cd -

# Start backend (from project root)
PYTHONPATH=framework/web/backend:framework uv run uvicorn main:app \
  --reload --reload-dir framework/web/backend --port 8000 \
  --app-dir framework/web/backend

# Start frontend (separate terminal)
npm run dev --prefix framework/web/frontend   # http://localhost:5173
```

Set `DEV_MODE=true` in `.env` to bypass Azure AD SSO during development. Set `MULTI_AGENT_ENABLED=false` to skip the agents registry (no `agents/` directory needed). Set `BACKEND_PORT` in `.env` to control which port the Vite proxy targets (default `8000`).

### Project Customization

The Web UI is designed to be branded per-project without modifying framework code. All project-specific overrides live outside `framework/`.

**`web/project-config.ts`** — export a `projectOverrides` object to customize:

| Field | What it controls |
|-------|-----------------|
| `name` | App name in titles and message labels |
| `tagline` | Login page subtitle |
| `appLogo` / `orgLogo` | Logo paths (place files in `web/public/`) |
| `pageTitle` | Browser tab title |
| `favicon` | Favicon path |
| `disclaimer` | Footer text below chat input |
| `theme` | Color scheme — CSS custom properties (`accent`, `bgPrimary`, etc.) |
| `sampleQuestions` | Welcome screen cards — Lucide icon name + text |

**`web/public/`** — static assets (logos, favicon). Auto-detected by Vite.

**`web/pages/index.ts`** — export a `PageDefinition[]` to add tabs beyond the default chat tab.

Vite resolves `@project/config` and `@project/pages` aliases automatically by checking for these files in the parent project directory.

### Web UI Structure

```
web/
├── backend/
│   ├── main.py              # FastAPI app + middleware setup
│   ├── agent_wrapper.py     # Async bridge — Agent.run() → WebSocket events
│   ├── auth.py              # Azure AD token validation
│   ├── config.py            # Auto-detects project root, loads .env
│   ├── database.py          # SQLAlchemy async engine (PostgreSQL)
│   ├── models.py            # ORM models (web_users, web_conversations, web_messages, web_charts, web_user_memory)
│   └── routers/
│       ├── auth.py          # SSO login endpoints
│       ├── chat.py          # WebSocket endpoint — streams events
│       └── conversations.py # REST CRUD for chat history
└── frontend/
    └── src/
        ├── App.tsx                  # Router + auth provider
        ├── components/Layout.tsx    # Main shell: sidebar + tabs + chat
        ├── hooks/useWebSocket.ts    # Client-side streaming state
        ├── config/                  # Project config merge logic
        ├── contexts/                # Auth + app context providers
        ├── pages/                   # Chat page + custom page slots
        └── services/                # API client helpers
```

---

## Project Structure

```
agent_framework/
├── agent/
│   ├── app.py          # Agent class + REPL entrypoint
│   ├── compaction.py   # auto_compact, estimate_tokens
│   ├── constants.py    # WORKDIR, paths, thresholds, memory caps
│   ├── memory.py       # PreloadedUserMemoryProvider + SystemBuilder (web-only memory)
│   ├── skills.py       # SkillLoader (multi-dir)
│   ├── tool_loader.py  # ToolLoader (auto-discovers project tools, multi-dir)
│   ├── todo.py         # TodoManager
│   └── tools.py        # Tool implementations + schemas
├── web/
│   ├── backend/        # FastAPI + WebSocket streaming server
│   └── frontend/       # React + TypeScript chat UI
├── skills/             # Skill definitions (SKILL.md per skill)
├── .transcripts/       # Auto-saved conversation transcripts
├── config.py           # Anthropic client + model config
└── pyproject.toml      # uv project config (Python >= 3.11)
```

---

## Security

### `bash` tool — unrestricted shell access

The agent has a `bash` tool that executes arbitrary shell commands in a subprocess. **This is a significant security risk if you run untrusted tasks or expose the agent to untrusted input.**

Specific risks:
- **Full filesystem access** — the agent can read, write, or delete any file your OS user can access, not just files within the project directory
- **Network access** — the agent can make outbound connections (`curl`, `wget`, `ssh`, etc.)
- **Process execution** — the agent can spawn arbitrary processes, including other shells or interpreters
- **No escape prevention** — the `cwd=WORKDIR` only sets the starting directory; the agent can `cd` out of it freely

The only commands blocked are a small hardcoded list (`rm -rf /`, `sudo`, `shutdown`, `reboot`, `> /dev/`), which is easy to work around.

**Mitigations to consider:**
- Run the agent inside a container or VM with limited permissions
- Use OS-level sandboxing (`firejail`, macOS Sandbox, `seccomp`)
- Replace the `bash` tool with a Python execution tool for reduced shell exposure
- Only run trusted tasks from trusted input sources

---

## Adding Skills

Create a new directory under `skills/` with a `SKILL.md` file:

```markdown
---
name: my-skill
description: Brief description shown in the agent's system prompt
tags: python, api
---

Full skill content here. Injected into context when the agent calls load_skill.
```

The agent discovers skills automatically on next startup.

---

## Using as a Submodule in a Project Repo

This framework is designed to be embedded as a git submodule inside project repos. This gives you full freedom to edit framework files within the project, push improvements back upstream, and pull new framework updates per-project on your own schedule.

### Initial setup

```bash
# Inside your project repo
git submodule add <framework-repo-url> framework
git commit -m "add agent_framework submodule"
```

Recommended project layout:

```
my-project/
├── framework/          ← submodule (agent_framework)
│   ├── agent/
│   ├── skills/
│   └── pyproject.toml
├── skills/             ← project-specific skills (optional)
└── src/                ← your project code
```

Clone a project that already has the submodule:

```bash
git clone --recurse-submodules <project-repo-url>
# or, if already cloned without --recurse-submodules:
git submodule update --init
```

### Pulling framework updates into a project

```bash
git submodule update --remote framework
git commit -m "bump framework"
```

This advances the submodule pointer to the latest commit on the framework's default branch. Resolve any conflicts as you would a normal merge.

### Pushing framework improvements upstream

Edit files inside `framework/` freely. When you have a fix or feature worth sharing:

```bash
cd framework/
git add <files>
git commit -m "fix: ..."
git push origin main        # pushes to the framework repo
cd ..
git add framework
git commit -m "bump framework"  # records the new submodule pointer
```

### Keeping projects independent

Each project pins to a specific framework commit. Two projects can be on different framework versions simultaneously — bumping one does not affect the other.
