"""
services/patient_service.py
────────────────────────────
Business logic for patient record management.

All methods accept a database session and Pydantic-validated input.
Returns domain objects or raises typed exceptions.
"""

from __future__ import annotations

from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AlreadyExistsError, NotFoundError
from app.core.logger import get_logger
from app.database import crud
from app.database.models import Patient
from app.database.schemas import PatientCreate, PatientUpdate

logger = get_logger("app.patient_service")


async def list_patients(db: AsyncSession) -> Sequence[Patient]:
    """Return all patients."""
    return await crud.get_all_patients(db)


async def get_patient(db: AsyncSession, patient_id: str) -> Patient:
    """
    Fetch a single patient by ID.

    Raises:
        NotFoundError: if patient does not exist.
    """
    patient = await crud.get_patient(db, patient_id)
    if not patient:
        raise NotFoundError(f"Patient '{patient_id}' not found.")
    return patient


async def create_patient(db: AsyncSession, data: PatientCreate) -> Patient:
    """
    Create a new patient record.

    Raises:
        AlreadyExistsError: if patient_id is provided and already exists.
    """
    if data.patient_id:
        existing = await crud.get_patient(db, data.patient_id)
        if existing:
            raise AlreadyExistsError(f"Patient '{data.patient_id}' already exists.")

    payload = data.model_dump(exclude_none=False)
    patient = await crud.create_patient(db, payload)
    await db.commit()
    logger.info("Patient created: %s", patient.patient_id)
    return patient


async def update_patient(
    db: AsyncSession, patient_id: str, data: PatientUpdate
) -> Patient:
    """
    Update mutable fields of a patient record.

    Raises:
        NotFoundError: if patient does not exist.
    """
    await get_patient(db, patient_id)   # raises if missing
    updated = await crud.update_patient(db, patient_id, data.model_dump(exclude_none=True))
    logger.info("Patient updated: %s", patient_id)
    return updated


async def delete_patient(db: AsyncSession, patient_id: str) -> None:
    """
    Hard-delete a patient and all associated records.

    Raises:
        NotFoundError: if patient does not exist.
    """
    await get_patient(db, patient_id)
    await crud.delete_patient(db, patient_id)
    logger.info("Patient deleted: %s", patient_id)
