"""
api/heart_rate.py
──────────────────
Heart rate endpoints.

GET /bpm/live     – current BPM and status
GET /bpm/history  – time-series BPM for a patient
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import TokenData, get_current_user
from app.database import crud
from app.database.database import get_db
from app.database.schemas import HeartRateResponse
from app.services.ecg_service import ecg_service

router = APIRouter(prefix="/bpm", tags=["Heart Rate"])


@router.get("/live", summary="Get current live heart rate")
async def get_live_bpm(
    _: TokenData = Depends(get_current_user),
):
    """
    Return the most recent BPM estimate from the ECG pipeline.

    Status:
      - Normal      : settings.HR_LOW – settings.HR_HIGH
      - Tachycardia : > settings.HR_HIGH
      - Bradycardia : < settings.HR_LOW
    """
    bpm = ecg_service.current_bpm
    if bpm >= settings.HR_HIGH:
        status = "Tachycardia"
    elif bpm <= settings.HR_LOW and bpm > 0:
        status = "Bradycardia"
    else:
        status = "Normal"

    return {
        "bpm":          int(bpm),
        "status":       status,
        "normal_range": f"{settings.HR_LOW}–{settings.HR_HIGH} BPM",
        "session_id":   ecg_service.session_id,
    }


@router.get("/history", response_model=List[HeartRateResponse], summary="BPM history")
async def get_bpm_history(
    patient_id: str = Query(..., description="Patient ID (required)"),
    limit:      int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    """Return time-series BPM records for a patient, newest first."""
    return await crud.get_heart_rate_history(db, patient_id, limit)
