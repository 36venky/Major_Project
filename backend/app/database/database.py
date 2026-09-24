"""
database/database.py
────────────────────
Async SQLAlchemy engine, session factory, and dependency injection helper.

Supports two database backends, selected via environment variables:

  DATABASE_TYPE=sqlite       (default — local development, unchanged behaviour)
  DATABASE_TYPE=postgresql   (Neon cloud — set DATABASE_URL in .env)

Engine creation is centralised here. All other modules consume the session
factory and the get_db() dependency without knowing which backend is active.

SQLite  → aiosqlite driver, check_same_thread=False, 30-second timeout
Neon    → asyncpg driver, SSL enforced by the connection string, connection
          pooling via NullPool (Neon's serverless endpoint closes idle
          connections, so SQLAlchemy's default pool causes stale-connection
          errors — NullPool avoids this cleanly).

Column migrations
─────────────────
SQLite does not support "ADD COLUMN IF NOT EXISTS", so the existing
approach of attempting ALTER TABLE and ignoring duplicate-column errors
is preserved — but ONLY when the backend is SQLite.  PostgreSQL receives
all columns from Base.metadata.create_all() because the models already
define them; no ALTER TABLE patches are needed there.
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


# ── Engine factory (centralised, backend-aware) ───────────

def _build_engine() -> AsyncEngine:
    """
    Build the async SQLAlchemy engine for the configured backend.

    Connection parameters are kept strictly backend-specific:
      - SQLite gets check_same_thread=False and a query timeout.
      - PostgreSQL gets NullPool (required for Neon serverless) and no
        SQLite-specific connect_args.

    The DATABASE_URL is never logged in full to avoid leaking credentials.
    """
    db_type = settings.database_type   # "sqlite" or "postgresql"
    db_url  = settings.database_url    # fully resolved async URL

    if db_type == "postgresql":
        # asyncpg / Neon
        # NullPool: do not maintain a persistent connection pool.
        # Neon's serverless proxy closes idle connections aggressively, so a
        # persistent pool accumulates stale connections.  NullPool opens a
        # fresh connection per request and closes it immediately afterward,
        # which is the safest default for serverless PostgreSQL.
        from sqlalchemy.pool import NullPool

        logger.info(
            "Database engine: PostgreSQL (asyncpg) — host=<redacted>"
        )
        return create_async_engine(
            url=db_url,
            echo=settings.DATABASE_ECHO,
            poolclass=NullPool,
            # No connect_args needed: SSL is controlled via ?ssl=require in the URL
        )

    # ── SQLite (default) ──────────────────────────────────
    logger.info("Database engine: SQLite — path=%s", settings.DATABASE_PATH)
    return create_async_engine(
        url=db_url,
        echo=settings.DATABASE_ECHO,
        connect_args={
            "check_same_thread": False,  # required for SQLite + asyncio
            "timeout": 30,
        },
    )


# Build the engine once at import time
engine: AsyncEngine = _build_engine()

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

    SQLite-only column migrations
    ─────────────────────────────
    Columns added to the models after the initial deployment cannot be
    added with "IF NOT EXISTS" on SQLite (it does not support that syntax).
    The workaround — attempt ALTER TABLE and swallow the
    "duplicate column name" error — is applied ONLY for SQLite.

    PostgreSQL receives a complete CREATE TABLE from the ORM models, so no
    ALTER TABLE patching is required there.
    """
    db_type = settings.database_type
    logger.info(
        "Initialising database  backend=%s  path/host=%s",
        db_type,
        settings.DATABASE_PATH if settings.is_sqlite else "<redacted>",
    )

    async with engine.begin() as conn:
        # Import models so Base.metadata has them registered
        from app.database import models  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)

    # ── Column migrations ──────────────────────────────────
    # SQLite: attempt ALTER TABLE, swallow "duplicate column" errors.
    # PostgreSQL: use "ADD COLUMN IF NOT EXISTS" (supported since PG 9.6).
    # Both paths are safe to run on every startup.
    if settings.is_sqlite:
        await _apply_sqlite_column_migrations()
    else:
        await _apply_postgres_column_migrations()

    logger.info("Database initialisation complete.")


async def _apply_sqlite_column_migrations() -> None:
    """
    Apply additive ALTER TABLE migrations for SQLite only.

    Each statement is attempted individually.  A "duplicate column name"
    error means the column already exists and is silently ignored.
    Any other error is logged as a warning and skipped.
    """
    import sqlalchemy

    _migrations = [
        # patients table — columns added after initial schema
        "ALTER TABLE patients ADD COLUMN doctor_phone    VARCHAR(30)",
        "ALTER TABLE patients ADD COLUMN ambulance_phone VARCHAR(30)",
        "ALTER TABLE patients ADD COLUMN location         TEXT",
        "ALTER TABLE patients ADD COLUMN location_address TEXT",
        "ALTER TABLE patients ADD COLUMN maps_link        TEXT",
        # Extended registration wizard columns (added in second iteration)
        "ALTER TABLE patients ADD COLUMN guardian_relation VARCHAR(60)",
        "ALTER TABLE patients ADD COLUMN doctor_name       VARCHAR(120)",
        "ALTER TABLE patients ADD COLUMN doctor_hospital   VARCHAR(200)",
        "ALTER TABLE patients ADD COLUMN ambulance_name    VARCHAR(120)",
        "ALTER TABLE patients ADD COLUMN notes             TEXT",
        "ALTER TABLE patients ADD COLUMN dob               VARCHAR(20)",
        # users table — columns added after initial schema
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
                logger.debug("SQLite migration applied: %s", stmt)
            except Exception as exc:
                if "duplicate column name" in str(exc).lower():
                    pass  # column already exists — nothing to do
                else:
                    logger.warning("SQLite migration skipped (%s): %s", stmt, exc)


async def _apply_postgres_column_migrations() -> None:
    """
    Apply additive column migrations for PostgreSQL using
    "ALTER TABLE … ADD COLUMN IF NOT EXISTS" (idempotent, safe on every restart).

    This covers columns that were added to the ORM models after the Neon
    database was first created with create_all(). Because create_all() only
    creates missing *tables*, not missing *columns*, we patch them here.
    """
    import sqlalchemy

    _migrations = [
        # patients — columns added after initial Neon schema
        "ALTER TABLE patients ADD COLUMN IF NOT EXISTS guardian_relation VARCHAR(60)",
        "ALTER TABLE patients ADD COLUMN IF NOT EXISTS doctor_name       VARCHAR(120)",
        "ALTER TABLE patients ADD COLUMN IF NOT EXISTS doctor_hospital   VARCHAR(200)",
        "ALTER TABLE patients ADD COLUMN IF NOT EXISTS ambulance_name    VARCHAR(120)",
        "ALTER TABLE patients ADD COLUMN IF NOT EXISTS notes             TEXT",
        "ALTER TABLE patients ADD COLUMN IF NOT EXISTS dob               VARCHAR(20)",
        # users — guard in case any of these were also missing
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone          VARCHAR(30)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS specialization VARCHAR(120)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS hospital       VARCHAR(200)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS license_number VARCHAR(80)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS address        TEXT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS city           VARCHAR(100)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS state          VARCHAR(100)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS country        VARCHAR(100)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login     TIMESTAMPTZ",
    ]

    async with engine.begin() as conn:
        for stmt in _migrations:
            try:
                await conn.execute(sqlalchemy.text(stmt))
                logger.debug("PostgreSQL migration applied: %s", stmt)
            except Exception as exc:
                logger.warning("PostgreSQL migration skipped (%s): %s", stmt, exc)


async def close_db() -> None:
    """Dispose of the async engine connection pool (called at shutdown)."""
    await engine.dispose()
    logger.info("Database connections closed.")


# ── Dependency injection ──────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides a scoped async database session.

    Works identically for SQLite and PostgreSQL — the session factory
    is already bound to the correct engine.

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
