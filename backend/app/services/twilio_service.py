"""
services/twilio_service.py
───────────────────────────
WhatsApp alert delivery via Twilio (Feature 4).

- Reads credentials exclusively from environment variables.
- Sends asynchronously via asyncio.create_task.
- Implements exponential back-off retry (2 s, 4 s, 8 s).
- Enforces per-patient, per-alert-type cooldown.
- Logs every dispatch attempt to the alert_logs table.
- Gracefully disables itself when credentials are absent.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.core.logger import get_logger
from app.database.database import AsyncSessionLocal
from app.database import crud

logger = get_logger("services.twilio")

# ── Recommendation map ────────────────────────────────────
_RECOMMENDATIONS: dict[str, str] = {
    "critical": "Seek immediate emergency care.",
    "warning":  "Contact your physician promptly.",
}

# ── Risk level labels that map to readable strings ────────
_RISK_LABELS: dict[str, str] = {
    "Low":      "LOW",
    "Moderate": "MODERATE",
    "High":     "HIGH",
    "Critical": "CRITICAL",
}


class TwilioWhatsAppService:
    """
    Singleton service for sending WhatsApp messages via Twilio.

    Instantiated once at import time. If TWILIO_ACCOUNT_SID /
    TWILIO_AUTH_TOKEN / TWILIO_WHATSAPP_FROM are missing from the
    environment the service disables itself without raising.
    """

    def __init__(self) -> None:
        self._account_sid: Optional[str] = os.getenv("TWILIO_ACCOUNT_SID")
        self._auth_token:  Optional[str] = os.getenv("TWILIO_AUTH_TOKEN")
        self._from_number: Optional[str] = os.getenv("TWILIO_WHATSAPP_FROM")  # e.g. whatsapp:+14155238886
        self._cooldown_s:  int           = int(os.getenv("WHATSAPP_COOLDOWN_SECONDS", "300"))

        self._enabled: bool = bool(self._account_sid and self._auth_token and self._from_number)

        # Cooldown tracker: {(patient_id, alert_type): datetime}
        self._last_sent: dict[tuple[str, str], datetime] = {}

        if not self._enabled:
            logger.warning(
                "WhatsApp service DISABLED — TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, "
                "or TWILIO_WHATSAPP_FROM not set in environment."
            )
        else:
            logger.info("WhatsApp service enabled (from=%s, cooldown=%ds)",
                        self._from_number, self._cooldown_s)

    # ── Public API ────────────────────────────────────────

    def dispatch(
        self,
        *,
        patient_id:   str,
        patient_name: str,
        guardian_phone: Optional[str],
        alert_type:   str,
        severity:     str,
        ecg_status:   str,
        risk_level:   str,
        alert_message: str,
        timestamp:    datetime,
    ) -> None:
        """
        Schedule an async WhatsApp dispatch without blocking the caller.

        Call this from synchronous or async code alike.
        """
        if not self._enabled:
            return

        if severity not in ("critical", "warning"):
            return

        # Cooldown check
        key = (patient_id, alert_type)
        last = self._last_sent.get(key)
        now  = datetime.now(timezone.utc)
        if last and (now - last) < timedelta(seconds=self._cooldown_s):
            logger.debug(
                "WhatsApp cooldown active for patient=%s type=%s — suppressing.",
                patient_id, alert_type,
            )
            return

        self._last_sent[key] = now

        if not guardian_phone:
            logger.debug(
                "No guardian_phone for patient=%s — skipping WhatsApp dispatch.", patient_id
            )
            return

        asyncio.create_task(
            self._send_with_retry(
                patient_id=patient_id,
                patient_name=patient_name,
                recipient_phone=guardian_phone,
                alert_type=alert_type,
                severity=severity,
                ecg_status=ecg_status,
                risk_level=risk_level,
                alert_message=alert_message,
                timestamp=timestamp,
            )
        )

    # ── Internal async helpers ────────────────────────────

    def _build_message(
        self,
        *,
        patient_name:  str,
        timestamp:     datetime,
        risk_level:    str,
        ecg_status:    str,
        alert_message: str,
        severity:      str,
    ) -> str:
        recommendation = _RECOMMENDATIONS.get(severity, "Please consult a healthcare professional.")
        ts_str = timestamp.strftime("%Y-%m-%d %H:%M UTC")
        return (
            f"🚨 *ECG Guardian Alert*\n\n"
            f"*Patient:* {patient_name}\n"
            f"*Time:* {ts_str}\n"
            f"*Risk Level:* {_RISK_LABELS.get(risk_level, risk_level)}\n"
            f"*ECG Status:* {ecg_status}\n"
            f"*Alert:* {alert_message}\n"
            f"*Recommendation:* {recommendation}"
        )

    async def _send_with_retry(
        self,
        *,
        patient_id:      str,
        patient_name:    str,
        recipient_phone: str,
        alert_type:      str,
        severity:        str,
        ecg_status:      str,
        risk_level:      str,
        alert_message:   str,
        timestamp:       datetime,
    ) -> None:
        """Attempt delivery with exponential back-off. Log outcome to DB."""
        body = self._build_message(
            patient_name=patient_name,
            timestamp=timestamp,
            risk_level=risk_level,
            ecg_status=ecg_status,
            alert_message=alert_message,
            severity=severity,
        )

        to_number = (
            recipient_phone if recipient_phone.startswith("whatsapp:")
            else f"whatsapp:{recipient_phone}"
        )

        delays = [2, 4, 8]
        last_error: Optional[str] = None

        for attempt, delay in enumerate(delays, start=1):
            try:
                # Run blocking Twilio call in executor to avoid blocking event loop
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    self._twilio_send,
                    to_number, body,
                )
                logger.info(
                    "WhatsApp sent to %s for patient=%s type=%s",
                    recipient_phone, patient_id, alert_type,
                )
                await self._log(patient_id, alert_type, recipient_phone, "sent", None)
                return
            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "WhatsApp attempt %d/%d failed for patient=%s: %s",
                    attempt, len(delays), patient_id, last_error,
                )
                if attempt < len(delays):
                    await asyncio.sleep(delay)

        logger.error(
            "WhatsApp delivery FAILED after %d attempts for patient=%s type=%s: %s",
            len(delays), patient_id, alert_type, last_error,
        )
        await self._log(patient_id, alert_type, recipient_phone, "failed", last_error)

    def _twilio_send(self, to_number: str, body: str) -> None:
        """Blocking Twilio API call — runs in executor thread."""
        from twilio.rest import Client  # imported lazily to avoid startup error when not installed
        client = Client(self._account_sid, self._auth_token)
        client.messages.create(
            from_=self._from_number,
            to=to_number,
            body=body,
        )

    async def _log(
        self,
        patient_id:    str,
        alert_type:    str,
        recipient:     str,
        status:        str,
        error_message: Optional[str],
    ) -> None:
        try:
            async with AsyncSessionLocal() as db:
                await crud.create_alert_log(
                    db,
                    patient_id=patient_id,
                    alert_type=alert_type,
                    recipient=recipient,
                    status=status,
                    error_message=error_message,
                )
                await db.commit()
        except Exception as exc:
            logger.error("Failed to log WhatsApp dispatch: %s", exc)


# ── Singleton ─────────────────────────────────────────────
whatsapp_service = TwilioWhatsAppService()
