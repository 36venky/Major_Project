"""
tests/test_database.py
───────────────────────
Unit tests for CRUD operations.

All tests use the in-memory SQLite session from conftest.py.
"""

from __future__ import annotations

import pytest

from app.database import crud
from app.database.models import Patient


# ── Patient CRUD ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_and_get_patient(db_session):
    patient = await crud.create_patient(db_session, {
        "name": "Alice", "age": 40, "gender": "Female",
        "blood_group": "A+", "height": "160 cm", "weight": "55 kg",
    })
    assert patient.patient_id is not None

    fetched = await crud.get_patient(db_session, patient.patient_id)
    assert fetched is not None
    assert fetched.name == "Alice"


@pytest.mark.asyncio
async def test_get_patient_not_found(db_session):
    result = await crud.get_patient(db_session, "BOGUS-ID")
    assert result is None


@pytest.mark.asyncio
async def test_update_patient(db_session):
    p = await crud.create_patient(db_session, {
        "name": "Bob", "age": 50, "gender": "Male", "blood_group": "B+",
    })
    updated = await crud.update_patient(db_session, p.patient_id, {"age": 51})
    assert updated.age == 51


@pytest.mark.asyncio
async def test_delete_patient(db_session):
    p = await crud.create_patient(db_session, {
        "name": "Charlie", "age": 35, "gender": "Male", "blood_group": "O-",
    })
    deleted = await crud.delete_patient(db_session, p.patient_id)
    assert deleted is True
    assert await crud.get_patient(db_session, p.patient_id) is None


# ── Session CRUD ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_and_close_session(db_session):
    p = await crud.create_patient(db_session, {
        "name": "Dave", "age": 45, "gender": "Male", "blood_group": "AB+",
    })
    session = await crud.create_session(db_session, p.patient_id)
    assert session.is_active is True

    closed = await crud.close_session(db_session, session.session_id, 75.0, 60.0, 95.0)
    assert closed is not None
    assert closed.is_active is False
    assert closed.average_bpm == 75.0


# ── Alert CRUD ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_and_resolve_alert(db_session):
    p = await crud.create_patient(db_session, {
        "name": "Eve", "age": 38, "gender": "Female", "blood_group": "O+",
    })
    alert = await crud.create_alert(
        db_session, p.patient_id, "HIGH_HR", "warning", "Heart rate elevated"
    )
    assert alert.resolved is False

    resolved = await crud.resolve_alert(db_session, alert.id)
    assert resolved.resolved is True
    assert resolved.resolved_at is not None


# ── Weekly health CRUD ────────────────────────────────────

@pytest.mark.asyncio
async def test_create_weekly_health(db_session):
    p = await crud.create_patient(db_session, {
        "name": "Frank", "age": 55, "gender": "Male", "blood_group": "B-",
    })
    record = await crud.create_weekly_health(db_session, {
        "patient_id":     p.patient_id,
        "blood_pressure": "125/82 mmHg",
        "blood_sugar":    "105 mg/dL",
        "updated_by":     "Doctor",
    })
    assert record.blood_pressure == "125/82 mmHg"

    latest = await crud.get_latest_weekly_health(db_session, p.patient_id)
    assert latest is not None
    assert latest.updated_by == "Doctor"
