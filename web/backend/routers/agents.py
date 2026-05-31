"""REST endpoint listing the agents available to the user."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from agent_acl import list_accessible_agents
from auth import get_current_user
from database import get_db
from models import WebUser

router = APIRouter()


@router.get("")
async def get_agents(
    user: WebUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return agents accessible to the current user (default first)."""
    accessible = await list_accessible_agents(db, user.email)
    return [a.to_public_dict() for a in accessible]
