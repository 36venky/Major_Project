"""
database/schemas.py
────────────────────
Pydantic v2 schemas for request validation, response serialisation,
and inter-layer data transfer.

Naming convention:
  <Model>Base      – shared fields
  <Model>Create    – body of POST requests
  <Model>Update    – body of PUT/PATCH requests
  <Model>Response  – what the API returns (includes computed/DB fields)
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Shared config ─────────────────────────────────────────

class _ORMBase(BaseModel):
    """Enable ORM mode for all response schemas."""
    model_config = ConfigDict(from_attributes=True)


# ────────────────────────────────────────────────────────────
# Patient
# ────────────────────────────────────────────────────────────

class PatientBase(BaseModel):
    name:           str = Field(..., min_length=2, max_length=120)
    age:            int = Field(..., ge=0, le=150)
    gender:         str = Field(..., max_length=20)
    blood_group:    str = Field(..., max_length=10)
    height:         Optional[str] = None
    weight:         Optional[str] = None
    guardian_name:  Optional[str] = None
    guardian_phone: Optional[str] = None
    # Extended fields (Feature 2)
    phone:             Optional[str] = None
    emergency_contact: Optional[str] = None
    diseases:          Optional[str] = None
    medications:       Optional[str] = None
    allergies:         Optional[str] = None
    address:           Optional[str] = None
    registration_date: Optional[datetime] = None


class PatientCreate(PatientBase):
    patient_id: Optional[str] = None   # auto-generated if omitted


class PatientUpdate(BaseModel):
    name:              Optional[str] = None
    age:               Optional[int] = None
    gender:            Optional[str] = None
    blood_group:       Optional[str] = None
    height:            Optional[str] = None
    weight:            Optional[str] = None
    guardian_name:     Optional[str] = None
    guardian_phone:    Optional[str] = None
    phone:             Optional[str] = None
    emergency_contact: Optional[str] = None
    diseases:          Optional[str] = None
    medications:       Optional[str] = None
    allergies:         Optional[str] = None
    address:           Optional[str] = None


class PatientResponse(_ORMBase, PatientBase):
    patient_id: str
    created_at: datetime


# ────────────────────────────────────────────────────────────
# ECG Session
# ────────────────────────────────────────────────────────────

class ECGSessionResponse(_ORMBase):
    session_id:  str
    patient_id:  str
    start_time:  datetime
    end_time:    Optional[datetime] = None
    duration:    Optional[str] = None
    average_bpm: Optional[float] = None
    minimum_bpm: Optional[float] = None
    maximum_bpm: Optional[float] = None
    is_active:   bool


# ────────────────────────────────────────────────────────────
# ECG Sample
# ────────────────────────────────────────────────────────────

class ECGSampleResponse(_ORMBase):
    sample_id:      int
    session_id:     str
    patient_id:     str
    timestamp:      datetime
    ecg_value:      float
    filtered_value: Optional[float] = None


# ────────────────────────────────────────────────────────────
# Heart Rate
# ────────────────────────────────────────────────────────────

class HeartRateResponse(_ORMBase):
    id:         int
    patient_id: str
    timestamp:  datetime
    bpm:        float
    session_id: Optional[str] = None


# ────────────────────────────────────────────────────────────
# Weekly Health
# ────────────────────────────────────────────────────────────

class WeeklyHealthCreate(BaseModel):
    patient_id:     str
    blood_pressure: Optional[str] = None
    blood_sugar:    Optional[str] = None
    weight:         Optional[str] = None
    notes:          Optional[str] = None
    updated_by:     Optional[str] = "Guardian"


class WeeklyHealthUpdate(BaseModel):
    blood_pressure: Optional[str] = None
    blood_sugar:    Optional[str] = None
    weight:         Optional[str] = None
    notes:          Optional[str] = None
    updated_by:     Optional[str] = None


class WeeklyHealthResponse(_ORMBase):
    id:             int
    patient_id:     str
    date:           datetime
    blood_pressure: Optional[str] = None
    blood_sugar:    Optional[str] = None
    weight:         Optional[str] = None
    notes:          Optional[str] = None
    updated_by:     Optional[str] = None


# ────────────────────────────────────────────────────────────
# Alerts
# ────────────────────────────────────────────────────────────

class AlertResponse(_ORMBase):
    id:          int
    patient_id:  str
    timestamp:   datetime
    alert_type:  str
    severity:    str
    message:     str
    resolved:    bool
    resolved_at: Optional[datetime] = None


# ────────────────────────────────────────────────────────────
# Doctor Notes
# ────────────────────────────────────────────────────────────

class DoctorNoteCreate(BaseModel):
    patient_id: str
    doctor:     str
    note:       str = Field(..., min_length=1)


class DoctorNoteResponse(_ORMBase):
    id:         int
    patient_id: str
    doctor:     str
    timestamp:  datetime
    note:       str


# ────────────────────────────────────────────────────────────
# Auth
# ────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token:  str
    refresh_token: str
    token_type:    str = "bearer"
    expires_in:    int


class UserProfileResponse(BaseModel):
    username:  str
    role:      str
    full_name: str


# ────────────────────────────────────────────────────────────
# WebSocket broadcast payload
# ────────────────────────────────────────────────────────────

class WSPayload(BaseModel):
    timestamp:   str
    ecg:         float
    bpm:         int
    quality:     str
    quality_pct: int
    status:      str
    session_id:  Optional[str] = None
    analysis:    Optional[dict] = None


# ────────────────────────────────────────────────────────────
# Generic API response wrapper
# ────────────────────────────────────────────────────────────

class APIResponse(BaseModel):
    """Standard JSON envelope for all API responses."""
    success: bool = True
    message: str  = "OK"
    data:    Optional[object] = None


# ────────────────────────────────────────────────────────────
# Risk Prediction
# ────────────────────────────────────────────────────────────

class RiskPredictionResponse(_ORMBase):
    id:              int
    patient_id:      str
    timestamp:       datetime
    risk_percentage: float
    risk_level:      str
    majority_label:  Optional[str] = None


# ────────────────────────────────────────────────────────────
# Alert Log
# ────────────────────────────────────────────────────────────

class AlertLogResponse(_ORMBase):
    id:            int
    patient_id:    str
    timestamp:     datetime
    alert_type:    str
    recipient:     str
    status:        str
    error_message: Optional[str] = None
