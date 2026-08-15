"""
core/config.py
──────────────
Single source of truth for all application settings.

Loads values from config.yaml then allows .env overrides via pydantic-settings.
All modules import `settings` from here — never read config files directly.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Locate project root (two levels up from this file)
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_FILE = ROOT_DIR / "config.yaml"


def _load_yaml() -> dict:
    """Load raw YAML config, returning empty dict if file is missing."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


_yaml = _load_yaml()


def _get(keys: str, default=None):
    """Dot-notation access into nested YAML dict. e.g. 'serial.port'"""
    val = _yaml
    for k in keys.split("."):
        if not isinstance(val, dict):
            return default
        val = val.get(k, default)
    return val


class Settings(BaseSettings):
    """
    Application settings.

    Priority (highest → lowest):
      1. Environment variables / .env file
      2. config.yaml values
    """

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ────────────────────────────────────────────────
    APP_TITLE: str       = _get("app.title",       "ECG Guardian API")
    APP_VERSION: str     = _get("app.version",     "1.0.0")
    APP_DESCRIPTION: str = _get("app.description", "ECG Monitoring Backend")
    DEBUG: bool          = _get("app.debug",        False)

    # ── Server ─────────────────────────────────────────────
    HOST: str = _get("server.host", "0.0.0.0")
    PORT: int = _get("server.port", 8000)

    # ── Device (ESP32 WiFi) ────────────────────────────────
    MOCK_WHEN_UNAVAILABLE: bool = _get("device.mock_when_unavailable", True)
    MOCK_CONNECT_TIMEOUT: float = _get("device.mock_connect_timeout",  10.0)
    SAMPLING_RATE: int          = _get("device.sampling_rate",         250)

    # ── Database ───────────────────────────────────────────
    DATABASE_PATH: str = _get("database.path", "data/ecg_guardian.db")
    DATABASE_ECHO: bool= _get("database.echo", False)

    # ── Retention ──────────────────────────────────────────
    RAW_ECG_RETENTION_HOURS: int    = _get("retention.raw_ecg_hours",        48)
    BACKUP_INTERVAL_HOURS: int      = _get("retention.backup_interval_hours", 24)

    # ── Signal Processing ──────────────────────────────────
    LOWPASS_CUTOFF: float           = _get("processing.lowpass_cutoff",           40.0)
    HIGHPASS_CUTOFF: float          = _get("processing.highpass_cutoff",           0.5)
    FILTER_ORDER: int               = _get("processing.filter_order",               4)
    R_PEAK_MIN_DISTANCE: float      = _get("processing.r_peak_min_distance",       0.6)
    R_PEAK_THRESHOLD_FACTOR: float  = _get("processing.r_peak_threshold_factor",   0.6)

    # ── Alerts ─────────────────────────────────────────────
    HR_HIGH: int                = _get("alerts.hr_high",             100)
    HR_LOW: int                 = _get("alerts.hr_low",               60)
    HR_CRITICAL_HIGH: int       = _get("alerts.hr_critical_high",    150)
    HR_CRITICAL_LOW: int        = _get("alerts.hr_critical_low",      40)
    SIGNAL_QUALITY_WARN: int    = _get("alerts.signal_quality_warn",  50)
    SIGNAL_QUALITY_POOR: int    = _get("alerts.signal_quality_poor",  30)
    MAX_ACTIVE_ALERTS: int      = _get("alerts.max_active_alerts",    50)

    # ── Security ───────────────────────────────────────────
    JWT_SECRET: str                     = _get("security.jwt_secret", "change-me")
    JWT_ALGORITHM: str                  = _get("security.jwt_algorithm", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int    = _get("security.access_token_expire_minutes", 60)
    REFRESH_TOKEN_EXPIRE_DAYS: int      = _get("security.refresh_token_expire_days",    7)

    # ── Logging ────────────────────────────────────────────
    LOG_LEVEL: str  = _get("logging.level",       "INFO")
    LOG_MAX_BYTES: int = _get("logging.max_bytes", 10485760)
    LOG_BACKUP_COUNT: int = _get("logging.backup_count", 5)

    # ── WebSocket ──────────────────────────────────────────
    WS_BROADCAST_INTERVAL: float = _get("websocket.broadcast_interval", 0.04)
    WS_MAX_CONNECTIONS: int      = _get("websocket.max_connections",     20)

    @property
    def database_url(self) -> str:
        """SQLite async URL for aiosqlite."""
        db_path = ROOT_DIR / self.DATABASE_PATH
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite+aiosqlite:///{db_path}"

    @property
    def database_url_sync(self) -> str:
        """Synchronous SQLite URL (used only for Alembic / tests)."""
        db_path = ROOT_DIR / self.DATABASE_PATH
        return f"sqlite:///{db_path}"

    @property
    def logs_dir(self) -> Path:
        d = ROOT_DIR / "logs"
        d.mkdir(exist_ok=True)
        return d


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached singleton Settings instance."""
    return Settings()


# Convenience alias used throughout the codebase
settings = get_settings()
