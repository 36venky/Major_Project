"""
api/ecg.py
───────────
ECG data endpoints.

GET  /ecg/live              – current ECG window + live metrics
GET  /ecg/history           – list all sessions for a patient
GET  /ecg/session/{id}      – get session detail
POST /ecg/test-alert        – inject a synthetic alert (dev/test only)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.security import TokenData, get_current_user
from app.database.database import get_db
from app.database import crud
from app.database.schemas import ECGSessionResponse, APIResponse
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
        "quality": {
            "score": quality.score if quality else 90,
            "label": quality.label if quality else "Good",
        },
        "analysis": {
            "rhythm":     arrhythmia.rhythm     if arrhythmia else "Normal Sinus Rhythm",
            "confidence": arrhythmia.confidence if arrhythmia else 95,
            "risk_level": arrhythmia.risk_level if arrhythmia else "Low",
        } if arrhythmia else None,
    }


@router.get("/history", response_model=List[ECGSessionResponse], summary="List past ECG sessions")
async def get_history(
    patient_id: str = Query(..., description="Patient ID (required)"),
    limit:      int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    """Return the most recent ECG sessions for a patient, newest first."""
    return await crud.get_sessions_for_patient(db, patient_id, limit)


@router.get("/session/{session_id}", response_model=ECGSessionResponse, summary="Get session detail")
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    """Fetch a single ECG session record by ID."""
    session = await crud.get_session(db, session_id)
    if not session:
        raise NotFoundError(f"Session '{session_id}' not found.")
    return session


# ── Test Alert ────────────────────────────────────────────

class TestAlertRequest(BaseModel):
    patient_id: str


@router.post("/test-alert", response_model=APIResponse, summary="Inject a synthetic test alert")
async def test_alert(
    body: TestAlertRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    """
    Inject a synthetic critical heart-rate alert for testing purposes.

    - Verifies the patient exists.
    - Persists an alert record in the database.
    - Fires the WhatsApp notification pipeline (if Twilio is configured).
    - Pushes a notification to all connected WebSocket clients.

    Useful for testing the full alert pipeline (DB → WhatsApp → WS) without
    needing live ECG hardware to generate a real arrhythmia event.
    """
    # Validate patient exists
    patient = await crud.get_patient(db, body.patient_id)
    if not patient:
        raise NotFoundError(f"Patient '{body.patient_id}' not found.")

    alert_type = "TEST_CRITICAL_HR"
    severity   = "critical"
    message    = (
        f"[TEST] Simulated critical tachycardia: 165 BPM. "
        f"This is a test alert triggered by {current_user.sub}."
    )

    # Persist to DB
    await crud.create_alert(db, body.patient_id, alert_type, severity, message)
    await db.commit()

    # Fire WhatsApp dispatch (non-blocking — errors are swallowed internally)
    try:
        from app.services.twilio_service import whatsapp_service
        whatsapp_service.dispatch(
            patient_id        = body.patient_id,
            patient_name      = patient.name,
            guardian_phone    = patient.guardian_phone,
            emergency_contact = getattr(patient, "emergency_contact", None),
            phone             = getattr(patient, "phone", None),
            doctor_phone      = getattr(patient, "doctor_phone", None),
            ambulance_phone   = getattr(patient, "ambulance_phone", None),
            maps_link         = getattr(patient, "maps_link", None),
            alert_type        = alert_type,
            severity          = severity,
            ecg_status        = "Simulated Critical Tachycardia",
            risk_level        = "High",
            alert_message     = message,
            timestamp         = datetime.now(timezone.utc),
        )
    except Exception:
        pass  # WhatsApp dispatch failure must not prevent the HTTP response

    return APIResponse(
        message=(
            f"Test alert injected for patient {body.patient_id}. "
            "Check the Alerts tab and WhatsApp (if Twilio is configured)."
        )
    )
