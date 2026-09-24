"""
services/twilio_service.py
───────────────────────────
WhatsApp alert delivery via Twilio (Feature 4).

Behaviour
─────────
- Reads credentials exclusively from environment variables / .env.
- Sends to ALL of the patient's contact numbers:
    1. guardian_phone  (always primary)
    2. emergency_contact (if different from guardian_phone)
    3. phone (patient's own number, if different from the above two)
- Each number is dispatched as an independent async task with
  exponential back-off (2 s → 4 s → 8 s).
- A per-patient, per-alert-type cooldown prevents message floods.
- Every attempt (success or failure) is logged to alert_logs.
- `dispatch()` returns a list of per-recipient result dicts so the
  caller can push a WebSocket notification to the frontend.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(dotenv_path=_env_path, override=False)
except ImportError:
    pass

from app.core.logger import get_logger
from app.database.database import AsyncSessionLocal
from app.database import crud

logger = get_logger("services.twilio")

_RECOMMENDATIONS: dict[str, str] = {
    "critical": "Seek immediate emergency care.",
    "warning":  "Contact your physician promptly.",
}

_RISK_LABELS: dict[str, str] = {
    "Low":      "LOW",
    "Moderate": "MODERATE",
    "High":     "HIGH",
    "Critical": "CRITICAL",
}


def e164(phone: str) -> str:
    """
    Normalise a phone number to E.164 format.

    Handles common Indian formats:
      '+91 7619109684'  → '+917619109684'
      '7619109684'      → '+917619109684'
      '07619109684'     → '+917619109684'
      '917619109684'    → '+917619109684'
    """
    if not phone:
        return phone
    raw = phone.replace("whatsapp:", "").strip()
    raw = "".join(c for c in raw if c.isdigit() or c == "+")
    if raw.startswith("+"):
        return raw
    if raw.startswith("0"):
        raw = raw[1:]
    if len(raw) == 10:
        return f"+91{raw}"
    if raw.startswith("91") and len(raw) == 12:
        return f"+{raw}"
    return f"+{raw}"


def _collect_recipients(
    guardian_phone:    Optional[str],
    emergency_contact: Optional[str],
    phone:             Optional[str],
    doctor_phone:      Optional[str] = None,
) -> list[str]:
    """
    Return a deduplicated ordered list of E.164 numbers to message.

    Priority order: guardian_phone → emergency_contact → phone → doctor_phone.
    Numbers that are empty, None, or duplicates are silently dropped.
    """
    seen: set[str] = set()
    result: list[str] = []
    for raw in (guardian_phone, emergency_contact, phone, doctor_phone):
        if not raw:
            continue
        normalised = e164(raw.strip())
        if normalised and normalised not in seen:
            seen.add(normalised)
            result.append(normalised)
    return result


class TwilioWhatsAppService:
    """
    Singleton service for sending WhatsApp messages via Twilio.

    Sends to all of the patient's registered contact numbers.
    Gracefully disables itself when credentials are absent.
    """

    def __init__(self) -> None:
        self._account_sid: Optional[str] = os.getenv("TWILIO_ACCOUNT_SID")
        self._auth_token:  Optional[str] = os.getenv("TWILIO_AUTH_TOKEN")
        self._from_number: Optional[str] = os.getenv("TWILIO_WHATSAPP_FROM")
        self._cooldown_s:  int           = int(os.getenv("WHATSAPP_COOLDOWN_SECONDS", "300"))  # 5 minutes

        self._enabled: bool = bool(self._account_sid and self._auth_token and self._from_number)

        # Cooldown tracker: {(patient_id, alert_type): datetime}
        self._last_sent: dict[tuple[str, str], datetime] = {}

        if not self._enabled:
            logger.warning(
                "WhatsApp service DISABLED — TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, "
                "or TWILIO_WHATSAPP_FROM not set in environment."
            )
        else:
            logger.info(
                "WhatsApp service enabled (from=%s, cooldown=%ds)",
                self._from_number, self._cooldown_s,
            )

    # ── Public API ────────────────────────────────────────

    def dispatch(
        self,
        *,
        patient_id:        str,
        patient_name:      str,
        guardian_phone:    Optional[str],
        emergency_contact: Optional[str] = None,
        phone:             Optional[str] = None,
        doctor_phone:      Optional[str] = None,
        ambulance_phone:   Optional[str] = None,
        maps_link:         Optional[str] = None,
        alert_type:        str,
        severity:          str,
        ecg_status:        str,
        risk_level:        str,
        alert_message:     str,
        timestamp:         datetime,
        on_result:         Optional[callable] = None,
    ) -> None:
        """
        Schedule async WhatsApp dispatch to all patient contacts.

        Parameters
        ----------
        on_result : optional async callable(results: list[dict])
            Called once all sends have settled.  Each dict has keys:
              { "phone": str, "status": "sent"|"failed", "error": str|None }
            Use this to push a WebSocket notification to the frontend.
        """
        if not self._enabled:
            return

        if severity not in ("critical", "warning"):
            return

        # Cooldown check — one gate covers all recipients for this alert type
        key  = (patient_id, alert_type)
        last = self._last_sent.get(key)
        now  = datetime.now(timezone.utc)
        if last and (now - last) < timedelta(seconds=self._cooldown_s):
            logger.debug(
                "WhatsApp cooldown active for patient=%s type=%s — suppressing.",
                patient_id, alert_type,
            )
            return

        recipients = _collect_recipients(
            guardian_phone, emergency_contact, phone, doctor_phone
        )
        if not recipients:
            logger.debug(
                "No contact numbers for patient=%s — skipping WhatsApp dispatch.", patient_id
            )
            return

        self._last_sent[key] = now

        asyncio.create_task(
            self._dispatch_all(
                patient_id=patient_id,
                patient_name=patient_name,
                recipients=recipients,
                alert_type=alert_type,
                severity=severity,
                ecg_status=ecg_status,
                risk_level=risk_level,
                alert_message=alert_message,
                timestamp=timestamp,
                doctor_phone=doctor_phone,
                ambulance_phone=ambulance_phone,
                maps_link=maps_link,
                on_result=on_result,
            )
        )

    # ── Internal async helpers ────────────────────────────

    async def _dispatch_all(
        self,
        *,
        patient_id:      str,
        patient_name:    str,
        recipients:      list[str],
        alert_type:      str,
        severity:        str,
        ecg_status:      str,
        risk_level:      str,
        alert_message:   str,
        timestamp:       datetime,
        doctor_phone:    Optional[str] = None,
        ambulance_phone: Optional[str] = None,
        maps_link:       Optional[str] = None,
        on_result:       Optional[callable],
    ) -> None:
        """Send to every recipient concurrently and collect results."""
        body = self._build_message(
            patient_name=patient_name,
            timestamp=timestamp,
            risk_level=risk_level,
            ecg_status=ecg_status,
            alert_message=alert_message,
            severity=severity,
            doctor_phone=doctor_phone,
            ambulance_phone=ambulance_phone,
            maps_link=maps_link,
        )

        tasks = [
            self._send_with_retry(
                patient_id=patient_id,
                alert_type=alert_type,
                recipient_phone=num,
                body=body,
            )
            for num in recipients
        ]

        results = await asyncio.gather(*tasks, return_exceptions=False)

        if on_result:
            try:
                await on_result(results)
            except Exception as exc:
                logger.error("on_result callback error: %s", exc)

    def _build_message(
        self,
        *,
        patient_name:    str,
        timestamp:       datetime,
        risk_level:      str,
        ecg_status:      str,
        alert_message:   str,
        severity:        str,
        doctor_phone:    Optional[str] = None,
        ambulance_phone: Optional[str] = None,
        maps_link:       Optional[str] = None,
    ) -> str:
        ts_str     = timestamp.strftime("%d %b %Y, %I:%M %p")
        risk_label = _RISK_LABELS.get(risk_level, risk_level.upper())
        urgent     = "🔴 CRITICAL" if severity == "critical" else "🟡 WARNING"

        lines = [
            f"*ECG Guardian Alert* — {urgent}",
            "",
            f"*Patient:* {patient_name}",
            f"*Time:* {ts_str}",
            f"*Condition:* {ecg_status}",
            f"*Detail:* {alert_message}",
            f"*Risk:* {risk_label}",
        ]

        if maps_link:
            lines += ["", f"📍 *Location:* {maps_link}"]

        if doctor_phone or ambulance_phone:
            lines.append("")
            if doctor_phone:
                lines.append(f"📞 *Doctor:* {doctor_phone}")
            if ambulance_phone:
                lines.append(f"🚑 *Ambulance:* {ambulance_phone}")

        lines += ["", "_ECG Guardian – Remote Cardiac Monitoring_"]
        return "\n".join(lines)

    async def _send_with_retry(
        self,
        *,
        patient_id:      str,
        alert_type:      str,
        recipient_phone: str,
        body:            str,
    ) -> dict:
        """
        Attempt delivery with exponential back-off.  Log outcome to DB.

        Returns { "phone": str, "status": "sent"|"failed", "error": str|None }
        """
        to_number = (
            recipient_phone if recipient_phone.startswith("whatsapp:")
            else f"whatsapp:{recipient_phone}"
        )

        delays = [2, 4, 8]
        last_error: Optional[str] = None

        for attempt, delay in enumerate(delays, start=1):
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._twilio_send, to_number, body)
                logger.info(
                    "WhatsApp sent to %s for patient=%s type=%s",
                    recipient_phone, patient_id, alert_type,
                )
                await self._log(patient_id, alert_type, recipient_phone, "sent", None)
                return {"phone": recipient_phone, "status": "sent", "error": None}
            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "WhatsApp attempt %d/%d failed for %s patient=%s: %s",
                    attempt, len(delays), recipient_phone, patient_id, last_error,
                )
                if attempt < len(delays):
                    await asyncio.sleep(delay)

        logger.error(
            "WhatsApp delivery FAILED after %d attempts to %s patient=%s type=%s: %s",
            len(delays), recipient_phone, patient_id, alert_type, last_error,
        )
        await self._log(patient_id, alert_type, recipient_phone, "failed", last_error)
        return {"phone": recipient_phone, "status": "failed", "error": last_error}

    def _twilio_send(self, to_number: str, body: str) -> None:
        """Blocking Twilio API call — runs in executor thread."""
        from twilio.rest import Client
        client = Client(self._account_sid, self._auth_token)
        client.messages.create(from_=self._from_number, to=to_number, body=body)

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
