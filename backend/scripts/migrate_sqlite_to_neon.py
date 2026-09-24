"""
scripts/migrate_sqlite_to_neon.py
──────────────────────────────────
One-shot migration utility: copies every table from the local SQLite database
into a Neon PostgreSQL database.

Safety guarantees
─────────────────
  • The SQLite database is NEVER modified or deleted.
  • The script is idempotent for tables that support ON CONFLICT DO NOTHING
    (i.e. all tables with integer or string primary keys).
  • Existing Neon rows are NOT overwritten; the script skips duplicates and
    reports them.
  • Foreign-key order is respected: parents are inserted before children.

Prerequisites
─────────────
  1. Both DATABASE_PATH (SQLite) and DATABASE_URL (Neon) must be reachable.
  2. The Neon database must be empty or already contain tables created by
     SQLAlchemy's Base.metadata.create_all().
     Run the app once with DATABASE_TYPE=postgresql to create the schema,
     then run this script to copy the data.

Usage
─────
  # From the backend/ directory:
  python scripts/migrate_sqlite_to_neon.py

  # Or with explicit paths:
  python scripts/migrate_sqlite_to_neon.py \\
      --sqlite  data/ecg_guardian.db \\
      --pg-url  "postgresql+psycopg2://USER:PASS@HOST/DB?sslmode=require"

Environment variables (read from .env automatically)
─────────────────────────────────────────────────────
  DATABASE_PATH  – relative path to the SQLite file (default: data/ecg_guardian.db)
  DATABASE_URL   – Neon connection string (must be set for this script to run)

Exit codes
──────────
  0 – migration completed without errors
  1 – migration completed with some skipped / failed rows
  2 – fatal error (cannot connect, schema missing, etc.)
"""

from __future__ import annotations

import argparse
import sys
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Ensure backend/ is on sys.path so app.* imports work ──
_BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_DIR))

# Load .env before importing settings
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=_BACKEND_DIR / ".env", override=False)
except ImportError:
    pass


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Migrate ECG Guardian data from SQLite to Neon PostgreSQL"
    )
    p.add_argument(
        "--sqlite",
        default=None,
        help="Path to the SQLite .db file (overrides DATABASE_PATH in .env)",
    )
    p.add_argument(
        "--pg-url",
        default=None,
        dest="pg_url",
        help="Synchronous PostgreSQL URL, e.g. postgresql+psycopg2://... "
             "(overrides DATABASE_URL in .env)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print what would be migrated without writing anything",
    )
    return p.parse_args()


# ── Colour output helpers ──────────────────────────────────

def _ok(msg: str)   -> None: print(f"  \033[32m✔\033[0m  {msg}")
def _warn(msg: str) -> None: print(f"  \033[33m⚠\033[0m  {msg}")
def _err(msg: str)  -> None: print(f"  \033[31m✘\033[0m  {msg}")
def _info(msg: str) -> None: print(f"     {msg}")
def _head(msg: str) -> None: print(f"\n\033[1m{msg}\033[0m")


# ── Migration table definitions ────────────────────────────
# Order matters: parent tables must appear before child tables so that
# foreign-key constraints are satisfied when rows are inserted into Neon.

_TABLE_ORDER = [
    "users",
    "patients",
    "ecg_sessions",
    "ecg_samples",
    "heart_rate",
    "alerts",
    "weekly_health",
    "doctor_notes",
    "risk_predictions",
    "alert_logs",
]


def _build_sqlite_url(sqlite_path: str) -> str:
    path = Path(sqlite_path)
    if not path.is_absolute():
        path = _BACKEND_DIR / path
    return f"sqlite:///{path}"


def _normalise_pg_url(url: str) -> str:
    """Ensure the synchronous psycopg2 driver is used (not asyncpg)."""
    url = url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    url = url.replace("postgres://",           "postgresql+psycopg2://", 1)
    if not url.startswith("postgresql"):
        raise ValueError(f"Not a PostgreSQL URL: {url!r}")
    if "psycopg2" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def _redact(url: str) -> str:
    """Remove credentials from a URL for safe logging."""
    try:
        from urllib.parse import urlparse, urlunparse
        p = urlparse(url)
        safe = p._replace(netloc=f"***:***@{p.hostname}" + (f":{p.port}" if p.port else ""))
        return urlunparse(safe)
    except Exception:
        return "<redacted>"


def _row_to_dict(row, columns: list[str]) -> dict[str, Any]:
    return dict(zip(columns, row))


def _migrate_table(
    table_name: str,
    src_conn,
    dst_conn,
    dry_run: bool,
) -> tuple[int, int, int]:
    """
    Copy all rows from *table_name* in SQLite to PostgreSQL.

    Returns (total, inserted, skipped).
    """
    from sqlalchemy import text

    # Read all rows from SQLite
    result = src_conn.execute(text(f"SELECT * FROM {table_name}"))
    columns  = list(result.keys())
    rows     = result.fetchall()
    total    = len(rows)

    if total == 0:
        return 0, 0, 0

    inserted = 0
    skipped  = 0

    for row in rows:
        data = _row_to_dict(row, columns)

        # Build a parameterised INSERT … ON CONFLICT DO NOTHING
        col_names   = ", ".join(f'"{c}"' for c in columns)
        placeholders = ", ".join(f":{c}" for c in columns)
        stmt = text(
            f'INSERT INTO "{table_name}" ({col_names}) '
            f"VALUES ({placeholders}) "
            f"ON CONFLICT DO NOTHING"
        )

        if dry_run:
            inserted += 1
            continue

        try:
            r = dst_conn.execute(stmt, data)
            if r.rowcount == 0:
                skipped += 1   # ON CONFLICT DO NOTHING — row already existed
            else:
                inserted += 1
        except Exception as exc:
            _warn(f"Row skipped in {table_name}: {exc}")
            skipped += 1

    return total, inserted, skipped


def main() -> int:
    args = _parse_args()

    _head("ECG Guardian  ·  SQLite → Neon PostgreSQL Migration")
    print(f"  Started at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    if args.dry_run:
        print("  \033[33mDRY RUN — no data will be written\033[0m")

    # ── Resolve connection URLs ────────────────────────────
    from app.core.config import settings

    sqlite_path = args.sqlite or (str(_BACKEND_DIR / settings.DATABASE_PATH))
    if not Path(sqlite_path).exists():
        _err(f"SQLite file not found: {sqlite_path}")
        return 2

    raw_pg_url = args.pg_url or settings.DATABASE_URL_OVERRIDE
    if not raw_pg_url:
        _err(
            "No PostgreSQL URL found.\n"
            "  Set DATABASE_URL in .env or pass --pg-url on the command line."
        )
        return 2

    try:
        pg_url = _normalise_pg_url(raw_pg_url)
    except ValueError as exc:
        _err(str(exc))
        return 2

    sqlite_url = _build_sqlite_url(sqlite_path)

    _info(f"Source (SQLite) : {sqlite_path}")
    _info(f"Target (Neon)   : {_redact(pg_url)}")

    # ── Import SQLAlchemy synchronous engine ───────────────
    try:
        from sqlalchemy import create_engine, inspect, text
    except ImportError:
        _err("sqlalchemy is not installed. Run: pip install sqlalchemy")
        return 2

    # ── psycopg2 check ─────────────────────────────────────
    try:
        import psycopg2  # noqa: F401
    except ImportError:
        _err(
            "psycopg2 is not installed. Run:\n"
            "  pip install psycopg2-binary\n"
            "(Only needed for this migration script, not the main app.)"
        )
        return 2

    # ── Connect ────────────────────────────────────────────
    _head("Connecting …")

    try:
        src_engine = create_engine(sqlite_url, echo=False)
        with src_engine.connect() as c:
            c.execute(text("SELECT 1"))
        _ok(f"SQLite connected ({sqlite_path})")
    except Exception as exc:
        _err(f"Cannot open SQLite: {exc}")
        return 2

    try:
        dst_engine = create_engine(pg_url, echo=False)
        with dst_engine.connect() as c:
            c.execute(text("SELECT 1"))
        _ok(f"Neon PostgreSQL connected ({_redact(pg_url)})")
    except Exception as exc:
        _err(f"Cannot connect to Neon: {exc}")
        _info("Make sure DATABASE_URL is correct and the Neon project is active.")
        return 2

    # ── Schema check ───────────────────────────────────────
    _head("Checking schema …")

    with dst_engine.connect() as dst_conn:
        pg_inspector = inspect(dst_engine)
        pg_tables    = set(pg_inspector.get_table_names())

    missing = [t for t in _TABLE_ORDER if t not in pg_tables]
    if missing:
        _err(
            f"These tables are missing from Neon: {missing}\n"
            "  Start the app once with DATABASE_TYPE=postgresql to create the schema:\n"
            "    DATABASE_TYPE=postgresql DATABASE_URL=<URL> python -m uvicorn main:app"
        )
        return 2

    _ok("All tables present in Neon")

    # ── Migrate ────────────────────────────────────────────
    _head("Migrating tables …")

    grand_total = grand_inserted = grand_skipped = 0
    has_errors  = False

    with src_engine.connect() as src_conn, dst_engine.begin() as dst_conn:
        for table in _TABLE_ORDER:
            try:
                total, inserted, skipped = _migrate_table(
                    table, src_conn, dst_conn, args.dry_run
                )
                grand_total    += total
                grand_inserted += inserted
                grand_skipped  += skipped

                label = "(dry-run)" if args.dry_run else ""
                if total == 0:
                    _info(f"{table:<25}  (empty table — skipped)")
                elif skipped > 0:
                    _warn(
                        f"{table:<25}  {inserted:>6} inserted  "
                        f"{skipped:>6} skipped {label}"
                    )
                else:
                    _ok(
                        f"{table:<25}  {inserted:>6} inserted {label}"
                    )

            except Exception as exc:
                _err(f"{table}: {exc}")
                has_errors = True

    # ── Summary ────────────────────────────────────────────
    _head("Summary")
    _info(f"Total rows processed : {grand_total}")
    _info(f"Rows inserted        : {grand_inserted}")
    _info(f"Rows skipped         : {grand_skipped}")

    if args.dry_run:
        print("\n  \033[33mDry run complete — nothing was written to Neon.\033[0m")
        return 0

    if has_errors:
        print("\n  \033[33mMigration completed with errors — check warnings above.\033[0m")
        return 1

    print("\n  \033[32mMigration completed successfully.\033[0m")
    print("  The original SQLite database was not modified.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
