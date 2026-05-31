"""Admin endpoints for managing per-agent access.

Two tiers (matches `agent_acl.py`):
  - **L1 super admin** — listed in `ADMIN_EMAILS` env var. Sees and manages
    every agent.
  - **L2 agent admin** — row in `web_agent_admins`. Sees and manages only
    the agents they are listed for.

The frontend gates the "Manage access" sidebar entry on `GET /api/admin/me`,
so a non-admin should never reach these endpoints; nevertheless every route
re-checks the user's tier server-side.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
import re

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_acl import ADMIN_EMAILS, _agent_admin_ids, is_admin
from agent_registry import get_agent_config, list_agents
from auth import get_current_user
from config import DEV_MODE
from database import get_db
from models import WebAgentAccess, WebAgentAdmin, WebUser

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AdminAgentInfo(BaseModel):
    id: str
    name: str


class AdminMe(BaseModel):
    """Returned by GET /api/admin/me — drives sidebar gating."""

    is_admin: bool          # True if L1 or L2 (any agent)
    is_super_admin: bool    # True iff L1
    managed_agents: list[AdminAgentInfo]  # full list (L1) or scoped (L2)
    # L1 super admins (from ADMIN_EMAILS env). Exposed so the Manage-access
    # UI can fall back to showing them in the "All agents" view when no DB
    # user has explicit grants to every agent.
    super_admins: list[str]


class AdminGrantRow(BaseModel):
    agent_id: str
    email: str
    created_at: datetime


_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class AdminAgentAdminRow(BaseModel):
    """One row of ``web_agent_admins`` — i.e. an L2 agent admin grant."""

    agent_id: str
    email: str
    created_at: datetime


class AddAgentAdminRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=64)
    email: str = Field(..., min_length=3, max_length=255)

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("invalid email format")
        return v


class AddGrantRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=64)
    email: str = Field(..., min_length=3, max_length=255)

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("invalid email format")
        return v


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_registered_agent(agent_id: str) -> bool:
    """True iff ``agent_id`` matches a registered AND enabled agent id.

    Matches ``list_agents()`` (which filters to enabled) — so admin grants
    cannot target a disabled agent even though ``get_agent_config`` would
    still resolve it for legacy conversations.
    """
    cfg = get_agent_config(agent_id)
    if cfg is None or cfg.id != agent_id:
        return False
    return any(a.id == agent_id for a in list_agents())


async def _managed_agent_ids(db: AsyncSession, user: WebUser) -> Optional[set[str]]:
    """Return the set of agent_ids the caller may manage.

    None  → caller is L1 (or DEV_MODE), can manage everything (no filter).
    set() → caller has no admin role at all; endpoints should 403.
    {...} → L2 admin scope.
    """
    if DEV_MODE or is_admin(user.email):
        return None
    return await _agent_admin_ids(db, user.email)


def _require_admin(scope: Optional[set[str]]):
    if scope is not None and not scope:
        raise HTTPException(status_code=403, detail="Not an admin")


def _require_super_admin(user: WebUser):
    """L1-only gate. Used by the agent-admin management endpoints since
    promoting/demoting L2 admins is a super-admin power."""
    if DEV_MODE or is_admin(user.email):
        return
    raise HTTPException(status_code=403, detail="Super admin only")


def _require_agent_in_scope(scope: Optional[set[str]], agent_id: str):
    if scope is None:
        return  # L1
    if agent_id not in scope:
        raise HTTPException(
            status_code=403,
            detail=f"You don't admin agent '{agent_id}'",
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/me", response_model=AdminMe)
async def admin_me(
    user: WebUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Tells the frontend whether to render the Manage access entry and which
    agents to show. Returns `is_admin=False` for everyone else."""
    scope = await _managed_agent_ids(db, user)
    all_agents = list_agents()
    super_admins = sorted(ADMIN_EMAILS)
    if scope is None:
        managed = [AdminAgentInfo(id=a.id, name=a.name) for a in all_agents]
        return AdminMe(
            is_admin=True,
            is_super_admin=True,
            managed_agents=managed,
            super_admins=super_admins,
        )
    if not scope:
        return AdminMe(
            is_admin=False,
            is_super_admin=False,
            managed_agents=[],
            super_admins=[],
        )
    managed = [
        AdminAgentInfo(id=a.id, name=a.name) for a in all_agents if a.id in scope
    ]
    return AdminMe(
        is_admin=True,
        is_super_admin=False,
        managed_agents=managed,
        super_admins=super_admins,
    )


@router.get("/access", response_model=list[AdminGrantRow])
async def list_access_grants(
    agent_id: Optional[str] = None,
    user: WebUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List grant rows from `web_agent_access`, filtered by admin scope.
    Optional `agent_id` query narrows further."""
    scope = await _managed_agent_ids(db, user)
    _require_admin(scope)

    stmt = select(
        WebAgentAccess.agent_id, WebAgentAccess.email, WebAgentAccess.created_at,
    ).order_by(WebAgentAccess.agent_id, WebAgentAccess.email)

    if agent_id:
        _require_agent_in_scope(scope, agent_id)
        stmt = stmt.where(WebAgentAccess.agent_id == agent_id)
    elif scope is not None:  # L2: limit to their agents
        stmt = stmt.where(WebAgentAccess.agent_id.in_(scope))

    rows = (await db.execute(stmt)).all()
    return [
        AdminGrantRow(agent_id=a, email=e, created_at=c) for a, e, c in rows
    ]


@router.post("/access", response_model=AdminGrantRow, status_code=201)
async def add_access_grant(
    body: AddGrantRequest,
    user: WebUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scope = await _managed_agent_ids(db, user)
    _require_admin(scope)
    _require_agent_in_scope(scope, body.agent_id)

    if not _is_registered_agent(body.agent_id):
        raise HTTPException(status_code=400, detail=f"Unknown agent_id: {body.agent_id}")

    email = body.email.lower()

    # Idempotent: if the row already exists, return it as-is rather than 409.
    existing = (
        await db.execute(
            select(WebAgentAccess).where(
                WebAgentAccess.agent_id == body.agent_id,
                WebAgentAccess.email == email,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return AdminGrantRow(
            agent_id=existing.agent_id,
            email=existing.email,
            created_at=existing.created_at,
        )

    row = WebAgentAccess(agent_id=body.agent_id, email=email)
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return AdminGrantRow(
        agent_id=row.agent_id, email=row.email, created_at=row.created_at,
    )


@router.delete("/access", status_code=204)
async def remove_access_grant(
    agent_id: str,
    email: str,
    user: WebUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scope = await _managed_agent_ids(db, user)
    _require_admin(scope)
    _require_agent_in_scope(scope, agent_id)

    res = (
        await db.execute(
            select(WebAgentAccess).where(
                WebAgentAccess.agent_id == agent_id,
                WebAgentAccess.email == email.lower(),
            )
        )
    ).scalar_one_or_none()
    if res is None:
        raise HTTPException(status_code=404, detail="Grant not found")
    await db.delete(res)
    return None


@router.get("/users")
async def search_users(
    q: str = "",
    limit: int = 20,
    user: WebUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Lookup helper for the add-user modal: returns up to `limit` matches
    from `web_users` by email or display_name substring. Admin-only."""
    scope = await _managed_agent_ids(db, user)
    _require_admin(scope)
    limit = max(1, min(limit, 50))
    q = (q or "").strip().lower()
    # web_users.email is NOT unique (only azure_ad_oid is) — the same person
    # can have multiple rows if they've signed in via different OIDs (e.g. mock
    # DEV_MODE OID + real EasyAuth OID). Collapse on lower(email) so the
    # add-user picker shows one entry per email; pick the most-recent
    # display_name (MAX(created_at) row wins via DISTINCT ON).
    email_lower = func.lower(WebUser.email).label("email_lower")
    stmt = (
        select(WebUser.email, WebUser.display_name)
        .distinct(email_lower)
        .order_by(email_lower, WebUser.created_at.desc())
        .limit(limit)
    )
    if q:
        ilike = f"%{q}%"
        stmt = (
            select(WebUser.email, WebUser.display_name)
            .where(
                (WebUser.email.ilike(ilike)) | (WebUser.display_name.ilike(ilike))
            )
            .distinct(email_lower)
            .order_by(email_lower, WebUser.created_at.desc())
            .limit(limit)
        )
    rows = (await db.execute(stmt)).all()
    return [{"email": e, "display_name": d} for e, d in rows]


# ---------------------------------------------------------------------------
# L2 agent-admin management (super-admin only)
# ---------------------------------------------------------------------------


@router.get("/agent-admins", response_model=list[AdminAgentAdminRow])
async def list_agent_admins(
    agent_id: Optional[str] = None,
    user: WebUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List rows from ``web_agent_admins``. L1-only — L2 admins shouldn't be
    able to enumerate or modify their peers."""
    _require_super_admin(user)

    stmt = select(
        WebAgentAdmin.agent_id, WebAgentAdmin.email, WebAgentAdmin.created_at,
    ).order_by(WebAgentAdmin.agent_id, WebAgentAdmin.email)
    if agent_id:
        stmt = stmt.where(WebAgentAdmin.agent_id == agent_id)
    rows = (await db.execute(stmt)).all()
    return [
        AdminAgentAdminRow(agent_id=a, email=e, created_at=c) for a, e, c in rows
    ]


@router.post("/agent-admins", response_model=AdminAgentAdminRow, status_code=201)
async def add_agent_admin(
    body: AddAgentAdminRequest,
    user: WebUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_super_admin(user)

    if not _is_registered_agent(body.agent_id):
        raise HTTPException(status_code=400, detail=f"Unknown agent_id: {body.agent_id}")

    email = body.email.lower()

    existing = (
        await db.execute(
            select(WebAgentAdmin).where(
                WebAgentAdmin.agent_id == body.agent_id,
                WebAgentAdmin.email == email,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return AdminAgentAdminRow(
            agent_id=existing.agent_id,
            email=existing.email,
            created_at=existing.created_at,
        )

    row = WebAgentAdmin(agent_id=body.agent_id, email=email)
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return AdminAgentAdminRow(
        agent_id=row.agent_id, email=row.email, created_at=row.created_at,
    )


@router.delete("/agent-admins", status_code=204)
async def remove_agent_admin(
    agent_id: str,
    email: str,
    user: WebUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_super_admin(user)

    res = (
        await db.execute(
            select(WebAgentAdmin).where(
                WebAgentAdmin.agent_id == agent_id,
                WebAgentAdmin.email == email.lower(),
            )
        )
    ).scalar_one_or_none()
    if res is None:
        raise HTTPException(status_code=404, detail="Admin row not found")
    await db.delete(res)
    return None
