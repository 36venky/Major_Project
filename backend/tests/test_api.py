"""
tests/test_api.py
──────────────────
Integration tests for REST API endpoints.

Uses the in-memory SQLite database and async HTTP test client from conftest.py.
The ECGService serial/WebSocket loops are not started in tests.
"""

from __future__ import annotations

import pytest
import pytest_asyncio


# ─────────────────────────────────────────────────────────────
# Auth tests
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_login_success(client):
    resp = await client.post("/auth/login", json={"username": "guardian", "password": "guardian123"})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    resp = await client.post("/auth/login", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_user(client):
    resp = await client.post("/auth/login", json={"username": "nobody", "password": "pass"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_profile_authenticated(client, auth_headers):
    resp = await client.get("/auth/profile", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["username"] == "guardian"


@pytest.mark.asyncio
async def test_profile_unauthenticated(client):
    resp = await client.get("/auth/profile")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_logout(client, auth_headers):
    resp = await client.post("/auth/logout", headers=auth_headers)
    assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────
# Patient tests
# ─────────────────────────────────────────────────────────────

_PATIENT_PAYLOAD = {
    "name":          "Test Patient",
    "age":           30,
    "gender":        "Female",
    "blood_group":   "O+",
    "height":        "165 cm",
    "weight":        "58 kg",
    "guardian_name": "Test Guardian",
    "guardian_phone": "+91 99999 00000",
}


@pytest.mark.asyncio
async def test_create_patient(client, auth_headers):
    resp = await client.post("/patients", json=_PATIENT_PAYLOAD, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Test Patient"
    assert "patient_id" in data


@pytest.mark.asyncio
async def test_list_patients(client, auth_headers):
    # Create one first
    await client.post("/patients", json=_PATIENT_PAYLOAD, headers=auth_headers)
    resp = await client.get("/patients", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_get_patient_not_found(client, auth_headers):
    resp = await client.get("/patients/NONEXISTENT", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_patient(client, auth_headers):
    create_resp = await client.post("/patients", json=_PATIENT_PAYLOAD, headers=auth_headers)
    pid = create_resp.json()["patient_id"]

    resp = await client.put(f"/patients/{pid}", json={"age": 35}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["age"] == 35


@pytest.mark.asyncio
async def test_delete_patient_requires_admin(client, auth_headers, admin_headers):
    create_resp = await client.post("/patients", json=_PATIENT_PAYLOAD, headers=auth_headers)
    pid = create_resp.json()["patient_id"]

    # guardian cannot delete
    resp = await client.delete(f"/patients/{pid}", headers=auth_headers)
    assert resp.status_code == 403

    # admin can delete
    resp = await client.delete(f"/patients/{pid}", headers=admin_headers)
    assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────
# Weekly health tests
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_weekly_health(client, auth_headers):
    # Need a patient first
    pr = await client.post("/patients", json=_PATIENT_PAYLOAD, headers=auth_headers)
    pid = pr.json()["patient_id"]

    resp = await client.post("/weekly-health", json={
        "patient_id":     pid,
        "blood_pressure": "118/76 mmHg",
        "blood_sugar":    "92 mg/dL",
        "weight":         "58 kg",
        "updated_by":     "Guardian",
    }, headers=auth_headers)
    assert resp.status_code == 201
    assert resp.json()["blood_pressure"] == "118/76 mmHg"


@pytest.mark.asyncio
async def test_get_weekly_health_not_found(client, auth_headers):
    resp = await client.get("/weekly-health?patient_id=NOBODY", headers=auth_headers)
    assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────
# Alerts tests
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_alerts_empty(client, auth_headers):
    resp = await client.get("/alerts?patient_id=EMPTY_PATIENT", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


# ─────────────────────────────────────────────────────────────
# Health check
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_check(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
