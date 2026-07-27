"""
api/alerts.py
──────────────
Alert management endpoints.

GET  /alerts                  – list alerts for a patient
POST /alerts/{id}/resolve     – mark alert as resolved
POST /alerts/send-report      – manually send WhatsApp status report
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.security import TokenData, get_current_user
from app.database import crud
from app.database.database import get_db
from app.database.schemas import AlertResponse, APIResponse
from app.services.ecg_service import ecg_service

router = APIRouter(prefix="/alerts", tags=["Alerts"])

_DEFAULT_PATIENT = "P-001"


@router.get("", response_model=List[AlertResponse], summary="List alerts")
async def list_alerts(
    patient_id: str   = Query(default=_DEFAULT_PATIENT),
    resolved:   Optional[bool] = Query(default=None, description="Filter by resolved status"),
    limit:      int   = Query(default=50, ge=1, le=200),
    db: AsyncSession  = Depends(get_db),
    _: TokenData      = Depends(get_current_user),
):
    """
    Return alerts for a patient.

    Args:
        patient_id: Patient identifier.
        resolved:   If True, return only resolved alerts.
                    If False, return only active alerts.
                    If None (default), return all alerts.
        limit:      Maximum number of records to return.
    """
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


class SendReportRequest(BaseModel):
    patient_id: str = _DEFAULT_PATIENT


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

    patient = await crud.get_patient(db, body.patient_id)
    if not patient:
        raise NotFoundError(f"Patient '{body.patient_id}' not found.")

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
