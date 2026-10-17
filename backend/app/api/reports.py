"""
api/reports.py
───────────────
PDF report generation endpoints.

GET /reports/pdf/{session_id}  – download single session PDF
GET /reports/pdf/all           – download all sessions for a patient as one merged PDF
"""

from __future__ import annotations

import io

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pypdf import PdfWriter, PdfReader
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.security import TokenData, get_current_user
from app.database import crud
from app.database.database import get_db
from app.services import report_service

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get(
    "/pdf/all",
    summary="Download all sessions for a patient as a single merged PDF",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
async def download_all_reports(
    patient_id: str      = Query(default=None, description="Patient ID (defaults to active patient)"),
    limit:      int      = Query(default=50, ge=1, le=200,
                                 description="Maximum number of sessions to include"),
    db: AsyncSession     = Depends(get_db),
    _: TokenData         = Depends(get_current_user),
):
    """
    Generate and download a merged PDF containing reports for ALL sessions
    of the specified patient (most recent first, up to `limit`).

    Each session gets its own page-group inside the single PDF.
    Returns 404 if no sessions exist for the patient.
    """
    from app.services.ecg_service import ecg_service as _ecg_service
    resolved_patient_id = patient_id or _ecg_service.active_patient_id or "P-001"
    patient = await crud.get_patient(db, resolved_patient_id)
    if not patient:
        raise NotFoundError(f"Patient '{resolved_patient_id}' not found.")

    sessions = await crud.get_sessions_for_patient(db, resolved_patient_id, limit=limit)
    if not sessions:
        raise NotFoundError(f"No ECG sessions found for patient '{resolved_patient_id}'.")

    # Common data shared across all session sub-reports
    all_alerts            = await crud.get_alerts(db, resolved_patient_id, limit=200)
    weekly_health         = await crud.get_latest_weekly_health(db, resolved_patient_id)
    doctor_notes          = await crud.get_doctor_notes(db, resolved_patient_id)
    heart_rate_history    = await crud.get_heart_rate_history(db, resolved_patient_id, limit=60)
    weekly_health_history = await crud.get_weekly_health_history(db, resolved_patient_id, limit=12)

    # Generate one PDF per session then merge with pypdf
    writer = PdfWriter()

    for session in sessions:
        # Filter alerts to this session's timeframe (approximate)
        session_alerts = [
            a for a in all_alerts
            if (session.start_time is None or a.timestamp >= session.start_time)
            and (session.end_time is None   or a.timestamp <= session.end_time)
        ] if session.start_time else list(all_alerts)

        pdf_bytes = report_service.generate_session_report(
            patient               = patient,
            session               = session,
            alerts                = session_alerts,
            weekly_health         = weekly_health,
            doctor_notes          = list(doctor_notes),
            heart_rate_history    = list(heart_rate_history),
            weekly_health_history = list(weekly_health_history),
        )
        sub_reader = PdfReader(io.BytesIO(pdf_bytes))
        for page in sub_reader.pages:
            writer.add_page(page)

    merged_buffer = io.BytesIO()
    writer.write(merged_buffer)
    merged_bytes = merged_buffer.getvalue()

    filename = f"ecg_all_reports_{resolved_patient_id}.pdf"
    return Response(
        content=merged_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/pdf/{session_id}",
    summary="Download single session PDF report",
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

    The PDF includes patient demographics, session statistics, BPM trend
    chart, blood sugar & blood pressure charts, alert history, and doctor notes.
    """
    session = await crud.get_session(db, session_id)
    if not session:
        raise NotFoundError(f"Session '{session_id}' not found.")

    patient = await crud.get_patient(db, session.patient_id)
    if not patient:
        raise NotFoundError(f"Patient '{session.patient_id}' not found.")

    alerts                = await crud.get_alerts(db, session.patient_id, limit=100)
    weekly_health         = await crud.get_latest_weekly_health(db, session.patient_id)
    doctor_notes          = await crud.get_doctor_notes(db, session.patient_id)
    heart_rate_history    = await crud.get_heart_rate_history(db, session.patient_id, limit=60)
    weekly_health_history = await crud.get_weekly_health_history(db, session.patient_id, limit=12)

    pdf_bytes = report_service.generate_session_report(
        patient               = patient,
        session               = session,
        alerts                = list(alerts),
        weekly_health         = weekly_health,
        doctor_notes          = list(doctor_notes),
        heart_rate_history    = list(heart_rate_history),
        weekly_health_history = list(weekly_health_history),
    )

    filename = f"ecg_report_{session_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

