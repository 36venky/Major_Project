"""
api/ecg.py
───────────
ECG data endpoints.

GET /ecg/live              – current ECG window + live metrics
GET /ecg/history           – list all sessions for active patient
GET /ecg/session/{id}      – get session detail + sample count
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

_DEFAULT_PATIENT = "P-001"


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
        "samples":    ecg_service.get_live_ecg_window(n),
        "bpm":        ecg_service.current_bpm,
        "session_id": ecg_service.session_id,
        "is_monitoring": ecg_service.is_monitoring,
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


@router.get("/history", response_model=List[ECGSessionResponse], summary="List past ECG sessions")
async def get_history(
    patient_id: str = Query(default=_DEFAULT_PATIENT),
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
    from app.core.exceptions import NotFoundError
    session = await crud.get_session(db, session_id)
    if not session:
        raise NotFoundError(f"Session '{session_id}' not found.")
    return session
