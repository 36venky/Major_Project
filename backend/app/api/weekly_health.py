"""
api/weekly_health.py
─────────────────────
Weekly health record endpoints (manual patient/guardian updates).

GET  /weekly-health       – latest health record for patient (returns empty default instead of 404)
POST /weekly-health       – upsert: update today's record or create new one
PUT  /weekly-health/{id}  – update existing health entry by ID
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.security import TokenData, get_current_user
from app.database import crud
from app.database.database import get_db
from app.database.schemas import (
    WeeklyHealthCreate, WeeklyHealthResponse, WeeklyHealthUpdate,
)
from app.services.ecg_service import ecg_service

router = APIRouter(prefix="/weekly-health", tags=["Weekly Health"])


def _empty_health(patient_id: str) -> dict:
    """Return an empty weekly health payload so the frontend never gets a 404."""
    return {
        "id":             0,
        "patient_id":     patient_id,
        "date":           datetime.now(timezone.utc).isoformat(),
        "blood_pressure": None,
        "blood_sugar":    None,
        "weight":         None,
        "notes":          None,
        "updated_by":     None,
    }


@router.get("", summary="Get latest health record")
async def get_weekly_health(
    patient_id: str  = Query(default=None, description="Patient ID (defaults to active patient)"),
    db: AsyncSession = Depends(get_db),
    _: TokenData     = Depends(get_current_user),
):
    """
    Return the most recently updated weekly health record for a patient.

    Instead of raising 404 when no records exist (which broke the frontend),
    returns an empty placeholder so components can render gracefully.
    """
    resolved_patient_id = patient_id or ecg_service.active_patient_id or "P-001"
    record = await crud.get_latest_weekly_health(db, resolved_patient_id)
    if not record:
        # Return a zero-state dict — no DB row created yet
        return _empty_health(resolved_patient_id)
    return record


@router.post(
    "",
    response_model=WeeklyHealthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit or update weekly health entry (upsert)",
)
async def create_weekly_health(
    body: WeeklyHealthCreate,
    db: AsyncSession = Depends(get_db),
    _: TokenData     = Depends(get_current_user),
):
    """
    Upsert a weekly health entry for a patient.

    • If a record already exists for today, it is updated in place.
    • Otherwise a new record is created.

    This is the endpoint called by the Settings page 'Save Health Data' button.
    """
    # Check if we already have a record created today for this patient
    existing = await crud.get_latest_weekly_health(db, body.patient_id)

    today = datetime.now(timezone.utc).date()
    if existing:
        record_date = existing.date
        # record.date may be a datetime (with or without tzinfo) or a bare date
        if hasattr(record_date, "date") and callable(record_date.date):
            record_date = record_date.date()
        # record_date is now a date object

        if record_date == today:
            # Update today's record rather than creating a duplicate
            update_data = body.model_dump(exclude={"patient_id"}, exclude_none=True)
            updated = await crud.update_weekly_health(db, existing.id, update_data)
            await db.commit()
            # Return 200 (not 201) for an update — but FastAPI status_code is per-endpoint;
            # returning the object is enough for the frontend which only checks success.
            return updated

    # No record today — create a fresh one
    record = await crud.create_weekly_health(db, body.model_dump())
    await db.commit()
    return record


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
    await db.commit()
    return record
