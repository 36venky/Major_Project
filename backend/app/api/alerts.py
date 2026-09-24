"""
api/alerts.py
──────────────
Alert management endpoints.

GET  /alerts                  – list alerts for a patient
POST /alerts/{id}/resolve     – mark alert as resolved
POST /alerts/send-report      – manually send WhatsApp status report to ALL
                                three contact numbers (guardian, doctor, ambulance)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.security import TokenData, get_current_user
from app.database import crud
from app.database.database import AsyncSessionLocal, get_db
from app.database.schemas import AlertResponse, APIResponse
from app.services.ecg_service import ecg_service

router = APIRouter(prefix="/alerts", tags=["Alerts"])


@router.get("", response_model=List[AlertResponse], summary="List alerts")
async def list_alerts(
    patient_id: str            = Query(..., description="Patient ID (required)"),
    resolved:   Optional[bool] = Query(default=None, description="Filter by resolved status"),
    limit:      int            = Query(default=50, ge=1, le=200),
    db: AsyncSession           = Depends(get_db),
    _: TokenData               = Depends(get_current_user),
):
    """Return alerts for a patient, newest first."""
    return await crud.get_alerts(db, patient_id, resolved=resolved, limit=limit)


@router.post("/{alert_id}/resolve", response_model=AlertResponse, summary="Resolve an alert")
async def resolve_alert(
    alert_id: int,
    db: AsyncSession = Depends(get_db),
    _: TokenData     = Depends(get_current_user),
):
    """Mark an alert as resolved and record the resolution time."""
    alert = await crud.resolve_alert(db, alert_id)
    if not alert:
        raise NotFoundError(f"Alert {alert_id} not found.")
    await db.commit()
    return alert


# ── Manual status report ──────────────────────────────────

class SendReportRequest(BaseModel):
    patient_id: str  # required — no default


class SendReportResponse(BaseModel):
    success:    bool
    message:    str
    recipients: List[dict]   # [{"phone", "role", "status": "sent"|"failed"}]


@router.post(
    "/send-report",
    response_model=SendReportResponse,
    summary="Send manual WhatsApp status report to all contacts",
)
async def send_whatsapp_report(
    body: SendReportRequest,
    db: AsyncSession = Depends(get_db),
    _: TokenData     = Depends(get_current_user),
):
    """
    Broadcast a WhatsApp status report to all three patient contact numbers:
      1. guardian_phone  — primary guardian / family member
      2. doctor_phone    — treating physician
      3. ambulance_phone — ambulance / emergency service

    Each number is sent to concurrently; each send uses its own DB session
    so there are no concurrent-flush conflicts on the asyncpg connection.
    """
    from app.services.twilio_service import whatsapp_service, e164

    if not whatsapp_service._enabled:
        raise NotFoundError(
            "WhatsApp service is not configured. "
            "Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_FROM in .env."
        )

    patient = await crud.get_patient(db, body.patient_id)
    if not patient:
        raise NotFoundError(f"Patient '{body.patient_id}' not found.")

    # ── Collect and deduplicate the three target numbers ──
    contacts = [
        ("guardian",  getattr(patient, "guardian_phone",  None)),
        ("doctor",    getattr(patient, "doctor_phone",    None)),
        ("ambulance", getattr(patient, "ambulance_phone", None)),
    ]
    seen: set[str] = set()
    targets: list[tuple[str, str]] = []
    for role, raw in contacts:
        if not raw:
            continue
        norm = e164(raw.strip())
        if norm and norm not in seen:
            seen.add(norm)
            targets.append((role, norm))

    if not targets:
        raise NotFoundError(
            f"No contact phone numbers set for patient '{body.patient_id}'. "
            "Add guardian_phone, doctor_phone, or ambulance_phone in the patient profile."
        )

    # ── Snapshot live monitoring values (read-only, no DB needed) ────────
    bpm        = ecg_service.current_bpm
    arrhythmia = ecg_service.current_arrhythmia
    quality    = ecg_service.current_quality
    risk       = ecg_service.current_risk
    session_id = ecg_service.session_id

    bpm_str     = f"{int(bpm)} BPM" if bpm > 0 else "— (no reading yet)"
    rhythm      = arrhythmia.rhythm     if arrhythmia else "Analysing…"
    risk_level  = arrhythmia.risk_level if arrhythmia else "Unknown"
    quality_pct = quality.score         if quality    else "—"
    quality_lbl = quality.label         if quality    else "—"

    ml_line = ""
    if risk and risk.get("risk_percentage") is not None:
        ml_line = (
            f"\n*🤖 ML Risk Score:* {risk['risk_percentage']:.1f}%"
            f" ({risk.get('risk_level', '—')})"
        )

    maps = getattr(patient, "maps_link", None)
    location_line = f"\n\n📍 *Patient Location:*\n{maps}" if maps else ""

    ts_str = datetime.now(timezone.utc).strftime("%d %b %Y, %I:%M %p UTC")

    role_labels = {
        "guardian":  "🧑‍👧 Guardian / Family",
        "doctor":    "👨‍⚕️ Doctor",
        "ambulance": "🚑 Ambulance Service",
    }

    # Capture Twilio credentials before the concurrent section
    account_sid  = whatsapp_service._account_sid
    auth_token   = whatsapp_service._auth_token
    from_number  = whatsapp_service._from_number
    patient_id   = patient.patient_id
    patient_name = patient.name

    # ── Per-recipient coroutine ───────────────────────────────────────────
    # IMPORTANT: each coroutine opens its OWN AsyncSessionLocal session.
    # Sharing the injected `db` session across concurrent coroutines causes
    # "Session is already flushing" / "another operation is in progress" on
    # asyncpg because a single connection cannot handle parallel operations.
    async def _send_one(role: str, norm_phone: str) -> dict:
        greeting = role_labels.get(role, role.title())
        message_body = (
            f"📊 *ECG Guardian – Live Status Report*\n"
            f"_Sent to: {greeting}_\n\n"
            f"*Patient:* {patient_name}  (ID: {patient_id})\n"
            f"*Time:* {ts_str}\n"
            f"*Session:* {session_id or '—'}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"*❤️ Heart Rate:* {bpm_str}\n"
            f"*🫀 Rhythm:* {rhythm}\n"
            f"*⚠️ Risk Level:* {risk_level}"
            f"{ml_line}\n"
            f"*📶 Signal Quality:* {quality_lbl} ({quality_pct}%)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━"
            f"{location_line}\n\n"
            f"_Manually triggered via ECG Guardian dashboard_"
        )
        to_number = f"whatsapp:{norm_phone}"

        # ── Twilio send ───────────────────────────────────
        send_ok    = False
        send_error: str | None = None
        try:
            loop = asyncio.get_event_loop()

            def _do_send():
                from twilio.rest import Client
                Client(account_sid, auth_token).messages.create(
                    from_=from_number, to=to_number, body=message_body,
                )

            await loop.run_in_executor(None, _do_send)
            send_ok = True
        except Exception as exc:
            send_error = str(exc)

        # ── Logging — own session, own transaction ────────
        try:
            async with AsyncSessionLocal() as own_db:
                await crud.create_alert_log(
                    own_db,
                    patient_id=patient_id,
                    alert_type="MANUAL_STATUS_REPORT",
                    recipient=norm_phone,
                    status="sent" if send_ok else "failed",
                    error_message=send_error,
                )
                await own_db.commit()
        except Exception as log_exc:
            # Logging failure must never mask the send result
            pass

        if send_ok:
            return {"phone": norm_phone, "role": role, "status": "sent"}
        return {"phone": norm_phone, "role": role, "status": "failed", "error": send_error}

    # ── Run all sends concurrently ────────────────────────
    results = await asyncio.gather(*[_send_one(r, p) for r, p in targets])

    sent_count   = sum(1 for r in results if r["status"] == "sent")
    failed_count = len(results) - sent_count

    if sent_count == 0:
        msg = f"All {failed_count} send(s) failed. Check Twilio credentials and phone numbers."
    elif failed_count == 0:
        msg = f"Status report delivered to all {sent_count} contact(s) successfully."
    else:
        msg = f"Sent to {sent_count} contact(s); {failed_count} failed."

    return SendReportResponse(
        success    = sent_count > 0,
        message    = msg,
        recipients = list(results),
    )
