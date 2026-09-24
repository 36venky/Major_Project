"""
alerts/notification.py
───────────────────────
In-process notification dispatcher.

Currently dispatches to:
  - Application logger (always)
  - WebSocket broadcast queue (via callback injection)

Designed for extension: add email / SMS / push by implementing
additional dispatcher classes and registering them here.
"""

from __future__ import annotations

from typing import Callable, Optional

from app.alerts.alert_engine import AlertEvent
from app.core.logger import get_logger

logger = get_logger("alerts.notification")


class NotificationDispatcher:
    """
    Routes alert events to one or more notification channels.

    Args:
        ws_broadcaster: Optional async callable that sends alert
                        payload to connected WebSocket clients.
    """

    def __init__(self, ws_broadcaster: Optional[Callable] = None):
        self._ws_broadcaster = ws_broadcaster

    def dispatch(self, event: AlertEvent) -> None:
        """
        Synchronously dispatch an alert event.

        Logs the event. If a WebSocket broadcaster is registered,
        schedules the async broadcast.
        """
        self._log(event)
        # WebSocket broadcast is handled by ECGService which owns the ws manager

    def _log(self, event: AlertEvent) -> None:
        level = {
            "critical": logger.critical,
            "warning":  logger.warning,
            "info":     logger.info,
        }.get(event.severity, logger.info)
        level(
            "ALERT [%s] patient=%s — %s",
            event.alert_type, event.patient_id, event.message
        )
