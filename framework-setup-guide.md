# agent_framework Setup Guide

---

## Prerequisites

- Python 3.11+, [uv](https://docs.astral.sh/uv/), Node.js 18+, Git

---

## 1. Create your project

```bash
mkdir my_project && cd my_project
git init
git clone <framework-repo-url> framework
```

---

## 2. Add web dependencies

Open `framework/pyproject.toml` and add to `dependencies`:

```toml
"fastapi>=0.115.0",
"uvicorn[standard]>=0.30.0",
"sqlalchemy[asyncio]>=2.0.0",
"asyncpg>=0.29.0",
"psycopg2-binary>=2.9.0",
"greenlet>=3.0.0",
"httpx>=0.27.0",
"pydantic>=2.0.0",
"python-multipart>=0.0.9",
```

```bash
cd framework && uv sync && cd ..
```

> Use plain `uv sync` — never `uv sync --extra web` (the extra doesn't exist).

---

## 3. Create project structure

```bash
mkdir -p prompts skills tools web/public
```

```
my_project/
├── framework/           ← framework code (don't edit)
├── prompts/system.md    ← agent system prompt
├── skills/              ← skills (auto-discovered)
├── tools/               ← tools (auto-discovered)
├── web/
│   ├── public/          ← logos, favicon
│   └── project-config.ts
└── .env
```

---

## 4. Configure .env

Place `.env` at your **project root** — the framework auto-detects it here.

```bash
ANTHROPIC_FOUNDRY_API_KEY=...
ANTHROPIC_FOUNDRY_RESOURCE=...
CLAUDE_MODEL=claude-sonnet-4-6
APP_NAME=my_project

DEV_MODE=true               # bypasses Azure AD auth
CHAT_HISTORY_ENABLED=false  # no PostgreSQL needed when false
USER_MEMORY_ENABLED=false   # no PostgreSQL needed when false
```

With all three flags set as above, **no database is required**.

---

## 5. Write system prompt

`prompts/system.md`:

```markdown
You are My Agent, an AI assistant for [purpose].

Working directory: {workdir} — do NOT use `cd`.
- Use todo tool for multi-step tasks.
- Call load_skill before answering domain questions.

{skill_descriptions}

{memory_guidance}
```

`{workdir}`, `{skill_descriptions}`, `{memory_guidance}` are filled automatically.

---

## 6. Add a skill

`skills/my-skill/SKILL.md`:

```markdown
---
name: my-skill
description: One-line description (shown in system prompt)
tags: keyword1, keyword2
---

Instructions for the agent: when to use this skill, what files to read,
what tools to call, how to interpret results.
```

Put reference docs in `skills/my-skill/docs/` and tell the agent to load them with `read_file`.

---

## 7. Add a tool

`tools/my_tool.py`:

```python
def my_function(input: str) -> str:
    """What this tool does.

    Args:
        input: Description of this parameter.
    """
    return f"result: {input}"

__tools__ = ["my_function"]
```

Type hints → schema types. Docstring → description. `Args:` → parameter descriptions. No registration needed — auto-discovered on startup.

---

## 8. Run

**REPL** (always from project root):
```bash
PYTHONPATH=framework uv run --project framework framework/agent/app.py
```

**Web UI backend:**
```bash
PYTHONPATH=framework uv run --project framework uvicorn main:app \
  --reload --reload-dir framework/web/backend --port 8000 \
  --app-dir framework/web/backend
```

**Web UI frontend** (separate terminal):
```bash
npm install --prefix framework/web/frontend   # first time only
npm run dev --prefix framework/web/frontend   # → http://localhost:5173
```

---

## 9. Customize the Web UI

`web/project-config.ts`:

```typescript
export const projectOverrides = {
  name: "My Project",
  tagline: "What it does",
  appLogo: "/my_logo.svg",
  favicon: "/my_icon.svg",
  pageTitle: "My Project — AI",
  disclaimer: "Verify important information.",
  theme: {
    bgPrimary: "#ffffff", bgSidebar: "#f5f5f7", bgInput: "#ffffff",
    textPrimary: "#1d1d1f", textSecondary: "#6e6e73",
    accent: "#0071e3", accentHover: "#0077ed", border: "#d2d2d7",
  },
  sampleQuestions: [
    { icon: "BookOpen", text: "What is X?" },
    { icon: "BarChart3", text: "Show me last quarter data" },
  ],
};
```

Place SVG/PNG files in `web/public/`. Icons are [Lucide](https://lucide.dev/icons/) names.

---

## Common pitfalls

| Error | Fix |
|---|---|
| `Failed to spawn: uvicorn` | Add web deps to `pyproject.toml`, re-run `uv sync` |
| `Extra 'web' is not defined` | Use `uv sync`, not `uv sync --extra web` |
| `No module named 'greenlet'` | Add `greenlet>=3.0.0` and `sqlalchemy[asyncio]` to pyproject.toml |
| `[Errno 61] Connection refused` | Set `CHAT_HISTORY_ENABLED=false` and `USER_MEMORY_ENABLED=false` |
| Skills/tools not loading | Run from project root, not from inside `framework/` |
