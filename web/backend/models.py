"""SQLAlchemy ORM models for web layer tables."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, LargeBinary, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class WebUser(Base):
    __tablename__ = "web_users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    azure_ad_oid: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    conversations: Mapped[list["WebConversation"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class WebConversation(Base):
    __tablename__ = "web_conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("web_users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(255), default="New conversation")
    # Conversations are bound to an agent at creation and never switched.
    # ``init_db()`` adds the column nullable on existing deployments, backfills
    # NULLs with the registry default, then sets NOT NULL. New rows must
    # always be inserted with a resolved agent_id (the chat router calls
    # ``get_agent_config`` and persists ``cfg.id``).
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Origin of the conversation: 'web' | 'slack' | 'teams'. Nullable for
    # rows created before this column was added; backfilled to 'web' on boot.
    source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user: Mapped["WebUser"] = relationship(back_populates="conversations")
    messages: Mapped[list["WebMessage"]] = relationship(back_populates="conversation", cascade="all, delete-orphan", order_by="WebMessage.created_at")

    __table_args__ = (
        Index("idx_conversations_user", "user_id", "updated_at"),
    )


class WebMessage(Base):
    __tablename__ = "web_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("web_conversations.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    # User feedback on assistant messages: 'up' / 'down' / NULL. NULL on
    # user-role rows and on assistant rows the user hasn't rated.
    # `feedback_comment` is an optional free-text note the user can attach
    # to either rating.
    feedback: Mapped[str | None] = mapped_column(String(10), nullable=True)
    feedback_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    conversation: Mapped["WebConversation"] = relationship(back_populates="messages")

    __table_args__ = (
        Index("idx_messages_conversation", "conversation_id", "created_at"),
    )


class WebChart(Base):
    """Stores chart data (HTML or PNG) in the database, served via /files/{filename}."""
    __tablename__ = "web_charts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("idx_charts_filename", "filename"),
    )


class WebUserMemory(Base):
    """Per-user durable memory (preferences, facts, feedback).

    One row per fact. ``content_normalized`` is the lowercase +
    whitespace-collapsed form of ``content`` and is covered by a unique
    constraint with ``user_id`` so cross-turn / cross-session duplicate saves
    are rejected at the DB layer (the in-process provider dedupes within a
    turn; this catches races across concurrent tabs).
    """

    __tablename__ = "web_user_memory"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("web_users.id", ondelete="CASCADE"),
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # lowercase + whitespace-collapsed form of ``content`` — the dedup key.
    content_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    # 'preference' | 'fact' | 'feedback' (nullable for legacy rows, but the
    # write-path schema restricts new inserts to the three-value enum).
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("idx_user_memory_user_updated", "user_id", "updated_at"),
        UniqueConstraint(
            "user_id", "content_normalized", name="uq_user_memory_dedup",
        ),
    )


class WebAgentAccess(Base):
    """Per-agent access grants. Every agent requires an explicit grant row
    (or L1/L2 admin). Users with zero grant rows see only the configured
    default agent; see ``agent_acl.can_user_access`` for full resolution."""

    __tablename__ = "web_agent_access"

    agent_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), primary_key=True)
    # server_default so raw psql INSERTs (admin workflow) don't need to
    # supply created_at — keeps ORM and ad-hoc SQL paths symmetric.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint("email = lower(email)", name="ck_agent_access_email_lower"),
    )


class WebAgentAdmin(Base):
    """L2 admin: this email manages grants for ``agent_id`` and implicitly
    has access to it. L1 super admins live in the ``ADMIN_EMAILS`` env var
    (see ``agent_acl.py``); L2 admins live in the DB so they can be granted
    and revoked at runtime without a backend restart.
    """

    __tablename__ = "web_agent_admins"

    agent_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint("email = lower(email)", name="ck_agent_admins_email_lower"),
    )
