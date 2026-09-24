"""
scheduler/weekly_reminder.py
─────────────────────────────
APScheduler setup and job registration.

All background jobs are registered here and started as part of
the application lifespan (main.py startup handler).
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings
from app.core.logger import get_logger
from app.scheduler.cleanup import (
    bp_reminder_check, daily_summary, delete_old_samples, sqlite_backup,
)

logger = get_logger("app.scheduler")

# ── Singleton scheduler ────────────────────────────────────
scheduler = AsyncIOScheduler(timezone="UTC")


def setup_scheduler() -> AsyncIOScheduler:
    """
    Register all background jobs and return the configured scheduler.

    Jobs are NOT started here — call scheduler.start() in main.py.
    """
    # Job 1: Delete old ECG samples every 6 hours
    scheduler.add_job(
        delete_old_samples,
        trigger=IntervalTrigger(hours=settings.BACKUP_INTERVAL_HOURS // 4),
        id="cleanup_samples",
        name="Delete old ECG samples",
        replace_existing=True,
    )

    # Job 2: Daily summary at midnight UTC
    scheduler.add_job(
        daily_summary,
        trigger=CronTrigger(hour=0, minute=0),
        id="daily_summary",
        name="Daily monitoring summary",
        replace_existing=True,
    )

    # Job 3: SQLite backup every 24 hours
    scheduler.add_job(
        sqlite_backup,
        trigger=IntervalTrigger(hours=settings.BACKUP_INTERVAL_HOURS),
        id="sqlite_backup",
        name="SQLite database backup",
        replace_existing=True,
    )

    # Job 4: Weekly BP reminder check every Monday at 9 AM
    scheduler.add_job(
        bp_reminder_check,
        trigger=CronTrigger(day_of_week="mon", hour=9),
        id="bp_reminder",
        name="Weekly BP update reminder",
        replace_existing=True,
    )

    logger.info("Scheduler: %d jobs registered", len(scheduler.get_jobs()))
    return scheduler
