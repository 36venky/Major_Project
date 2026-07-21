"""
api/weekly_health.py
─────────────────────
Weekly health record endpoints (manual patient/guardian updates).

GET  /weekly-health       – latest health record for patient
POST /weekly-health       – create new health entry
PUT  /weekly-health/{id}  – update existing health entry
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.security import TokenData, get_current_user
from app.database import crud
from app.database.database import get_db
from app.database.schemas import (
    WeeklyHealthCreate, WeeklyHealthResponse, WeeklyHealthUpdate,
)

router = APIRouter(prefix="/weekly-health", tags=["Weekly Health"])


@router.get("", response_model=WeeklyHealthResponse, summary="Get latest health record")
async def get_weekly_health(
    patient_id: str  = "P-001",
    db: AsyncSession = Depends(get_db),
    _: TokenData     = Depends(get_current_user),
):
    """Return the most recently updated weekly health record for a patient."""
    record = await crud.get_latest_weekly_health(db, patient_id)
    if not record:
        raise NotFoundError("No weekly health records found for this patient.")
    return record


@router.post(
    "",
    response_model=WeeklyHealthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a new weekly health entry",
)
async def create_weekly_health(
    body: WeeklyHealthCreate,
    db: AsyncSession = Depends(get_db),
    _: TokenData     = Depends(get_current_user),
):
    """
    Create a new weekly health entry for a patient.

    Typically submitted by the patient or guardian after a clinic visit.
    """
    return await crud.create_weekly_health(db, body.model_dump())


@router.put("/{record_id}", response_model=WeeklyHealthResponse, summary="Update health record")
async def update_weekly_health(
    record_id: int,
    body: WeeklyHealthUpdate,
    db: AsyncSession = Depends(get_db),
    _: TokenData     = Depends(get_current_user),
):
    """Update an existing weekly health record by ID."""
    record = await crud.update_weekly_health(db, record_id, body.model_dump(exclude_none=True))
    if not record:
        raise NotFoundError(f"Weekly health record {record_id} not found.")
    return record
