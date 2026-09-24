"""
api/patient_route.py
─────────────────────
Convenience shorthand routes matching the spec:
  GET /patient       → returns the currently monitored patient
                       (driven by ecg_service.active_patient_id, not P-001)
  GET /device        → live device status
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.security import TokenData, get_current_user
from app.database.database import get_db
from app.database import crud
from app.database.schemas import PatientResponse
from app.services.ecg_service import ecg_service

router = APIRouter(tags=["Dashboard"])


@router.get("/patient", response_model=PatientResponse, summary="Get active patient")
async def get_active_patient(
    db: AsyncSession = Depends(get_db),
    _: TokenData     = Depends(get_current_user),
):
    """
    Return the currently monitored patient record.

    The active patient is determined by the ECG service's runtime state,
    not a hardcoded ID.  Returns 404 when no patient is selected yet.
    """
    patient_id = ecg_service.active_patient_id
    if not patient_id:
        raise NotFoundError("No active patient — select a patient first.")
    patient = await crud.get_patient(db, patient_id)
    if not patient:
        raise NotFoundError(f"Active patient '{patient_id}' not found in database.")
    return patient


@router.get("/device", summary="Get live device status")
async def get_device_status(_: TokenData = Depends(get_current_user)):
    """Return current device connection and signal quality status."""
    quality = ecg_service.current_quality
    return {
        "connected":          ecg_service.is_connected,
        "sampling_rate":      "250 Hz",
        "signal_quality":     quality.score if quality else 90,
        "signal_label":       quality.label if quality else "Good",
        "monitoring_duration": None,     # computed by frontend timer
        "status":             "Active" if ecg_service.is_monitoring else "Idle",
        "session_id":         ecg_service.session_id,
        "active_patient_id":  ecg_service.active_patient_id,
    }
