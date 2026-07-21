"""
api/alerts.py
──────────────
Alert management endpoints.

GET  /alerts               – list alerts for a patient
POST /alerts/{id}/resolve  – mark alert as resolved
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.security import TokenData, get_current_user
from app.database import crud
from app.database.database import get_db
from app.database.schemas import AlertResponse, APIResponse

router = APIRouter(prefix="/alerts", tags=["Alerts"])

_DEFAULT_PATIENT = "P-001"


@router.get("", response_model=List[AlertResponse], summary="List alerts")
async def list_alerts(
    patient_id: str   = Query(default=_DEFAULT_PATIENT),
    resolved:   Optional[bool] = Query(default=None, description="Filter by resolved status"),
    limit:      int   = Query(default=50, ge=1, le=200),
    db: AsyncSession  = Depends(get_db),
    _: TokenData      = Depends(get_current_user),
):
    """
    Return alerts for a patient.

    Args:
        patient_id: Patient identifier.
        resolved:   If True, return only resolved alerts.
                    If False, return only active alerts.
                    If None (default), return all alerts.
        limit:      Maximum number of records to return.
    """
    return await crud.get_alerts(db, patient_id, resolved=resolved, limit=limit)


@router.post("/{alert_id}/resolve", response_model=AlertResponse, summary="Resolve an alert")
async def resolve_alert(
    alert_id: int,
    db: AsyncSession = Depends(get_db),
    _: TokenData     = Depends(get_current_user),
):
    """Mark an alert as resolved and record the resolution time."""
    alert = await crud.resolve_alert(db, alert_id)
    if not alert:
        raise NotFoundError(f"Alert {alert_id} not found.")
    return alert
