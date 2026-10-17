"""
api/alerts.py
──────────────
Alert management endpoints.

GET  /alerts                        – list alerts for a patient
POST /alerts/{id}/resolve           – mark alert as resolved
POST /alerts/send-report            – manually send WhatsApp status report
GET  /alerts/cooldowns              – inspect current WhatsApp cooldown state (admin)
DELETE /alerts/cooldowns            – reset all WhatsApp cooldowns (admin)
DELETE /alerts/cooldowns/{patient_id}/{alert_type} – reset one specific cooldown (admin)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.security import TokenData, get_current_user, require_admin
from app.database import crud
from app.database.database import get_db
from app.database.schemas import AlertResponse, APIResponse
from app.services.ecg_service import ecg_service

router = APIRouter(prefix="/alerts", tags=["Alerts"])


@router.get("", response_model=List[AlertResponse], summary="List alerts")
async def list_alerts(
    patient_id: str   = Query(default=None, description="Patient ID (defaults to active patient)"),
    resolved:   Optional[bool] = Query(default=None, description="Filter by resolved status"),
    limit:      int   = Query(default=50, ge=1, le=200),
    db: AsyncSession  = Depends(get_db),
    _: TokenData      = Depends(get_current_user),
):
    """
    Return alerts for a patient.

    Args:
        patient_id: Patient identifier (defaults to currently active patient).
        resolved:   If True, return only resolved alerts.
                    If False, return only active alerts.
                    If None (default), return all alerts.
        limit:      Maximum number of records to return.
    """
    resolved_patient_id = patient_id or ecg_service.active_patient_id or "P-001"
    return await crud.get_alerts(db, resolved_patient_id, resolved=resolved, limit=limit)


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


class SendReportRequest(BaseModel):
    patient_id: Optional[str] = None   # defaults to active patient if omitted


@router.post("/send-report", response_model=APIResponse, summary="Send manual WhatsApp status report")
async def send_whatsapp_report(
    body: SendReportRequest,
    db: AsyncSession = Depends(get_db),
    _: TokenData     = Depends(get_current_user),
):
    """
    Manually send a WhatsApp status report to the patient's guardian.

    Includes current ECG status, BPM, risk level, and signal quality.
    """
    from app.services.twilio_service import whatsapp_service, e164

    if not whatsapp_service._enabled:
        raise NotFoundError("WhatsApp service is not configured (check Twilio credentials in .env).")

    resolved_patient_id = body.patient_id or ecg_service.active_patient_id or "P-001"
    patient = await crud.get_patient(db, resolved_patient_id)
    if not patient:
        raise NotFoundError(f"Patient '{resolved_patient_id}' not found.")

    if not patient.guardian_phone:
        raise NotFoundError(f"No guardian phone number set for patient '{body.patient_id}'.")

    # Gather live values from the ECG service
    bpm          = int(ecg_service.current_bpm) if ecg_service.current_bpm > 0 else "—"
    arrhythmia   = ecg_service.current_arrhythmia
    quality      = ecg_service.current_quality
    risk         = ecg_service.current_risk
    session_id   = ecg_service.session_id

    rhythm       = arrhythmia.rhythm     if arrhythmia else "Analysing…"
    risk_level   = arrhythmia.risk_level if arrhythmia else "Unknown"
    quality_pct  = quality.score         if quality    else "—"
    quality_lbl  = quality.label         if quality    else "—"

    # Risk prediction from ML model (if available)
    risk_pct_str = ""
    if risk and risk.get("risk_percentage") is not None:
        risk_pct_str = f"\n*ML Risk Score:* {risk['risk_percentage']:.1f}%"

    ts_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    body_text = (
        f"📊 *ECG Guardian – Status Report*\n\n"
        f"*Patient:* {patient.name}\n"
        f"*Time:* {ts_str}\n"
        f"*Session:* {session_id or '—'}\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"*❤️ Heart Rate:* {bpm} BPM\n"
        f"*🫀 Rhythm:* {rhythm}\n"
        f"*⚠️ Risk Level:* {risk_level}"
        f"{risk_pct_str}\n"
        f"*📶 Signal Quality:* {quality_lbl} ({quality_pct}%)\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"_Sent manually via ECG Guardian_"
    )

    to_number = f"whatsapp:{e164(patient.guardian_phone)}"

    account_sid = whatsapp_service._account_sid
    auth_token  = whatsapp_service._auth_token
    from_number = whatsapp_service._from_number

    import asyncio

    def _do_send():
        from twilio.rest import Client
        Client(account_sid, auth_token).messages.create(
            from_=from_number,
            to=to_number,
            body=body_text,
        )

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _do_send)

    return APIResponse(message=f"Status report sent to {patient.guardian_phone}.")


# ── WhatsApp cooldown inspection / management (admin only) ────────────────────

@router.get(
    "/cooldowns",
    response_model=List[dict],
    summary="Inspect WhatsApp cooldown state (admin)",
    tags=["Alerts"],
)
async def get_cooldown_status(
    _: TokenData = Depends(require_admin),
):
    """
    Return the current WhatsApp cooldown state for every
    (patient_id, alert_type) pair.

    Shows which alert types are still on cooldown and how many seconds remain.
    Requires admin role.
    """
    from app.services.twilio_service import whatsapp_service
    return whatsapp_service.cooldown_status()


@router.delete(
    "/cooldowns",
    response_model=APIResponse,
    summary="Reset ALL WhatsApp cooldowns (admin)",
    tags=["Alerts"],
)
async def reset_all_cooldowns(
    _: TokenData = Depends(require_admin),
):
    """
    Clear every WhatsApp cooldown entry so the next qualifying alert
    will send immediately.  Use after testing or after a configuration change.
    Requires admin role.
    """
    from app.services.twilio_service import whatsapp_service
    count = whatsapp_service.reset_cooldown()
    return APIResponse(message=f"All WhatsApp cooldowns cleared ({count} entries removed).")


@router.delete(
    "/cooldowns/{patient_id}/{alert_type}",
    response_model=APIResponse,
    summary="Reset one specific WhatsApp cooldown (admin)",
    tags=["Alerts"],
)
async def reset_single_cooldown(
    patient_id: str,
    alert_type: str,
    _: TokenData = Depends(require_admin),
):
    """
    Clear the cooldown for a specific patient + alert_type combination.
    The next matching alert will be dispatched immediately.
    Requires admin role.
    """
    from app.services.twilio_service import whatsapp_service
    count = whatsapp_service.reset_cooldown(patient_id=patient_id, alert_type=alert_type)
    if count == 0:
        raise NotFoundError(
            f"No active cooldown found for patient='{patient_id}' type='{alert_type}'."
        )
    return APIResponse(
        message=f"Cooldown cleared for patient={patient_id} type={alert_type}."
    )
