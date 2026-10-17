"""
api/patient_route.py
─────────────────────
Convenience shorthand routes matching the spec:
  GET /patient       → active patient (from ECGService, falls back to P-001)
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


@router.get("/patient", response_model=PatientResponse, summary="Get active patient")
async def get_active_patient(
    db: AsyncSession = Depends(get_db),
    _: TokenData     = Depends(get_current_user),
):
    """Return the currently monitored patient record."""
    from app.core.exceptions import NotFoundError
    patient_id = ecg_service.active_patient_id or "P-001"
    patient = await crud.get_patient(db, patient_id)
    if not patient:
        raise NotFoundError("Active patient not configured.")
    return patient


@router.get("/device", summary="Get live device status")
async def get_device_status(_: TokenData = Depends(get_current_user)):
    """Return current device connection and signal quality status."""
    from app.core.config import settings as _settings
    quality = ecg_service.current_quality
    is_hw   = ecg_service.is_connected   # True = real ESP32 over WiFi, False = not connected
    return {
        "connected":          is_hw,
        "hardware_connected": is_hw,
        "connection_type":    "WiFi (ESP32 WebSocket)" if is_hw else "Not connected",
        "port":               None,                         # no COM port — WiFi only
        "sampling_rate":      f"{_settings.SAMPLING_RATE} Hz",
        "signal_quality":     quality.score if quality else 90,
        "signal_label":       quality.label if quality else "Good",
        "monitoring_duration": None,          # computed by frontend timer
        "status":             "Active" if ecg_service.is_monitoring else "Idle",
        "session_id":         ecg_service.session_id,
    }
