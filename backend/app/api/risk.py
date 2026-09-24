"""
api/risk.py
────────────
Risk prediction endpoints (Feature 5).

GET /patients/{patient_id}/risk          – latest prediction
GET /patients/{patient_id}/risk/history  – last 30 days
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenData, get_current_user
from app.database.database import get_db
from app.database import crud
from app.database.schemas import RiskPredictionResponse

router = APIRouter(tags=["Risk Prediction"])


@router.get(
    "/patients/{patient_id}/risk",
    response_model=RiskPredictionResponse,
    summary="Latest risk prediction for a patient",
)
async def get_latest_risk(
    patient_id: str,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    """Return the most recent risk prediction row. 404 if patient or data not found."""
    patient = await crud.get_patient(db, patient_id)
    if not patient:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found.")
    record = await crud.get_latest_risk_prediction(db, patient_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No predictions yet.")
    return record


@router.get(
    "/patients/{patient_id}/risk/history",
    response_model=List[RiskPredictionResponse],
    summary="Risk prediction history (last 30 days)",
)
async def get_risk_history(
    patient_id: str,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    """Return all predictions for a patient within the last 30 days."""
    patient = await crud.get_patient(db, patient_id)
    if not patient:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found.")
    return await crud.get_risk_prediction_history(db, patient_id, days=30)
