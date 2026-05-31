"""REST endpoints for conversation history CRUD.

Access control: only ``POST`` is gated by ``can_user_access`` (v1 scope —
see ``plans/plan_agent_access_control_db.md``). List / detail / PATCH /
DELETE remain owner-only; retroactive-revocation gates on those endpoints
are deferred.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agent_acl import can_user_access
from agent_registry import default_agent_id, get_agent_config
from agent_wrapper import CHAT_HISTORY_ENABLED
from auth import get_current_user
from database import get_db
from models import WebConversation, WebMessage, WebUser

router = APIRouter()


class ConversationOut(BaseModel):
    id: str
    title: str
    agent_id: str | None = None
    source: str | None = None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: str
    role: str
    content: dict
    created_at: str
    feedback: str | None = None

    model_config = {"from_attributes": True}


class FeedbackRequest(BaseModel):
    rating: str | None  # 'up' | 'down' | None to clear


class ConversationDetail(BaseModel):
    id: str
    title: str
    agent_id: str | None = None
    source: str | None = None
    created_at: str
    updated_at: str
    messages: list[MessageOut]


class RenameRequest(BaseModel):
    title: str


class CreateConversationRequest(BaseModel):
    agent_id: str | None = None
    source: str | None = None


def _conversation_out(c: WebConversation) -> ConversationOut:
    return ConversationOut(
        id=str(c.id),
        title=c.title,
        agent_id=c.agent_id,
        source=c.source,
        created_at=c.created_at.isoformat(),
        updated_at=c.updated_at.isoformat(),
    )


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    user: WebUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
):
    """List the user's conversations, newest first."""
    if not CHAT_HISTORY_ENABLED:
        return []
    result = await db.execute(
        select(WebConversation)
        .where(WebConversation.user_id == user.id)
        .order_by(WebConversation.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [_conversation_out(c) for c in result.scalars().all()]


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID,
    user: WebUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a conversation with all its messages."""
    if not CHAT_HISTORY_ENABLED:
        raise HTTPException(status_code=404, detail="Conversation not found")
    result = await db.execute(
        select(WebConversation)
        .where(WebConversation.id == conversation_id, WebConversation.user_id == user.id)
        .options(selectinload(WebConversation.messages))
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return ConversationDetail(
        id=str(conversation.id),
        title=conversation.title,
        agent_id=conversation.agent_id,
        source=conversation.source,
        created_at=conversation.created_at.isoformat(),
        updated_at=conversation.updated_at.isoformat(),
        messages=[
            MessageOut(
                id=str(m.id),
                role=m.role,
                content=m.content,
                created_at=m.created_at.isoformat(),
                feedback=m.feedback,
            )
            for m in conversation.messages
        ],
    )


@router.post("", response_model=ConversationOut)
async def create_conversation(
    body: CreateConversationRequest | None = None,
    user: WebUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new empty conversation bound to ``agent_id``.

    Validates the requested agent against the registry. Falls back to the
    registry default when not specified. Returns 400 if an agent_id is given
    but does not match a registered agent. Returns 501 when
    ``CHAT_HISTORY_ENABLED=false``.
    """
    if not CHAT_HISTORY_ENABLED:
        raise HTTPException(status_code=501, detail="Chat history is disabled")
    requested = body.agent_id if body else None
    cfg = get_agent_config(requested)
    if requested and (cfg is None or cfg.id != requested):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown agent_id: {requested!r}",
        )
    resolved = (cfg.id if cfg else None) or default_agent_id()
    if resolved is None:
        raise HTTPException(
            status_code=500,
            detail="No agents are registered on this server.",
        )
    if not await can_user_access(db, user.email, resolved):
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this agent",
        )
    conversation = WebConversation(
        user_id=user.id,
        agent_id=resolved,
        source=(body.source if body and body.source else "web"),
    )
    db.add(conversation)
    await db.flush()
    return _conversation_out(conversation)


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def rename_conversation(
    conversation_id: uuid.UUID,
    body: RenameRequest,
    user: WebUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rename a conversation."""
    if not CHAT_HISTORY_ENABLED:
        raise HTTPException(status_code=404, detail="Conversation not found")
    result = await db.execute(
        select(WebConversation).where(
            WebConversation.id == conversation_id, WebConversation.user_id == user.id
        )
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conversation.title = body.title
    await db.flush()
    return _conversation_out(conversation)


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: uuid.UUID,
    user: WebUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a conversation and all its messages."""
    if not CHAT_HISTORY_ENABLED:
        raise HTTPException(status_code=404, detail="Conversation not found")
    result = await db.execute(
        select(WebConversation).where(
            WebConversation.id == conversation_id, WebConversation.user_id == user.id
        )
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    await db.delete(conversation)
    return {"status": "deleted"}


@router.patch("/{conversation_id}/messages/{message_id}/feedback")
async def set_message_feedback(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    body: FeedbackRequest,
    user: WebUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set or clear the feedback rating on an assistant message.

    Owner-only: the message must belong to a conversation owned by ``user``.
    ``rating`` must be 'up', 'down', or None (to clear).
    """
    if not CHAT_HISTORY_ENABLED:
        raise HTTPException(status_code=404, detail="Message not found")
    if body.rating not in ("up", "down", None):
        raise HTTPException(status_code=400, detail="rating must be 'up', 'down', or null")

    result = await db.execute(
        select(WebMessage)
        .join(WebConversation, WebMessage.conversation_id == WebConversation.id)
        .where(
            WebMessage.id == message_id,
            WebMessage.conversation_id == conversation_id,
            WebConversation.user_id == user.id,
        )
    )
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    if msg.role != "assistant":
        raise HTTPException(status_code=400, detail="Feedback only applies to assistant messages")

    msg.feedback = body.rating
    await db.flush()
    return {"id": str(msg.id), "feedback": msg.feedback}
