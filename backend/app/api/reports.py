"""
api/reports.py
───────────────
PDF report generation endpoint.

GET /reports/pdf/{session_id}  – download session PDF report
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.security import TokenData, get_current_user
from app.database import crud
from app.database.database import get_db
from app.services import report_service

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get(
    "/pdf/{session_id}",
    summary="Download session PDF report",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
async def download_report(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    _: TokenData     = Depends(get_current_user),
):
    """
    Generate and stream a PDF monitoring report for the given session.

    The PDF includes:
    - Patient demographics (including doctor & ambulance contacts)
    - Session statistics (avg/min/max BPM, duration)
    - BPM trend line chart (last 60 readings)
    - Blood Sugar & Blood Pressure trend charts (weekly history)
    - Alert history table
    - Latest weekly health values
    - Doctor notes

    Returns:
        PDF file as application/pdf response.
    """
    session = await crud.get_session(db, session_id)
    if not session:
        raise NotFoundError(f"Session '{session_id}' not found.")

    patient = await crud.get_patient(db, session.patient_id)
    if not patient:
        raise NotFoundError(f"Patient '{session.patient_id}' not found.")

    # Core data
    alerts        = await crud.get_alerts(db, session.patient_id, limit=100)
    weekly_health = await crud.get_latest_weekly_health(db, session.patient_id)
    doctor_notes  = await crud.get_doctor_notes(db, session.patient_id)

    # Chart data — heart rate history (last 60) + weekly health history (last 12)
    heart_rate_history    = await crud.get_heart_rate_history(db, session.patient_id, limit=60)
    weekly_health_history = await crud.get_weekly_health_history(db, session.patient_id, limit=12)

    pdf_bytes = report_service.generate_session_report(
        patient=patient,
        session=session,
        alerts=list(alerts),
        weekly_health=weekly_health,
        doctor_notes=list(doctor_notes),
        heart_rate_history=list(heart_rate_history),
        weekly_health_history=list(weekly_health_history),
    )

    filename = f"ecg_report_{session_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
