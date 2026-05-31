"""Per-agent access control helpers.

Two admin tiers:
  - **L1 super admin** — listed in ``ADMIN_EMAILS`` env var (comma-separated,
    case-insensitive). Sees and uses every agent. Static; requires backend
    restart to update.
  - **L2 agent admin** — rows in ``web_agent_admins`` (agent_id, email).
    Implicit access to that agent + ability to grant access on it (the grant
    UI lands in Stage 2; the data model is set up here). Dynamic; managed
    via psql or the future admin UI.

Access resolution (top wins):
  1. ``DEV_MODE=true`` → True
  2. L1 super admin → True
  3. L2 agent admin for ``agent_id`` → True
  4. User has zero grant rows AND ``agent_id`` is the configured default
     (``DEFAULT_AGENT_FOR_UNASSIGNED`` env var, falling back to the registry's
     ``default: true`` agent) → True (default-agent fallback for unprovisioned
     users)
  5. User has zero grant rows AND ``agent_id`` is *not* the default → False
     (unprovisioned users only see the default agent — no public-by-default
     fallthrough)
  6. ``user_email`` listed in ``web_agent_access`` for ``agent_id`` → True
  7. Otherwise → False (no per-agent public fallback — every agent must be
     explicitly granted)
"""

from __future__ import annotations

import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_registry import AgentConfig, default_agent_id, list_agents
from config import DEV_MODE
from models import WebAgentAccess, WebAgentAdmin

# L1 super admin allowlist. Parsed once at import; flip via env + restart.
ADMIN_EMAILS: frozenset[str] = frozenset(
    e.strip().lower()
    for e in os.environ.get("ADMIN_EMAILS", "").split(",")
    if e.strip()
)


def default_agent_for_unassigned() -> str | None:
    """Agent id shown to users with no grant rows. Env override
    ``DEFAULT_AGENT_FOR_UNASSIGNED`` takes precedence over the registry's
    ``default: true`` agent so operators can swap the fallback without
    editing yaml. Read on every call so a restart picks up env changes
    without import-time caching surprises during tests."""
    env = os.environ.get("DEFAULT_AGENT_FOR_UNASSIGNED", "").strip()
    return env or default_agent_id()


async def _user_has_any_grants(db: AsyncSession, user_email: str) -> bool:
    row = await db.scalar(
        select(WebAgentAccess.email)
        .where(WebAgentAccess.email == user_email.lower())
        .limit(1)
    )
    return row is not None


def is_admin(user_email: str) -> bool:
    """L1 super admin check (env-based, sync)."""
    return user_email.lower() in ADMIN_EMAILS


async def _agent_admin_ids(db: AsyncSession, user_email: str) -> set[str]:
    """Agent ids for which ``user_email`` is an L2 admin."""
    rows = (
        await db.execute(
            select(WebAgentAdmin.agent_id).where(
                WebAgentAdmin.email == user_email.lower()
            )
        )
    ).scalars().all()
    return set(rows)


async def is_agent_admin(
    db: AsyncSession, user_email: str, agent_id: str,
) -> bool:
    """L2 agent admin check for a specific agent."""
    row = await db.scalar(
        select(WebAgentAdmin.email).where(
            WebAgentAdmin.agent_id == agent_id,
            WebAgentAdmin.email == user_email.lower(),
        )
    )
    return row is not None


async def can_user_access(
    db: AsyncSession, user_email: str, agent_id: str,
) -> bool:
    if DEV_MODE or is_admin(user_email):
        return True
    if await is_agent_admin(db, user_email, agent_id):
        return True
    # Unprovisioned-user fallback: zero grant rows → only the default agent.
    # Prevents brand-new users from seeing every "no-rows = public" agent
    # before they've been triaged into a cohort.
    if not await _user_has_any_grants(db, user_email):
        return agent_id == default_agent_for_unassigned()
    hit = await db.scalar(
        select(WebAgentAccess.email).where(
            WebAgentAccess.agent_id == agent_id,
            WebAgentAccess.email == user_email.lower(),
        )
    )
    return hit is not None


async def list_accessible_agents(
    db: AsyncSession, user_email: str,
) -> list[AgentConfig]:
    if DEV_MODE or is_admin(user_email):
        return list_agents()
    grant_rows = (
        await db.execute(
            select(WebAgentAccess.agent_id, WebAgentAccess.email)
        )
    ).all()
    email = user_email.lower()
    user_grants = {a for a, e in grant_rows if e == email}
    admined = await _agent_admin_ids(db, user_email)

    # Unprovisioned-user fallback: zero grants and no L2 admin role → show
    # only the configured default agent.
    if not user_grants and not admined:
        default_id = default_agent_for_unassigned()
        return [a for a in list_agents() if a.id == default_id]

    return [
        a for a in list_agents()
        if a.id in admined or a.id in user_grants
    ]
