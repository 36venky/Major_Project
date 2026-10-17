"""
api/ecg.py
───────────
ECG data endpoints.

GET  /ecg/live              – current ECG window + live metrics
GET  /ecg/history           – list all sessions for active patient
GET  /ecg/session/{id}      – get session detail + sample count
POST /ecg/start             – open a DB session and start recording
POST /ecg/stop              – flush + close the session, stop recording
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenData, get_current_user
from app.database.database import get_db
from app.database import crud
from app.database.schemas import ECGSessionResponse
from app.services.ecg_service import ecg_service

router = APIRouter(prefix="/ecg", tags=["ECG"])


@router.get("/live", summary="Get live ECG window and current metrics")
async def get_live_ecg(
    n: int = Query(default=250, ge=10, le=2000, description="Number of samples to return"),
    _: TokenData = Depends(get_current_user),
):
    """
    Return the latest N raw ECG samples and current monitoring metrics.

    Useful for REST polling fallback when WebSocket is not available.
    """
    quality    = ecg_service.current_quality
    arrhythmia = ecg_service.current_arrhythmia

    return {
        "samples":       ecg_service.get_live_ecg_window(n),
        "bpm":           ecg_service.current_bpm,
        "session_id":    ecg_service.session_id,
        "is_monitoring": ecg_service.is_monitoring,
        "is_recording":  ecg_service.is_recording,
        "quality": {
            "score": quality.score if quality else 90,
            "label": quality.label if quality else "Good",
        },
        "analysis": {
            "rhythm":     arrhythmia.rhythm      if arrhythmia else "Normal Sinus Rhythm",
            "confidence": arrhythmia.confidence  if arrhythmia else 95,
            "risk_level": arrhythmia.risk_level  if arrhythmia else "Low",
        } if arrhythmia else None,
    }


@router.post("/start", summary="Start recording — open a new ECG session in the DB")
async def start_recording(
    _: TokenData = Depends(get_current_user),
):
    """
    Called when the user clicks **Start** on the dashboard.

    Hardware data must already be streaming (ESP32 connected).
    Opens a new DB session and enables data storage + the analysis pipeline.

    Returns 200 on success or 409 if already recording / no hardware.
    """
    from fastapi import HTTPException, status as http_status
    result = await ecg_service.start_monitoring()
    if not result["success"]:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=result["message"],
        )
    return result


@router.post("/stop", summary="Stop recording — flush and close the active ECG session")
async def stop_recording(
    _: TokenData = Depends(get_current_user),
):
    """
    Called when the user clicks **Stop** on the dashboard.

    Flushes any pending samples to the DB, closes the active session,
    and disables the storage + analysis pipeline.
    Hardware data continues streaming to the frontend for live preview.
    """
    result = await ecg_service.stop_monitoring()
    return result


@router.get("/history", response_model=List[ECGSessionResponse], summary="List past ECG sessions")
async def get_history(
    patient_id: str = Query(default=None, description="Patient ID (defaults to active patient)"),
    limit:      int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    """Return the most recent ECG sessions for a patient, newest first."""
    resolved_patient_id = patient_id or ecg_service.active_patient_id or "P-001"
    return await crud.get_sessions_for_patient(db, resolved_patient_id, limit)


@router.get("/session/{session_id}", response_model=ECGSessionResponse, summary="Get session detail")
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    """Fetch a single ECG session record by ID."""
    from app.core.exceptions import NotFoundError
    session = await crud.get_session(db, session_id)
    if not session:
        raise NotFoundError(f"Session '{session_id}' not found.")
    return session


@router.post("/test-alert", summary="Trigger a test alert through the full pipeline (dev/debug)")
async def test_alert(
    body: dict,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    """
    Inject a synthetic HIGH_HR alert through the full pipeline:
    DB persist + WhatsApp dispatch (if Twilio is configured).

    Used by the DeviceTestPanel in the frontend when no hardware is connected.
    Does NOT require an active recording session.
    """
    from app.alerts.alert_engine import AlertEvent
    from app.services.twilio_service import whatsapp_service
    from datetime import datetime, timezone

    patient_id = body.get("patient_id") or ecg_service.active_patient_id or "P-001"

    patient = await crud.get_patient(db, patient_id)
    if not patient:
        from fastapi import HTTPException, status as http_status
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Patient '{patient_id}' not found.",
        )

    # Persist a synthetic alert to DB
    await crud.create_alert(
        db,
        patient_id=patient_id,
        alert_type="HIGH_HR",
        severity="warning",
        message="Test alert: simulated high heart rate (165 BPM) via DeviceTestPanel.",
    )
    await db.commit()

    # Dispatch WhatsApp if configured (non-blocking)
    event_ts = datetime.now(timezone.utc)
    whatsapp_service.dispatch(
        patient_id=patient_id,
        patient_name=patient.name,
        guardian_phone=patient.guardian_phone,
        emergency_contact=patient.emergency_contact,
        phone=patient.phone,
        doctor_phone=getattr(patient, "doctor_phone", None),
        ambulance_phone=getattr(patient, "ambulance_phone", None),
        maps_link=getattr(patient, "maps_link", None),
        alert_type="HIGH_HR",
        severity="warning",
        ecg_status="Simulated 165 BPM",
        risk_level="High",
        alert_message="Test alert: simulated high heart rate (165 BPM) via DeviceTestPanel.",
        timestamp=event_ts,
    )

    return {
        "success":    True,
        "message":    (
            f"Test alert triggered for patient {patient_id}. "
            + ("WhatsApp dispatched." if whatsapp_service._enabled
               else "WhatsApp disabled — set Twilio credentials in .env to enable.")
        ),
        "session_id": ecg_service.session_id,
    }
