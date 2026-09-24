"""
scheduler/cleanup.py
─────────────────────
Background scheduled jobs.

Jobs:
  1. delete_old_samples     – runs every 6h, purges ECG samples > 48h old
  2. daily_summary          – runs at midnight, logs session statistics
  3. sqlite_backup          – runs every 24h, copies DB to data/backups/
  4. bp_reminder_check      – runs weekly, alerts if BP not updated
"""

from __future__ import annotations

import asyncio
import shutil
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.core.logger import get_logger
from app.database import crud
from app.database.database import AsyncSessionLocal

logger = get_logger("app.scheduler")

_BACKUP_DIR = Path("data/backups")


async def delete_old_samples() -> None:
    """Delete raw ECG samples older than settings.RAW_ECG_RETENTION_HOURS."""
    logger.info("Scheduler: running ECG sample cleanup (retention=%dh)", settings.RAW_ECG_RETENTION_HOURS)
    try:
        async with AsyncSessionLocal() as db:
            count = await crud.delete_old_samples(db, settings.RAW_ECG_RETENTION_HOURS)
        logger.info("Scheduler: deleted %d old ECG samples", count)
    except Exception as exc:
        logger.error("Scheduler cleanup error: %s", exc)


async def daily_summary() -> None:
    """Generate a daily summary log of active sessions."""
    logger.info("Scheduler: daily summary — %s", datetime.now(timezone.utc).date())
    try:
        async with AsyncSessionLocal() as db:
            patients = await crud.get_all_patients(db)
            for p in patients:
                sessions = await crud.get_sessions_for_patient(db, p.patient_id, limit=1)
                if sessions:
                    s = sessions[0]
                    logger.info(
                        "Daily summary | patient=%s  last_session=%s  avg_bpm=%.1f",
                        p.patient_id, s.session_id, s.average_bpm or 0,
                    )
    except Exception as exc:
        logger.error("Scheduler daily summary error: %s", exc)


async def sqlite_backup() -> None:
    """Copy the SQLite database file to the backups directory."""
    from app.core.config import ROOT_DIR
    db_path = ROOT_DIR / settings.DATABASE_PATH
    if not db_path.exists():
        return

    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest  = _BACKUP_DIR / f"ecg_guardian_{stamp}.db"
    try:
        shutil.copy2(db_path, dest)
        logger.info("Scheduler: DB backed up to %s", dest)
        # Keep only the last 7 backups
        backups = sorted(_BACKUP_DIR.glob("ecg_guardian_*.db"))
        for old in backups[:-7]:
            old.unlink()
    except Exception as exc:
        logger.error("Scheduler backup error: %s", exc)


async def bp_reminder_check() -> None:
    """Alert if a patient has not updated blood pressure in the last 7 days."""
    from datetime import timedelta
    logger.info("Scheduler: weekly BP reminder check")
    try:
        async with AsyncSessionLocal() as db:
            patients = await crud.get_all_patients(db)
            for p in patients:
                record = await crud.get_latest_weekly_health(db, p.patient_id)
                if record is None:
                    logger.warning("BP reminder: patient %s has NO health records", p.patient_id)
                else:
                    age_days = (datetime.now(timezone.utc) - record.date.replace(tzinfo=timezone.utc)).days
                    if age_days >= 7:
                        logger.warning(
                            "BP reminder: patient %s — last update was %d days ago",
                            p.patient_id, age_days,
                        )
    except Exception as exc:
        logger.error("Scheduler BP reminder error: %s", exc)
