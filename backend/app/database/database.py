"""
database/database.py
────────────────────
Async SQLAlchemy engine, session factory, and dependency injection helper.

All database I/O uses the async engine (aiosqlite) to avoid blocking the
FastAPI event loop. A synchronous engine is also exposed for test setups
and Alembic migrations.
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


# ── Async engine ──────────────────────────────────────────
engine: AsyncEngine = create_async_engine(
    url=settings.database_url,
    echo=settings.DATABASE_ECHO,
    connect_args={
        "check_same_thread": False,     # required for SQLite + asyncio
        "timeout": 30,
    },
)

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
    Does NOT drop existing tables — safe to call on restarts.
    Also applies lightweight column migrations for columns added after
    the initial schema was created (ALTER TABLE … ADD COLUMN IF NOT EXISTS
    equivalent for SQLite).
    """
    logger.info("Initialising database at: %s", settings.DATABASE_PATH)
    async with engine.begin() as conn:
        # Import models so Base.metadata knows about them
        from app.database import models  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)

    # ── Column migrations (SQLite does not support IF NOT EXISTS on ALTER) ──
    # For each new column we attempt ALTER TABLE and silently ignore the
    # "duplicate column name" error that SQLite raises if it already exists.
    _migrations = [
        "ALTER TABLE patients ADD COLUMN doctor_phone    VARCHAR(30)",
        "ALTER TABLE patients ADD COLUMN ambulance_phone VARCHAR(30)",
    ]
    async with engine.begin() as conn:
        for stmt in _migrations:
            try:
                await conn.execute(__import__("sqlalchemy").text(stmt))
                logger.info("Migration applied: %s", stmt)
            except Exception as exc:
                if "duplicate column name" in str(exc).lower():
                    pass  # column already exists — nothing to do
                else:
                    logger.warning("Migration skipped (%s): %s", stmt, exc)

    logger.info("Database initialisation complete.")


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
