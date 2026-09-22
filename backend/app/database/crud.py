"""
database/crud.py
────────────────
Repository layer – all direct database access lives here.

Principles:
  - No business logic. Pure data access.
  - All methods are async.
  - Services call CRUD; API routes never call CRUD directly.
  - Returns ORM models or None; never raises HTTP exceptions.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from sqlalchemy import delete, select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.database.models import (
    Alert, AlertLog, DoctorNote, ECGSample, ECGSession,
    HeartRate, Patient, RiskPrediction, User, WeeklyHealth,
)

logger = get_logger("database.crud")


# ── Helpers ────────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ────────────────────────────────────────────────────────────
# Patient CRUD
# ────────────────────────────────────────────────────────────

async def create_patient(db: AsyncSession, data: dict) -> Patient:
    """Insert a new patient record. Supports auto-generated patient_id with date-based format."""
    from datetime import date as _date

    # Work on a copy so we never mutate the caller's dict
    data = dict(data)

    explicit_id = data.pop("patient_id", None)
    if explicit_id:
        patient_id = explicit_id
    else:
        # Format: P-YYYYMMDD-XXXX (sequential counter per day)
        today = _date.today().strftime("%Y%m%d")
        prefix = f"P-{today}-"
        result = await db.execute(
            select(func.count(Patient.patient_id)).where(
                Patient.patient_id.like(f"{prefix}%")
            )
        )
        count = (result.scalar() or 0) + 1
        if count > 9999:
            raise ValueError("Daily patient registration limit (9999) reached.")
        patient_id = f"{prefix}{count:04d}"

    patient = Patient(patient_id=patient_id, **data)
    db.add(patient)
    await db.flush()
    logger.info("Created patient %s", patient.patient_id)
    return patient


async def get_patient(db: AsyncSession, patient_id: str) -> Optional[Patient]:
    """Fetch a single patient by ID."""
    result = await db.execute(select(Patient).where(Patient.patient_id == patient_id))
    return result.scalar_one_or_none()


async def get_all_patients(db: AsyncSession) -> Sequence[Patient]:
    """Fetch all patients ordered by creation date."""
    result = await db.execute(select(Patient).order_by(Patient.created_at.desc()))
    return result.scalars().all()


async def update_patient(db: AsyncSession, patient_id: str, data: dict) -> Optional[Patient]:
    """
    Update a patient record with only the fields present in *data*.

    Fields absent from *data* are never touched.
    Fields explicitly set to None in *data* ARE written as NULL —
    this is intentional and required for clearing optional fields
    (e.g. clearing location via DELETE /patients/{id}/location).
    """
    patient = await get_patient(db, patient_id)
    if not patient:
        return None
    for key, value in data.items():
        if hasattr(patient, key):
            setattr(patient, key, value)   # None is written as NULL — intentional
        else:
            logger.warning("update_patient: unknown column '%s' — skipped", key)
    await db.flush()
    logger.info("Updated patient %s — fields: %s", patient_id, list(data.keys()))
    return patient


async def delete_patient(db: AsyncSession, patient_id: str) -> bool:
    """Hard-delete a patient and all related records (cascade)."""
    patient = await get_patient(db, patient_id)
    if not patient:
        return False
    await db.delete(patient)
    await db.flush()
    logger.info("Deleted patient %s", patient_id)
    return True


# ────────────────────────────────────────────────────────────
# ECG Session CRUD
# ────────────────────────────────────────────────────────────

async def create_session(db: AsyncSession, patient_id: str) -> ECGSession:
    """Open a new ECG monitoring session."""
    session = ECGSession(
        session_id=f"S-{uuid.uuid4().hex[:10].upper()}",
        patient_id=patient_id,
        is_active=True,
    )
    db.add(session)
    await db.flush()
    logger.info("Opened session %s for patient %s", session.session_id, patient_id)
    return session


async def close_session(
    db: AsyncSession,
    session_id: str,
    avg_bpm: float,
    min_bpm: float,
    max_bpm: float,
) -> Optional[ECGSession]:
    """Close an active session and store aggregated metrics."""
    result = await db.execute(
        select(ECGSession).where(ECGSession.session_id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        return None

    now = _utcnow()
    # Normalise start_time — always treat as UTC regardless of stored tzinfo
    start = session.start_time
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    elapsed = now - start
    hours, rem = divmod(int(elapsed.total_seconds()), 3600)
    minutes, seconds = divmod(rem, 60)

    session.end_time    = now
    session.duration    = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    session.average_bpm = round(avg_bpm, 1)
    session.minimum_bpm = round(min_bpm, 1)
    session.maximum_bpm = round(max_bpm, 1)
    session.is_active   = False

    await db.flush()
    logger.info("Closed session %s  avg=%.1f  min=%.1f  max=%.1f",
                session_id, avg_bpm, min_bpm, max_bpm)
    return session


async def get_session(db: AsyncSession, session_id: str) -> Optional[ECGSession]:
    result = await db.execute(select(ECGSession).where(ECGSession.session_id == session_id))
    return result.scalar_one_or_none()


async def get_sessions_for_patient(
    db: AsyncSession, patient_id: str, limit: int = 20
) -> Sequence[ECGSession]:
    result = await db.execute(
        select(ECGSession)
        .where(ECGSession.patient_id == patient_id)
        .order_by(ECGSession.start_time.desc())
        .limit(limit)
    )
    return result.scalars().all()


async def get_active_session(db: AsyncSession, patient_id: str) -> Optional[ECGSession]:
    """Return the currently open session for a patient, if any."""
    result = await db.execute(
        select(ECGSession)
        .where(ECGSession.patient_id == patient_id, ECGSession.is_active == True)
        .order_by(ECGSession.start_time.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


# ────────────────────────────────────────────────────────────
# ECG Sample CRUD
# ────────────────────────────────────────────────────────────

async def bulk_insert_samples(
    db: AsyncSession,
    samples: list[dict],
) -> None:
    """Batch-insert ECG samples for efficiency."""
    db.add_all([ECGSample(**s) for s in samples])
    await db.flush()


async def get_recent_samples(
    db: AsyncSession, session_id: str, limit: int = 500
) -> Sequence[ECGSample]:
    result = await db.execute(
        select(ECGSample)
        .where(ECGSample.session_id == session_id)
        .order_by(ECGSample.timestamp.desc())
        .limit(limit)
    )
    return result.scalars().all()


async def delete_old_samples(db: AsyncSession, hours: int) -> int:
    """
    Delete raw ECG samples older than `hours` hours.

    Returns the number of deleted rows.
    """
    cutoff = _utcnow() - timedelta(hours=hours)
    result = await db.execute(
        delete(ECGSample).where(ECGSample.timestamp < cutoff)
    )
    count = result.rowcount
    if count:
        logger.info("Deleted %d ECG samples older than %dh", count, hours)
    return count


# ────────────────────────────────────────────────────────────
# Heart Rate CRUD
# ────────────────────────────────────────────────────────────

async def save_heart_rate(
    db: AsyncSession, patient_id: str, bpm: float, session_id: str | None = None
) -> HeartRate:
    hr = HeartRate(patient_id=patient_id, bpm=round(bpm, 1), session_id=session_id)
    db.add(hr)
    await db.flush()
    return hr


async def get_heart_rate_history(
    db: AsyncSession, patient_id: str, limit: int = 100
) -> Sequence[HeartRate]:
    result = await db.execute(
        select(HeartRate)
        .where(HeartRate.patient_id == patient_id)
        .order_by(HeartRate.timestamp.desc())
        .limit(limit)
    )
    return result.scalars().all()


async def get_latest_bpm(db: AsyncSession, patient_id: str) -> Optional[HeartRate]:
    result = await db.execute(
        select(HeartRate)
        .where(HeartRate.patient_id == patient_id)
        .order_by(HeartRate.timestamp.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


# ────────────────────────────────────────────────────────────
# Alerts CRUD
# ────────────────────────────────────────────────────────────

async def create_alert(
    db: AsyncSession,
    patient_id: str,
    alert_type: str,
    severity: str,
    message: str,
) -> Alert:
    alert = Alert(
        patient_id=patient_id,
        alert_type=alert_type,
        severity=severity,
        message=message,
    )
    db.add(alert)
    await db.flush()
    logger.info("Alert [%s/%s] for patient %s: %s", alert_type, severity, patient_id, message)
    return alert


async def get_alerts(
    db: AsyncSession,
    patient_id: str,
    resolved: bool | None = None,
    limit: int = 50,
) -> Sequence[Alert]:
    q = select(Alert).where(Alert.patient_id == patient_id)
    if resolved is not None:
        q = q.where(Alert.resolved == resolved)
    q = q.order_by(Alert.timestamp.desc()).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


async def resolve_alert(db: AsyncSession, alert_id: int) -> Optional[Alert]:
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if alert:
        alert.resolved    = True
        alert.resolved_at = _utcnow()
        await db.flush()
    return alert


# ────────────────────────────────────────────────────────────
# Weekly Health CRUD
# ────────────────────────────────────────────────────────────

async def create_weekly_health(db: AsyncSession, data: dict) -> WeeklyHealth:
    record = WeeklyHealth(**data)
    db.add(record)
    await db.flush()
    return record


async def get_latest_weekly_health(
    db: AsyncSession, patient_id: str
) -> Optional[WeeklyHealth]:
    result = await db.execute(
        select(WeeklyHealth)
        .where(WeeklyHealth.patient_id == patient_id)
        .order_by(WeeklyHealth.date.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_weekly_health_history(
    db: AsyncSession, patient_id: str, limit: int = 10
) -> Sequence[WeeklyHealth]:
    result = await db.execute(
        select(WeeklyHealth)
        .where(WeeklyHealth.patient_id == patient_id)
        .order_by(WeeklyHealth.date.desc())
        .limit(limit)
    )
    return result.scalars().all()


async def update_weekly_health(
    db: AsyncSession, record_id: int, data: dict
) -> Optional[WeeklyHealth]:
    result = await db.execute(select(WeeklyHealth).where(WeeklyHealth.id == record_id))
    record = result.scalar_one_or_none()
    if not record:
        return None
    for k, v in data.items():
        if v is not None:
            setattr(record, k, v)
    await db.flush()
    return record


# ────────────────────────────────────────────────────────────
# Doctor Notes CRUD
# ────────────────────────────────────────────────────────────

async def create_doctor_note(db: AsyncSession, data: dict) -> DoctorNote:
    note = DoctorNote(**data)
    db.add(note)
    await db.flush()
    return note


async def get_doctor_notes(
    db: AsyncSession, patient_id: str
) -> Sequence[DoctorNote]:
    result = await db.execute(
        select(DoctorNote)
        .where(DoctorNote.patient_id == patient_id)
        .order_by(DoctorNote.timestamp.desc())
    )
    return result.scalars().all()


# ────────────────────────────────────────────────────────────
# Risk Prediction CRUD (Feature 5)
# ────────────────────────────────────────────────────────────

async def save_risk_prediction(
    db: AsyncSession,
    patient_id: str,
    risk_percentage: float,
    risk_level: str,
    majority_label: str | None = None,
) -> RiskPrediction:
    """Persist a new risk prediction result."""
    record = RiskPrediction(
        patient_id=patient_id,
        risk_percentage=round(risk_percentage, 1),
        risk_level=risk_level,
        majority_label=majority_label,
    )
    db.add(record)
    await db.flush()
    return record


async def get_latest_risk_prediction(
    db: AsyncSession, patient_id: str
) -> Optional[RiskPrediction]:
    """Return the most recent prediction for a patient."""
    result = await db.execute(
        select(RiskPrediction)
        .where(RiskPrediction.patient_id == patient_id)
        .order_by(RiskPrediction.timestamp.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_risk_prediction_history(
    db: AsyncSession, patient_id: str, days: int = 30
) -> Sequence[RiskPrediction]:
    """Return predictions within the last `days` days, oldest first."""
    cutoff = _utcnow() - timedelta(days=days)
    result = await db.execute(
        select(RiskPrediction)
        .where(
            RiskPrediction.patient_id == patient_id,
            RiskPrediction.timestamp >= cutoff,
        )
        .order_by(RiskPrediction.timestamp.asc())
    )
    return result.scalars().all()


# ────────────────────────────────────────────────────────────
# Alert Log CRUD (Feature 4 – WhatsApp dispatch log)
# ────────────────────────────────────────────────────────────

async def create_alert_log(
    db: AsyncSession,
    patient_id: str,
    alert_type: str,
    recipient: str,
    status: str,
    error_message: str | None = None,
) -> AlertLog:
    """Record a WhatsApp dispatch attempt."""
    log = AlertLog(
        patient_id=patient_id,
        alert_type=alert_type,
        recipient=recipient,
        status=status,
        error_message=error_message,
    )
    db.add(log)
    await db.flush()
    return log


async def get_alert_logs(
    db: AsyncSession,
    patient_id: str,
    limit: int = 50,
) -> Sequence[AlertLog]:
    """Return recent WhatsApp dispatch logs for a patient, newest first."""
    result = await db.execute(
        select(AlertLog)
        .where(AlertLog.patient_id == patient_id)
        .order_by(AlertLog.timestamp.desc())
        .limit(limit)
    )
    return result.scalars().all()


# ────────────────────────────────────────────────────────────
# User CRUD
# ────────────────────────────────────────────────────────────

async def create_user(db: AsyncSession, data: dict) -> User:
    """Insert a new user account. `data` must include hashed_password (not plain)."""
    user = User(**data)
    db.add(user)
    await db.flush()
    logger.info("Created user '%s' (role=%s)", user.username, user.role)
    return user


async def get_user_by_id(db: AsyncSession, user_id: int) -> Optional[User]:
    """Fetch a user by primary key."""
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_username(db: AsyncSession, username: str) -> Optional[User]:
    """Fetch a user by username (case-insensitive)."""
    result = await db.execute(
        select(User).where(func.lower(User.username) == username.lower())
    )
    return result.scalar_one_or_none()


async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    """Fetch a user by email address (case-insensitive)."""
    result = await db.execute(
        select(User).where(func.lower(User.email) == email.lower())
    )
    return result.scalar_one_or_none()


async def get_all_users(db: AsyncSession) -> Sequence[User]:
    """Return all users ordered by creation date."""
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return result.scalars().all()


async def update_user(db: AsyncSession, user_id: int, data: dict) -> Optional[User]:
    """Partially update a user record (skips None values)."""
    user = await get_user_by_id(db, user_id)
    if not user:
        return None
    for key, value in data.items():
        if value is not None:
            setattr(user, key, value)
    await db.flush()
    return user


async def update_last_login(db: AsyncSession, user_id: int) -> None:
    """Stamp the last_login field to now (called on every successful login)."""
    await db.execute(
        update(User).where(User.id == user_id).values(last_login=_utcnow())
    )
    await db.flush()


async def delete_user(db: AsyncSession, user_id: int) -> bool:
    """Hard-delete a user account."""
    user = await get_user_by_id(db, user_id)
    if not user:
        return False
    await db.delete(user)
    await db.flush()
    logger.info("Deleted user id=%d", user_id)
    return True


async def username_exists(db: AsyncSession, username: str) -> bool:
    """Return True if username is already taken."""
    result = await db.execute(
        select(func.count(User.id)).where(func.lower(User.username) == username.lower())
    )
    return (result.scalar() or 0) > 0


async def email_exists(db: AsyncSession, email: str) -> bool:
    """Return True if email is already registered."""
    result = await db.execute(
        select(func.count(User.id)).where(func.lower(User.email) == email.lower())
    )
    return (result.scalar() or 0) > 0
