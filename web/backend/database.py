"""Async database session management using SQLAlchemy."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import DATABASE_URL

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=300,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:
    """FastAPI dependency that yields an async DB session."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def _column_exists(conn, table: str, column: str) -> bool:
    """True if `table.column` exists. Uses information_schema (a plain SELECT),
    so it works even when the connecting user doesn't own the table — letting
    us skip ALTERs that would otherwise raise InsufficientPrivilege on a DB
    where the column is already present."""
    from sqlalchemy import text
    result = await conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c LIMIT 1"
        ),
        {"t": table, "c": column},
    )
    return result.first() is not None


async def init_db():
    """Create all tables on startup. Logs a warning if the DB is unreachable."""
    import logging
    logger = logging.getLogger(__name__)
    try:
        from models import Base

        # Import project-level models so their tables register with Base.metadata
        from config import PROJECT_ROOT
        project_models = PROJECT_ROOT / "web" / "backend" / "models_project.py"
        if project_models.exists():
            import importlib, sys
            project_backend = str(PROJECT_ROOT / "web" / "backend")
            if project_backend not in sys.path:
                sys.path.insert(0, project_backend)
            try:
                importlib.import_module("models_project")
                logger.info("Loaded project-level models from %s", project_models)
            except Exception as e:
                logger.warning("Failed to import project models: %s", e)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created/verified.")

        # Add columns introduced after the initial schema. create_all does not
        # ALTER existing tables on its own. Sequence:
        #   1. ADD COLUMN nullable (idempotent on fresh DBs too — column
        #      survives even though create_all already declares it NOT NULL).
        #   2. Backfill any NULL rows to the registry's default agent id.
        #   3. ALTER COLUMN ... SET NOT NULL so future inserts must specify
        #      an agent_id explicitly.
        try:
            from sqlalchemy import text
            from agent_registry import default_agent_id
            default_id = default_agent_id()
            async with engine.begin() as conn:
                # Skip the migration entirely when the column already exists —
                # ALTER requires table ownership (even with IF NOT EXISTS), which
                # the runtime DB user may lack. The existence check is a plain
                # SELECT, so it works regardless of ownership.
                if not await _column_exists(conn, "web_conversations", "agent_id"):
                    await conn.execute(text(
                        "ALTER TABLE web_conversations "
                        "ADD COLUMN IF NOT EXISTS agent_id VARCHAR(64)"
                    ))
                    if default_id:
                        # default_id comes from a YAML `id:` field (also used as a
                        # directory name), but DDL cannot bind parameters — guard
                        # against anything weird before splicing into ALTER TABLE.
                        import re
                        if not re.fullmatch(r"[A-Za-z0-9_-]+", default_id):
                            raise ValueError(
                                f"Refusing to set unsafe agent_id default: {default_id!r}"
                            )
                        result = await conn.execute(
                            text(
                                "UPDATE web_conversations SET agent_id = :aid "
                                "WHERE agent_id IS NULL"
                            ),
                            {"aid": default_id},
                        )
                        if getattr(result, "rowcount", 0):
                            logger.info(
                                "Backfilled %d conversations with agent_id=%s",
                                result.rowcount, default_id,
                            )
                        # Set a column-level DEFAULT so an old deployment running
                        # against the migrated schema (no `agent_id` in its INSERT
                        # statement) still gets a valid value instead of NULL —
                        # without this, rolling deploys and rollbacks would 500
                        # on conversation creation.
                        await conn.execute(text(
                            "ALTER TABLE web_conversations "
                            f"ALTER COLUMN agent_id SET DEFAULT '{default_id}'"
                        ))
                        await conn.execute(text(
                            "ALTER TABLE web_conversations "
                            "ALTER COLUMN agent_id SET NOT NULL"
                        ))
                    else:
                        # No agents registered (single-agent / framework-only
                        # deployment). Leave the column nullable so the existing
                        # behavior keeps working.
                        logger.info(
                            "No agents registered; leaving agent_id nullable."
                        )
        except Exception as e:
            logger.warning("Failed to ensure agent_id column: %s", e)

        # Add source column. Nullable, no default — writers must set it
        # explicitly so a missing value surfaces as NULL.
        try:
            from sqlalchemy import text
            async with engine.begin() as conn:
                if not await _column_exists(conn, "web_conversations", "source"):
                    await conn.execute(text(
                        "ALTER TABLE web_conversations "
                        "ADD COLUMN IF NOT EXISTS source VARCHAR(20)"
                    ))
        except Exception as e:
            logger.warning("Failed to ensure source column: %s", e)

        # Add per-message feedback columns. Nullable; feedback is
        # 'up' / 'down' / NULL, feedback_comment is an optional free-text
        # note the user can attach to either rating. Only assistant rows the
        # user has rated will have values.
        try:
            from sqlalchemy import text
            async with engine.begin() as conn:
                if not await _column_exists(conn, "web_messages", "feedback"):
                    await conn.execute(text(
                        "ALTER TABLE web_messages "
                        "ADD COLUMN IF NOT EXISTS feedback VARCHAR(10)"
                    ))
                if not await _column_exists(conn, "web_messages", "feedback_comment"):
                    await conn.execute(text(
                        "ALTER TABLE web_messages "
                        "ADD COLUMN IF NOT EXISTS feedback_comment TEXT"
                    ))
        except Exception as e:
            logger.warning("Failed to ensure feedback columns: %s", e)

        # Prune old report charts (360 days). Chat charts now live on disk under tmp/
        # and are pruned by a separate filesystem sweep in main.py:lifespan().
        try:
            from sqlalchemy import text
            async with engine.begin() as conn:
                result = await conn.execute(text(
                    "DELETE FROM web_charts WHERE "
                    "filename LIKE 'report\\_%' AND created_at < now() - interval '360 days'"
                ))
                if result.rowcount > 0:
                    logger.info("Pruned %d expired report charts from web_charts", result.rowcount)
        except Exception as e:
            logger.debug("Report chart cleanup skipped (table may not exist yet): %s", e)

        await _ensure_dev_user()
    except Exception as e:
        logger.warning(f"Could not initialize database (will retry on first request): {e}")


async def _ensure_dev_user():
    """Insert the dev mock user if DEV_MODE is on and it doesn't exist yet."""
    from config import DEV_MODE
    if not DEV_MODE:
        return
    from sqlalchemy import select
    from auth import _DEV_USER
    from models import WebUser
    async with async_session() as session:
        result = await session.execute(
            select(WebUser).where(WebUser.id == _DEV_USER.id)
        )
        if result.scalar_one_or_none() is None:
            session.add(WebUser(
                id=_DEV_USER.id,
                azure_ad_oid=_DEV_USER.azure_ad_oid,
                email=_DEV_USER.email,
                display_name=_DEV_USER.display_name,
            ))
            await session.commit()


async def close_db():
    """Dispose engine on shutdown."""
    await engine.dispose()
