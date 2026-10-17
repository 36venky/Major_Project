"""
database/database.py
────────────────────
Async SQLAlchemy engine, session factory, and dependency injection helper.

Supports both:
  • PostgreSQL via asyncpg  (Neon cloud — set DATABASE_TYPE=postgresql in .env)
  • SQLite via aiosqlite    (local development fallback)

All database I/O uses the async engine to avoid blocking the FastAPI event loop.
"""

from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger("database")


# ── Declarative base for all ORM models ───────────────────
class Base(DeclarativeBase):
    pass


# ── Engine factory ────────────────────────────────────────

def _make_engine() -> AsyncEngine:
    url = settings.database_url
    if settings.is_postgres:
        logger.info("Database: PostgreSQL (Neon) — %s", url.split("@")[-1])
        return create_async_engine(
            url=url,
            echo=settings.DATABASE_ECHO,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,   # detect stale connections
            connect_args={
                "ssl":                  "require",   # Neon requires TLS
                "statement_cache_size": 0,           # required for Neon pgBouncer pooler
            },
        )
    else:
        logger.info("Database: SQLite (local) — %s", settings.DATABASE_PATH)
        return create_async_engine(
            url=url,
            echo=settings.DATABASE_ECHO,
            connect_args={
                "check_same_thread": False,
                "timeout": 30,
            },
        )


engine: AsyncEngine = _make_engine()

# ── Session factory ───────────────────────────────────────
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


# ── Table initialisation ──────────────────────────────────

async def init_db() -> None:
    """
    Create all tables defined on Base metadata.

    Called once at application startup (lifespan handler in main.py).
    Safe to call on restarts — does NOT drop existing tables.

    For PostgreSQL: uses CREATE TABLE IF NOT EXISTS (handled by SQLAlchemy).
    For SQLite:     additionally runs lightweight ALTER TABLE migrations for
                    columns added after the initial schema was deployed.
    """
    logger.info("Initialising database…")
    async with engine.begin() as conn:
        from app.database import models  # noqa: F401  — register models with Base
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Tables created / verified.")

    # SQLite-only column migrations (PostgreSQL handles this via create_all)
    if not settings.is_postgres:
        await _run_sqlite_migrations()

    logger.info("Database initialisation complete.")


async def _run_sqlite_migrations() -> None:
    """
    Apply incremental ALTER TABLE migrations for SQLite.

    SQLite does not support IF NOT EXISTS on ALTER TABLE, so we attempt each
    statement and silently ignore the 'duplicate column name' error.
    """
    import sqlalchemy

    _migrations = [
        # patients — original extended fields
        "ALTER TABLE patients ADD COLUMN doctor_phone      VARCHAR(30)",
        "ALTER TABLE patients ADD COLUMN ambulance_phone   VARCHAR(30)",
        "ALTER TABLE patients ADD COLUMN location          TEXT",
        "ALTER TABLE patients ADD COLUMN location_address  TEXT",
        "ALTER TABLE patients ADD COLUMN maps_link         TEXT",
        # patients — feature-parity fields (match frontend registration form)
        "ALTER TABLE patients ADD COLUMN dob               VARCHAR(20)",
        "ALTER TABLE patients ADD COLUMN notes             TEXT",
        "ALTER TABLE patients ADD COLUMN guardian_relation VARCHAR(80)",
        "ALTER TABLE patients ADD COLUMN doctor_name       VARCHAR(120)",
        "ALTER TABLE patients ADD COLUMN doctor_hospital   VARCHAR(200)",
        "ALTER TABLE patients ADD COLUMN ambulance_name    VARCHAR(120)",
        # users — extended fields
        "ALTER TABLE users ADD COLUMN phone           VARCHAR(30)",
        "ALTER TABLE users ADD COLUMN specialization  VARCHAR(120)",
        "ALTER TABLE users ADD COLUMN hospital        VARCHAR(200)",
        "ALTER TABLE users ADD COLUMN license_number  VARCHAR(80)",
        "ALTER TABLE users ADD COLUMN address         TEXT",
        "ALTER TABLE users ADD COLUMN city            VARCHAR(100)",
        "ALTER TABLE users ADD COLUMN state           VARCHAR(100)",
        "ALTER TABLE users ADD COLUMN country         VARCHAR(100)",
        "ALTER TABLE users ADD COLUMN last_login      DATETIME",
    ]
    async with engine.begin() as conn:
        for stmt in _migrations:
            try:
                await conn.execute(sqlalchemy.text(stmt))
            except Exception as exc:
                if "duplicate column name" in str(exc).lower():
                    pass  # already exists
                else:
                    logger.warning("Migration skipped (%s): %s", stmt[:60], exc)


async def close_db() -> None:
    """Dispose of the async engine connection pool (called at shutdown)."""
    await engine.dispose()
    logger.info("Database connections closed.")


# ── Dependency injection ──────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides a scoped async database session.

    Usage:
        @router.get("/")
        async def endpoint(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
