"""
api/patients.py
────────────────
Patient CRUD endpoints.

GET    /patients         – list all patients
GET    /patients/{id}    – get single patient
POST   /patients         – create patient
PUT    /patients/{id}    – update patient
DELETE /patients/{id}    – delete patient (admin only)
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenData, get_current_user, require_admin
from app.database.database import get_db
from app.database.schemas import (
    APIResponse, PatientCreate, PatientResponse, PatientUpdate,
)
from app.services import patient_service
from app.services.ecg_service import ecg_service

router = APIRouter(prefix="/patients", tags=["Patients"])


@router.get("", response_model=List[PatientResponse], summary="List all patients")
async def list_patients(
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    """Return all registered patients ordered by creation date."""
    return await patient_service.list_patients(db)


@router.get("/{patient_id}", response_model=PatientResponse, summary="Get a patient by ID")
async def get_patient(
    patient_id: str,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    """Fetch a single patient record. Returns 404 if not found."""
    return await patient_service.get_patient(db, patient_id)


@router.post(
    "",
    response_model=PatientResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new patient",
)
async def create_patient(
    body: PatientCreate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    """Create a new patient record. Returns 409 if patient_id already exists."""
    return await patient_service.create_patient(db, body)


@router.put("/{patient_id}", response_model=PatientResponse, summary="Update patient information")
async def update_patient(
    patient_id: str,
    body: PatientUpdate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    """Update one or more fields of an existing patient record."""
    return await patient_service.update_patient(db, patient_id, body)


@router.delete(
    "/{patient_id}",
    response_model=APIResponse,
    summary="Delete a patient (admin only)",
)
async def delete_patient(
    patient_id: str,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    """Permanently delete a patient and all associated records. Requires admin role."""
    await patient_service.delete_patient(db, patient_id)
    return APIResponse(message=f"Patient {patient_id} deleted.")


@router.post(
    "/{patient_id}/select",
    response_model=APIResponse,
    summary="Switch active monitored patient",
)
async def select_patient(
    patient_id: str,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
):
    """Switch the active monitoring session to the specified patient."""
    await patient_service.get_patient(db, patient_id)   # raises 404 if missing
    await ecg_service.switch_patient(patient_id)
    return APIResponse(message=f"Active patient switched to {patient_id}.")
