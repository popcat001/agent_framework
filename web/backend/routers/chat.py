"""WebSocket endpoint for streaming chat with the Finguru agent."""

import asyncio
import json
import logging
import threading
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agent.constants import USER_MEMORY_MAX_PER_USER
from agent.memory import PreloadedUserMemoryProvider
from agent_acl import can_user_access
from agent_registry import default_agent_id, get_agent_config
from agent_wrapper import CHAT_HISTORY_ENABLED, MULTI_AGENT_ENABLED, USER_MEMORY_ENABLED, StreamingAgentWrapper
from auth import get_user_from_ws_token
from database import async_session
from models import WebConversation, WebMessage, WebUserMemory

logger = logging.getLogger(__name__)
router = APIRouter()


def _resolve_or_default(agent_id: str | None) -> str | None:
    """Resolve ``agent_id`` via the registry, falling back to the default."""
    cfg = get_agent_config(agent_id)
    if cfg is not None:
        return cfg.id
    return agent_id or default_agent_id()


def _row_to_dict(r: WebUserMemory) -> dict:
    """Project a ``WebUserMemory`` row into the dict shape the provider expects."""
    return {
        "id": r.id,
        "content": r.content,
        "content_normalized": r.content_normalized,
        "category": r.category,
        "created_at": r.created_at,
        "updated_at": r.updated_at,
    }


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """Handle a WebSocket connection for streaming agent chat.

    Protocol:
        Client -> Server:
            {"type": "user_message", "conversation_id": "uuid|null", "content": "text"}
            {"type": "stop"}

        Server -> Client:
            {"type": "text_delta", "text": "..."}
            {"type": "tool_start", "name": "...", "input": {...}}
            {"type": "tool_result", "name": "...", "output": "..."}
            {"type": "tool_use_start", "name": "..."}
            {"type": "conversation_created", "conversation_id": "uuid", "title": "..."}
            {"type": "assistant_persisted", "conversation_id": "uuid", "message_id": "uuid"}
            {"type": "done"}
            {"type": "error", "message": "..."}
    """
    await websocket.accept()

    # Authenticate
    async with async_session() as db:
        try:
            user = await get_user_from_ws_token(websocket, db)
            await db.commit()
        except Exception:
            return

    # Lazy-init: agent is created on first message to avoid blocking the
    # connection. Rebuilt whenever a message targets a conversation bound to a
    # different agent_id.
    agent: StreamingAgentWrapper | None = None

    # Cache of conversation messages keyed by conversation_id
    conversation_messages: dict[str, list[dict]] = {}

    # The in-flight message handler runs as a background task so the receive
    # loop stays free to handle a `stop` frame or notice a disconnect and
    # signal cancellation. ``current_cancel`` is the threading.Event the agent
    # thread polls; ``current_task`` is the asyncio task running the handler.
    current_task: asyncio.Task | None = None
    current_cancel: threading.Event | None = None

    def _on_task_done(t: asyncio.Task):
        nonlocal current_task, current_cancel
        if current_task is t:
            current_task = None
            current_cancel = None
        if not t.cancelled():
            exc = t.exception()
            if exc is not None:
                logger.error("message handler task failed", exc_info=exc)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await _send(websocket, {"type": "error", "message": "Invalid JSON"})
                continue

            msg_type = data.get("type")

            if msg_type == "user_message":
                # The UI locks input while a turn streams, so a second
                # user_message mid-run is unexpected — reject it rather than
                # run two turns concurrently against the same agent/DB state.
                if current_task is not None and not current_task.done():
                    await _send(websocket, {
                        "type": "error",
                        "message": "Still processing the previous message",
                    })
                    continue
                # Resolve which agent should handle this message. Existing
                # conversations: read agent_id off the row. New conversation
                # (no conversation_id): take from client payload, falling back
                # to the registry default.
                target_agent_id = await _resolve_agent_id(user, data)
                if agent is None or agent.agent_id != target_agent_id:
                    agent = StreamingAgentWrapper(target_agent_id)
                current_cancel = threading.Event()
                current_task = asyncio.create_task(
                    _handle_user_message(
                        websocket, agent, user, data,
                        conversation_messages, current_cancel,
                    )
                )
                current_task.add_done_callback(_on_task_done)
            elif msg_type == "stop":
                # Signal the in-flight run to abort at its next checkpoint.
                if current_cancel is not None:
                    current_cancel.set()
            else:
                await _send(websocket, {"type": "error", "message": f"Unknown type: {msg_type}"})

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for user {user.email}")
    except Exception as e:
        logger.exception("WebSocket error")
        await _send(websocket, {"type": "error", "message": str(e)})
    finally:
        # On any exit (disconnect, error, stop) make sure a background run is
        # told to stop and is awaited, so we never leave an LLM/tool run going
        # unattended after the socket is gone.
        if current_cancel is not None:
            current_cancel.set()
        if current_task is not None and not current_task.done():
            try:
                await current_task
            except Exception:
                logger.exception("background message task failed during shutdown")


async def _resolve_agent_id(user, data: dict) -> str | None:
    """Resolve which agent_id should run this message.

    - Existing conversation: read agent_id off the conversation row.
    - New conversation: trust the client payload, falling back to the registry
      default. Unknown ids resolve to the default via ``get_agent_config``.
    """
    conv_id = data.get("conversation_id")
    if conv_id:
        # When history is disabled, conversations are in-memory only — there is
        # no DB row to look up, so resolve straight from the client payload.
        if not CHAT_HISTORY_ENABLED:
            return _resolve_or_default(data.get("agent_id"))
        try:
            conv_uuid = uuid.UUID(conv_id)
        except (ValueError, TypeError):
            return default_agent_id()
        async with async_session() as db:
            row = (
                await db.execute(
                    select(WebConversation.agent_id).where(
                        WebConversation.id == conv_uuid,
                        WebConversation.user_id == user.id,
                    )
                )
            ).scalar_one_or_none()
        return _resolve_or_default(row)

    return _resolve_or_default(data.get("agent_id"))


async def _handle_user_message(
    websocket: WebSocket,
    agent: StreamingAgentWrapper,
    user,
    data: dict,
    conversation_messages: dict[str, list[dict]],
    cancel_event: threading.Event | None = None,
):
    """Process a user message: persist, run agent, stream response.

    ``cancel_event`` is forwarded to the agent run; the receive loop sets it on
    a client ``stop`` frame or on disconnect so a long run aborts promptly.
    """
    content = data.get("content", "").strip()
    if not content:
        await _send(websocket, {"type": "error", "message": "Empty message"})
        return

    logger.info(f"[{user.email}] {content}")
    conversation_id = data.get("conversation_id")

    async with async_session() as db:
        # ---- Conversation setup ----
        # ``conversation`` is the DB row when history is enabled, or ``None``
        # when it is disabled (conversations live in-memory only for the life
        # of the socket). All DB reads/writes below are gated accordingly.
        conversation = None
        if CHAT_HISTORY_ENABLED:
            # Get or create conversation
            if conversation_id:
                conv_uuid = uuid.UUID(conversation_id)
                result = await db.execute(
                    select(WebConversation).where(
                        WebConversation.id == conv_uuid,
                        WebConversation.user_id == user.id,
                    )
                )
                conversation = result.scalar_one_or_none()
                if not conversation:
                    await _send(websocket, {"type": "error", "message": "Conversation not found"})
                    return
                # TODO(access-control): retroactive revocation is deferred — a user
                # revoked from this conversation's agent can still continue sending
                # messages here. See plans/plan_agent_access_control_db.md
                # §Out of scope.
            else:
                # Create new conversation with title from first message and bind
                # it to the agent the client picked (falling back to the default).
                # agent_id is NOT NULL — bail out if the registry can't supply one.
                title = content[:100] + ("..." if len(content) > 100 else "")
                resolved_agent = _resolve_or_default(data.get("agent_id"))
                if resolved_agent is None and MULTI_AGENT_ENABLED:
                    await _send(websocket, {
                        "type": "error",
                        "message": "No agents are registered on this server.",
                    })
                    return
                if resolved_agent is not None and not await can_user_access(db, user.email, resolved_agent):
                    await _send(websocket, {
                        "type": "error",
                        "code": "agent_access_denied",
                        "message": "You do not have access to this agent",
                    })
                    return
                conversation = WebConversation(
                    user_id=user.id,
                    title=title,
                    agent_id=resolved_agent,
                    source=data.get("source", "web"),
                )
                db.add(conversation)
                await db.flush()
                conversation_id = str(conversation.id)
                await _send(websocket, {
                    "type": "conversation_created",
                    "conversation_id": conversation_id,
                    "title": title,
                    "agent_id": conversation.agent_id,
                    "source": conversation.source,
                })
            conv_id_str = str(conversation.id)
        else:
            # History disabled — mint (or keep) an in-memory conversation ID.
            # Access is still enforced on the first turn of a new conversation.
            if not conversation_id:
                resolved_agent = _resolve_or_default(data.get("agent_id"))
                if resolved_agent is None and MULTI_AGENT_ENABLED:
                    await _send(websocket, {
                        "type": "error",
                        "message": "No agents are registered on this server.",
                    })
                    return
                if resolved_agent is not None and not await can_user_access(db, user.email, resolved_agent):
                    await _send(websocket, {
                        "type": "error",
                        "code": "agent_access_denied",
                        "message": "You do not have access to this agent",
                    })
                    return
                conversation_id = str(uuid.uuid4())
                await _send(websocket, {
                    "type": "conversation_created",
                    "conversation_id": conversation_id,
                    "title": content[:100] + ("..." if len(content) > 100 else ""),
                    "agent_id": agent.agent_id,
                    "source": data.get("source", "web"),
                })
            conv_id_str = conversation_id

        # ---- Load / initialise message history ----
        if conv_id_str not in conversation_messages:
            if CHAT_HISTORY_ENABLED:
                conversation_messages[conv_id_str] = await _load_messages_from_db(db, conversation.id)
            else:
                conversation_messages[conv_id_str] = []

        messages = conversation_messages[conv_id_str]

        # Add user message
        messages.append({"role": "user", "content": content})

        # Persist user message + bump conversation timestamp (history only)
        if CHAT_HISTORY_ENABLED:
            db.add(WebMessage(
                conversation_id=conversation.id,
                role="user",
                content={"text": content},
            ))
            conversation.updated_at = datetime.now(timezone.utc)
            await db.commit()

        # Load user memory snapshot for this turn. One DB round-trip, ordered
        # by updated_at DESC so the provider's internal list matches the
        # ranking shown to the agent. Gated by ``USER_MEMORY_ENABLED``: when
        # the flag is off we skip the load entirely — no DB round-trip, no
        # provider object — and pass ``None`` into the agent.
        if USER_MEMORY_ENABLED:
            mem_rows = (
                await db.execute(
                    select(WebUserMemory)
                    .where(WebUserMemory.user_id == user.id)
                    .order_by(WebUserMemory.updated_at.desc())
                )
            ).scalars().all()
            memory_provider = PreloadedUserMemoryProvider(
                user.id,
                [_row_to_dict(r) for r in mem_rows],
            )
        else:
            memory_provider = None

        # Stream agent response
        collected_text = []
        collected_charts = []
        execution_log = []
        _last_event_type: list[str] = [""]  # mutable to allow closure mutation
        # Buffer the agent's terminal `done` event. We delay forwarding it
        # until AFTER the assistant message is persisted and the DB id has
        # been sent to the client. The frontend gates "send next message" and
        # "switch conversation" on isStreaming (driven by `done`), so holding
        # `done` keeps the client locked until `assistant_persisted` has
        # attached its DB id to the right bubble — closing the race where a
        # second user turn would steal the id.
        _pending_done: list[dict] = []

        async def send_event(event: dict):
            event_type = event.get("type", "")
            if event_type == "text_delta":
                # If text resumes after a tool result, insert a newline separator
                # so consecutive text blocks don't run together
                if _last_event_type[0] == "tool_result" and collected_text:
                    collected_text.append("\n\n")
                collected_text.append(event.get("text", ""))
            if event_type in ("tool_start", "tool_result"):
                log_entry = {
                    "type": event["type"],
                    "name": event.get("name"),
                    "tool_use_id": event.get("tool_use_id"),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                if event["type"] == "tool_start":
                    log_entry["input"] = event.get("input")
                elif event["type"] == "tool_result":
                    log_entry["output"] = event.get("output", "")
                    if event.get("chart_url"):
                        log_entry["chart_url"] = event["chart_url"]
                        collected_charts.append({"name": event.get("name"), "chart_url": event["chart_url"]})
                execution_log.append(log_entry)
            _last_event_type[0] = event_type
            if event_type == "done":
                _pending_done.append(event)
                return
            # If the send fails the client is gone — cancel the run so we don't
            # keep generating into a dead socket.
            if not await _send(websocket, {**event, "conversation_id": conv_id_str}):
                if cancel_event is not None:
                    cancel_event.set()

        try:
            await agent.run_streaming(
                messages,
                send_event,
                user_memory_provider=memory_provider,
                cancel_event=cancel_event,
            )
        except Exception as e:
            logger.exception("Agent run failed")
            await _send(websocket, {"type": "error", "message": f"Agent error: {e}"})
            # Release the client-side streaming lock even on failure — without
            # this the UI would stay disabled because `done` is now buffered.
            for ev in _pending_done:
                await _send(websocket, {**ev, "conversation_id": conv_id_str})
            return

        # Flush pending memory ops. Runs BEFORE the assistant message commit
        # so that a downstream assistant-persist failure does not lose memory
        # the agent already told the user was saved.
        # Order: evict → deletes → updates → per-row savepoint inserts.
        # Skipped when memory is disabled — ``memory_provider`` is ``None`` in
        # that case, and there is nothing to flush.
        if memory_provider is not None:
            await _flush_user_memory(db, user.id, memory_provider)

        # Persist assistant response (store the raw content blocks from
        # messages). Guard on the last message actually being an assistant
        # turn: a cancelled run (stop/disconnect) can raise AgentCancelled
        # before Agent.run appends the assistant message, leaving messages[-1]
        # as the user's own turn — persisting that as role="assistant" would
        # duplicate the user's question as an assistant bubble on reload.
        # Skipped entirely when history is disabled — there is no DB row, so no
        # ``assistant_persisted`` is sent and feedback is unavailable for the turn.
        if CHAT_HISTORY_ENABLED:
            last_msg = messages[-1] if messages else None
            assistant_content = (
                last_msg.get("content")
                if last_msg and last_msg.get("role") == "assistant"
                else None
            )
            if assistant_content:
                # Serialize content blocks for storage
                serialized = _serialize_content(assistant_content)
                assistant_msg = WebMessage(
                    conversation_id=conversation.id,
                    role="assistant",
                    content={
                        "blocks": serialized,
                        "text": "".join(collected_text),
                        **({"charts": collected_charts} if collected_charts else {}),
                        **({"execution_log": execution_log} if execution_log else {}),
                    },
                )
                db.add(assistant_msg)
                await db.commit()
                # Send the persisted message id so the client can wire feedback
                # (thumbs up/down + comment) to a real DB row, not the synthetic
                # client-side counter id. MUST be sent before the buffered `done`
                # event below — `done` releases the frontend's streaming lock, and
                # only after the id has been attached is it safe to let the user
                # send another message or switch conversations.
                await _send(websocket, {
                    "type": "assistant_persisted",
                    "conversation_id": conv_id_str,
                    "message_id": str(assistant_msg.id),
                })

        # Flush the buffered `done` event(s) last. Sent regardless of whether
        # the assistant message was persisted (empty content path), so the
        # client always exits its streaming state.
        for ev in _pending_done:
            await _send(websocket, {**ev, "conversation_id": conv_id_str})


async def _flush_user_memory(
    db: AsyncSession,
    user_id: uuid.UUID,
    provider: PreloadedUserMemoryProvider,
) -> None:
    """Apply the provider's pending writes/updates/deletes to the DB.

    Flush order is load-bearing:

    1. **Evict** — clamp the user's total rows at ``USER_MEMORY_MAX_PER_USER``
       before inserting. Running eviction first (rather than after) prevents
       a post-insert cleanup from ever deleting rows the agent just told the
       user were saved. PostgreSQL does not allow ``ORDER BY`` / ``LIMIT``
       directly on DELETE, so it uses ``DELETE … WHERE id IN (SELECT … OFFSET
       N)`` — keeps the top N by ``updated_at DESC`` and deletes the rest.
    2. **Deletes** — straight DELETEs from ``pending_deletes``. Not savepoint-
       wrapped: the schema has no FK into ``web_user_memory`` today and
       0-rowcount deletes are benign.
    3. **Updates** — one UPDATE per distinct id in ``pending_updates`` (the
       provider's dict-of-id coalesces dup-spam to one entry). Not savepoint-
       wrapped: 0-rowcount updates on a concurrent delete are benign.
    4. **Inserts** — each wrapped in ``db.begin_nested()`` (SAVEPOINT) so a
       unique-constraint collision from a concurrent tab only drops that one
       row. Without the savepoint, any IntegrityError would roll back the
       whole transaction and discard every legitimate write in this turn.
    """
    # Step 0: per-user cap eviction.
    evict_limit = USER_MEMORY_MAX_PER_USER - len(provider.pending_writes)
    if evict_limit < 0:
        # The inserts alone would blow the cap. Surface rather than silently
        # evict rows we just told the user we saved.
        raise ValueError(
            f"pending_writes ({len(provider.pending_writes)}) exceeds "
            f"USER_MEMORY_MAX_PER_USER ({USER_MEMORY_MAX_PER_USER}) — "
            "raise the per-turn cap or the per-user cap."
        )
    if evict_limit > 0:
        keep_subq = (
            select(WebUserMemory.id)
            .where(WebUserMemory.user_id == user_id)
            .order_by(WebUserMemory.updated_at.desc())
            .offset(evict_limit)
        )
        result = await db.execute(
            delete(WebUserMemory).where(WebUserMemory.id.in_(keep_subq))
        )
        if getattr(result, "rowcount", 0):
            logger.info(
                "user_memory.evict user=%s count=%d",
                user_id, result.rowcount,
            )

    # Step 1: deletes.
    for del_id in provider.pending_deletes:
        await db.execute(
            delete(WebUserMemory).where(WebUserMemory.id == del_id)
        )

    # Step 2: updates (duplicate re-saves bump updated_at so ranking works).
    for mem_id, ts in provider.pending_updates.items():
        await db.execute(
            update(WebUserMemory)
            .where(WebUserMemory.id == mem_id)
            .values(updated_at=ts)
        )

    # Step 3: inserts — per-row savepoint.
    for w in provider.pending_writes:
        try:
            async with db.begin_nested():
                db.add(WebUserMemory(
                    id=w["id"],
                    user_id=user_id,
                    content=w["content"],
                    content_normalized=w["content_normalized"],
                    category=w["category"],
                    created_at=w["created_at"],
                    updated_at=w["updated_at"],
                ))
            # begin_nested() flushes on __aexit__; IntegrityError surfaces here.
        except IntegrityError:
            # Another concurrent session saved the same normalized content
            # first. The user's content is already in the table — no-op.
            logger.info(
                "user_memory.insert_skip_duplicate user=%s id=%s",
                user_id, w["id"],
            )

    await db.commit()


async def _load_messages_from_db(db: AsyncSession, conversation_id: uuid.UUID) -> list[dict]:
    """Load conversation messages from DB into Anthropic message format."""
    result = await db.execute(
        select(WebMessage)
        .where(WebMessage.conversation_id == conversation_id)
        .order_by(WebMessage.created_at)
    )
    db_messages = result.scalars().all()

    messages = []
    for msg in db_messages:
        if msg.role == "user":
            messages.append({"role": "user", "content": msg.content.get("text", "")})
        elif msg.role == "assistant":
            # For assistant messages, use the text content for replay
            text = msg.content.get("text", "")
            if text:
                messages.append({"role": "assistant", "content": text})
    return messages


def _serialize_content(content) -> list:
    """Serialize Anthropic content blocks to JSON-safe format."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        result = []
        for block in content:
            if hasattr(block, "text"):
                result.append({"type": "text", "text": block.text})
            elif hasattr(block, "type") and block.type == "tool_use":
                result.append({
                    "type": "tool_use",
                    "name": block.name,
                    "input": block.input if isinstance(block.input, dict) else str(block.input),
                })
            else:
                result.append({"type": "unknown", "data": str(block)})
        return result
    return [{"type": "text", "text": str(content)}]


async def _send(websocket: WebSocket, data: dict) -> bool:
    """Send a JSON message to the WebSocket client.

    Returns ``True`` on success, ``False`` if the send failed (typically a
    disconnected client). Failures are logged rather than silently swallowed
    so callers streaming a long run can react (e.g. cancel the run).
    """
    try:
        await websocket.send_text(json.dumps(data, default=str))
        return True
    except Exception:
        logger.debug("WebSocket send failed (client likely disconnected)", exc_info=True)
        return False
