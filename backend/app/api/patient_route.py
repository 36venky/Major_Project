"""
api/patient_route.py
─────────────────────
Convenience shorthand routes matching the spec:
  GET /patient       → same as GET /patients/P-001 (active patient)
  GET /device        → live device status
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenData, get_current_user
from app.database.database import get_db
from app.database import crud
from app.database.schemas import PatientResponse
from app.services.ecg_service import ecg_service

router = APIRouter(tags=["Dashboard"])

_DEFAULT_PATIENT = "P-001"


@router.get("/patient", response_model=PatientResponse, summary="Get active patient")
async def get_active_patient(
    db: AsyncSession = Depends(get_db),
    _: TokenData     = Depends(get_current_user),
):
    """Return the currently monitored patient record."""
    from app.core.exceptions import NotFoundError
    patient = await crud.get_patient(db, _DEFAULT_PATIENT)
    if not patient:
        raise NotFoundError("Active patient not configured.")
    return patient


@router.get("/device", summary="Get live device status")
async def get_device_status(_: TokenData = Depends(get_current_user)):
    """Return current device connection and signal quality status."""
    quality = ecg_service.current_quality
    return {
        "connected":     ecg_service.is_connected,
        "port":          "COM6",
        "sampling_rate": "250 Hz",
        "signal_quality": quality.score if quality else 90,
        "signal_label":   quality.label if quality else "Good",
        "monitoring_duration": None,     # computed by frontend timer
        "status":        "Active" if ecg_service.is_monitoring else "Idle",
        "session_id":    ecg_service.session_id,
    }
