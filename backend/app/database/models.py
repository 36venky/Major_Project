"""
database/models.py
──────────────────
SQLAlchemy ORM models for all database tables.

Relationships:
  Patient ──< ECGSession ──< ECGSample
  Patient ──< HeartRate
  Patient ──< Alert
  Patient ──< WeeklyHealth
  Patient ──< DoctorNote
  Patient ──< RiskPrediction
  Patient ──< AlertLog
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey,
    Integer, String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.database import Base


def _now() -> datetime:
    """UTC-aware current timestamp."""
    return datetime.now(timezone.utc)


# ── Users ────────────────────────────────────────────────

class User(Base):
    """Application user account (doctor / guardian / admin)."""

    __tablename__ = "users"

    id: Mapped[int]                    = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str]              = mapped_column(String(80), unique=True, nullable=False, index=True)
    email: Mapped[str]                 = mapped_column(String(200), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str]       = mapped_column(String(200), nullable=False)
    full_name: Mapped[str]             = mapped_column(String(150), nullable=False)
    role: Mapped[str]                  = mapped_column(String(30), nullable=False, default="guardian")
    phone: Mapped[str | None]          = mapped_column(String(30), nullable=True)
    # Professional details
    specialization: Mapped[str | None] = mapped_column(String(120), nullable=True)   # e.g. "Cardiologist"
    hospital: Mapped[str | None]       = mapped_column(String(200), nullable=True)
    license_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Address / contact
    address: Mapped[str | None]        = mapped_column(Text, nullable=True)
    city: Mapped[str | None]           = mapped_column(String(100), nullable=True)
    state: Mapped[str | None]          = mapped_column(String(100), nullable=True)
    country: Mapped[str | None]        = mapped_column(String(100), nullable=True)
    # Account state
    is_active: Mapped[bool]            = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime]       = mapped_column(DateTime(timezone=True), default=_now)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ── Patients ──────────────────────────────────────────────

class Patient(Base):
    """Demographic and contact information for a monitored patient."""

    __tablename__ = "patients"

    patient_id: Mapped[str]           = mapped_column(String(36), primary_key=True, index=True)
    name: Mapped[str]                 = mapped_column(String(120), nullable=False)
    age: Mapped[int]                  = mapped_column(Integer, nullable=False)
    gender: Mapped[str]               = mapped_column(String(20), nullable=False)
    blood_group: Mapped[str]          = mapped_column(String(10), nullable=False)
    height: Mapped[str]               = mapped_column(String(20), nullable=True)
    weight: Mapped[str]               = mapped_column(String(20), nullable=True)
    guardian_name: Mapped[str]        = mapped_column(String(120), nullable=True)
    guardian_phone: Mapped[str]       = mapped_column(String(30), nullable=True)
    # Extended fields (Feature 2)
    phone: Mapped[str | None]         = mapped_column(String(30), nullable=True)
    emergency_contact: Mapped[str | None] = mapped_column(String(30), nullable=True)
    diseases: Mapped[str | None]         = mapped_column(Text, nullable=True)
    medications: Mapped[str | None]      = mapped_column(Text, nullable=True)
    allergies: Mapped[str | None]        = mapped_column(Text, nullable=True)
    address: Mapped[str | None]          = mapped_column(Text, nullable=True)
    registration_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Emergency services (Feature 4 – formal alerts)
    doctor_phone: Mapped[str | None]     = mapped_column(String(30), nullable=True)
    ambulance_phone: Mapped[str | None]  = mapped_column(String(30), nullable=True)
    # Location (Feature 7 – patient location management)
    location: Mapped[str | None]         = mapped_column(Text, nullable=True)  # "lat,lng" e.g. "12.9716,77.5946"
    location_address: Mapped[str | None] = mapped_column(Text, nullable=True)  # human-readable address
    maps_link: Mapped[str | None]        = mapped_column(Text, nullable=True)  # Google Maps URL
    created_at: Mapped[datetime]      = mapped_column(DateTime(timezone=True), default=_now)

    # Relationships
    sessions:         Mapped[list["ECGSession"]]     = relationship("ECGSession",     back_populates="patient", cascade="all, delete-orphan")
    heart_rates:      Mapped[list["HeartRate"]]      = relationship("HeartRate",      back_populates="patient", cascade="all, delete-orphan")
    alerts:           Mapped[list["Alert"]]          = relationship("Alert",          back_populates="patient", cascade="all, delete-orphan")
    weekly_health:    Mapped[list["WeeklyHealth"]]   = relationship("WeeklyHealth",   back_populates="patient", cascade="all, delete-orphan")
    doctor_notes:     Mapped[list["DoctorNote"]]     = relationship("DoctorNote",     back_populates="patient", cascade="all, delete-orphan")
    risk_predictions: Mapped[list["RiskPrediction"]] = relationship("RiskPrediction", back_populates="patient", cascade="all, delete-orphan")
    alert_logs:       Mapped[list["AlertLog"]]       = relationship("AlertLog",       back_populates="patient", cascade="all, delete-orphan")


# ── ECG Sessions ──────────────────────────────────────────

class ECGSession(Base):
    """
    A monitoring session: the period between ECG stream start and stop.
    Aggregated metrics are stored here; raw samples reference this record.
    """

    __tablename__ = "ecg_sessions"

    session_id:  Mapped[str]              = mapped_column(String(36), primary_key=True, index=True)
    patient_id:  Mapped[str]              = mapped_column(String(36), ForeignKey("patients.patient_id"), index=True)
    start_time:  Mapped[datetime]         = mapped_column(DateTime(timezone=True), default=_now)
    end_time:    Mapped[datetime | None]  = mapped_column(DateTime(timezone=True), nullable=True)
    duration:    Mapped[str | None]       = mapped_column(String(20), nullable=True)    # e.g. "00:12:34"
    average_bpm: Mapped[float | None]     = mapped_column(Float, nullable=True)
    minimum_bpm: Mapped[float | None]     = mapped_column(Float, nullable=True)
    maximum_bpm: Mapped[float | None]     = mapped_column(Float, nullable=True)
    is_active:   Mapped[bool]             = mapped_column(Boolean, default=True)

    patient: Mapped["Patient"]         = relationship("Patient", back_populates="sessions")
    samples: Mapped[list["ECGSample"]] = relationship("ECGSample", back_populates="session", cascade="all, delete-orphan")


# ── ECG Samples ───────────────────────────────────────────

class ECGSample(Base):
    """
    Individual raw ECG data point.

    Retention: automatically deleted after RAW_ECG_RETENTION_HOURS (default 48 h).
    The session-level aggregates in ECGSession are kept permanently.
    """

    __tablename__ = "ecg_samples"

    sample_id:  Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str]      = mapped_column(String(36), ForeignKey("ecg_sessions.session_id"), index=True)
    patient_id: Mapped[str]      = mapped_column(String(36), ForeignKey("patients.patient_id"),    index=True)
    timestamp:  Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    ecg_value:  Mapped[float]    = mapped_column(Float, nullable=False)
    filtered_value: Mapped[float | None] = mapped_column(Float, nullable=True)

    session: Mapped["ECGSession"] = relationship("ECGSession", back_populates="samples")


# ── Heart Rate ────────────────────────────────────────────

class HeartRate(Base):
    """Time-series heart rate measurements (BPM) calculated from R-peaks."""

    __tablename__ = "heart_rate"

    id:         Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[str]      = mapped_column(String(36), ForeignKey("patients.patient_id"), index=True)
    timestamp:  Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    bpm:        Mapped[float]    = mapped_column(Float, nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    patient: Mapped["Patient"] = relationship("Patient", back_populates="heart_rates")


# ── Alerts ────────────────────────────────────────────────

class Alert(Base):
    """Clinical alerts generated by the alert engine."""

    __tablename__ = "alerts"

    id:          Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id:  Mapped[str]      = mapped_column(String(36), ForeignKey("patients.patient_id"), index=True)
    timestamp:   Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    alert_type:  Mapped[str]      = mapped_column(String(50), nullable=False)   # e.g. "HIGH_HR"
    severity:    Mapped[str]      = mapped_column(String(20), nullable=False)   # critical | warning | info
    message:     Mapped[str]      = mapped_column(Text, nullable=False)
    resolved:    Mapped[bool]     = mapped_column(Boolean, default=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    patient: Mapped["Patient"] = relationship("Patient", back_populates="alerts")


# ── Weekly Health ─────────────────────────────────────────

class WeeklyHealth(Base):
    """Manually entered health metrics (BP, blood sugar, weight) per patient."""

    __tablename__ = "weekly_health"

    id:             Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id:     Mapped[str]      = mapped_column(String(36), ForeignKey("patients.patient_id"), index=True)
    date:           Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    blood_pressure: Mapped[str]      = mapped_column(String(30), nullable=True)   # e.g. "120/80 mmHg"
    blood_sugar:    Mapped[str]      = mapped_column(String(30), nullable=True)   # e.g. "98 mg/dL"
    weight:         Mapped[str]      = mapped_column(String(20), nullable=True)
    notes:          Mapped[str]      = mapped_column(Text, nullable=True)
    updated_by:     Mapped[str]      = mapped_column(String(50), nullable=True)

    patient: Mapped["Patient"] = relationship("Patient", back_populates="weekly_health")


# ── Doctor Notes ──────────────────────────────────────────

class DoctorNote(Base):
    """Clinical notes written by doctors and attached to a patient record."""

    __tablename__ = "doctor_notes"

    id:         Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[str]      = mapped_column(String(36), ForeignKey("patients.patient_id"), index=True)
    doctor:     Mapped[str]      = mapped_column(String(120), nullable=False)
    timestamp:  Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    note:       Mapped[str]      = mapped_column(Text, nullable=False)

    patient: Mapped["Patient"] = relationship("Patient", back_populates="doctor_notes")


# ── Risk Predictions ──────────────────────────────────────

class RiskPrediction(Base):
    """ML-based cardiac risk prediction result per patient (Feature 5)."""

    __tablename__ = "risk_predictions"

    id:             Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id:     Mapped[str]      = mapped_column(String(36), ForeignKey("patients.patient_id"), index=True)
    timestamp:      Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    risk_percentage: Mapped[float]   = mapped_column(Float, nullable=False)   # 0.0–100.0
    risk_level:     Mapped[str]      = mapped_column(String(20), nullable=False)  # Low | Moderate | High
    majority_label: Mapped[str | None] = mapped_column(String(10), nullable=True)  # raw model label

    patient: Mapped["Patient"] = relationship("Patient", back_populates="risk_predictions")


# ── Alert Logs (WhatsApp dispatch log) ────────────────────

class AlertLog(Base):
    """Log of every WhatsApp message dispatch attempt (Feature 4)."""

    __tablename__ = "alert_logs"

    id:            Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id:    Mapped[str]      = mapped_column(String(36), ForeignKey("patients.patient_id"), index=True)
    timestamp:     Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    alert_type:    Mapped[str]      = mapped_column(String(50), nullable=False)
    recipient:     Mapped[str]      = mapped_column(String(50), nullable=False)
    status:        Mapped[str]      = mapped_column(String(10), nullable=False)   # sent | failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    patient: Mapped["Patient"] = relationship("Patient", back_populates="alert_logs")
