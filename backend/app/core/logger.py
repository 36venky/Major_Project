"""
core/logger.py
──────────────
Centralised logging configuration.

Creates separate rotating log files for each subsystem:
  backend.log   – general application
  serial.log    – COM port / hardware
  database.log  – SQLAlchemy / DB operations
  alerts.log    – alert engine events
  api.log       – HTTP request/response

Usage:
    from app.core.logger import get_logger
    logger = get_logger(__name__)          # uses module name
    logger = get_logger("serial")         # uses named subsystem logger
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from app.core.config import settings

# Map subsystem names to dedicated log files
_SUBSYSTEM_FILES: dict[str, str] = {
    "serial":   "serial.log",
    "database": "database.log",
    "alerts":   "alerts.log",
    "api":      "api.log",
}

_DEFAULT_FILE = "backend.log"

# Shared formatter
_FORMATTER = logging.Formatter(
    fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_configured_loggers: dict[str, logging.Logger] = {}


def _make_file_handler(log_file: str) -> RotatingFileHandler:
    """Create a rotating file handler for the given filename."""
    path: Path = settings.logs_dir / log_file
    handler = RotatingFileHandler(
        filename=path,
        maxBytes=settings.LOG_MAX_BYTES,
        backupCount=settings.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(_FORMATTER)
    return handler


def _make_console_handler() -> logging.StreamHandler:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_FORMATTER)
    return handler


def get_logger(name: str) -> logging.Logger:
    """
    Return a configured logger for the given name or subsystem.

    If `name` matches a known subsystem (serial, database, alerts, api),
    log output is directed to that subsystem's dedicated file as well as
    the main backend.log.

    Args:
        name: Module __name__ or subsystem label.

    Returns:
        Configured logging.Logger instance.
    """
    if name in _configured_loggers:
        return _configured_loggers[name]

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))

    if not logger.handlers:
        # Always write to backend.log and stdout
        logger.addHandler(_make_file_handler(_DEFAULT_FILE))
        logger.addHandler(_make_console_handler())

        # Write to subsystem log if applicable
        for subsystem, filename in _SUBSYSTEM_FILES.items():
            if subsystem in name.lower():
                logger.addHandler(_make_file_handler(filename))
                break

    logger.propagate = False
    _configured_loggers[name] = logger
    return logger


# Root application logger
app_logger = get_logger("app")
