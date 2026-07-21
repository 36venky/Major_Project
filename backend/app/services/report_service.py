"""
services/report_service.py
───────────────────────────
PDF report generation using ReportLab.

Generates a clinical-style patient monitoring report including:
  - Patient demographics
  - Session summary (BPM statistics)
  - Alert history
  - Weekly health values
  - Doctor notes
"""

from __future__ import annotations

import io
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable, Paragraph, SimpleDocTemplate,
    Spacer, Table, TableStyle,
)

from app.core.logger import get_logger
from app.database.models import Alert, ECGSession, Patient, WeeklyHealth

logger = get_logger("app.report_service")

# ── Colour palette ─────────────────────────────────────────
BLUE      = colors.HexColor("#1d4ed8")
LIGHT_BG  = colors.HexColor("#f8fafc")
BORDER    = colors.HexColor("#e2e8f0")
GREEN     = colors.HexColor("#059669")
RED       = colors.HexColor("#dc2626")
AMBER     = colors.HexColor("#d97706")
TEXT_DARK = colors.HexColor("#1e293b")
TEXT_MUTE = colors.HexColor("#64748b")


def _fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return dt.strftime("%d %b %Y  %I:%M %p")


def _severity_color(severity: str) -> colors.HexColor:
    return {
        "critical": RED,
        "warning":  AMBER,
        "info":     BLUE,
    }.get(severity.lower(), TEXT_MUTE)


def generate_session_report(
    patient: Patient,
    session: ECGSession,
    alerts: list[Alert],
    weekly_health: WeeklyHealth | None,
    doctor_notes: list,
) -> bytes:
    """
    Generate a PDF monitoring report for a single ECG session.

    Args:
        patient:       Patient ORM record.
        session:       ECGSession ORM record.
        alerts:        List of Alert records for this session.
        weekly_health: Latest WeeklyHealth record (may be None).
        doctor_notes:  List of DoctorNote records.

    Returns:
        PDF content as bytes (ready for HTTP response).
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    story  = []

    # ── Title header ──────────────────────────────────────
    title_style = ParagraphStyle(
        "title",
        parent=styles["Heading1"],
        fontSize=18,
        textColor=colors.white,
        spaceAfter=4,
    )
    sub_style = ParagraphStyle(
        "sub",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#bfdbfe"),
    )

    header_data = [[
        Paragraph("ECG Guardian", title_style),
        Paragraph("AI-Based Patient Monitoring Report", sub_style),
    ]]
    header_table = Table(header_data, colWidths=["40%", "60%"])
    header_table.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, -1), BLUE),
        ("ROWPADDING",  (0, 0), (-1, -1), 12),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 0.4 * cm))

    # Report metadata
    story.append(Paragraph(
        f"Generated: {_fmt_dt(datetime.now(timezone.utc))}   &nbsp;&nbsp;  Session: {session.session_id}",
        ParagraphStyle("meta", parent=styles["Normal"], fontSize=8, textColor=TEXT_MUTE)
    ))
    story.append(Spacer(1, 0.6 * cm))

    # ── Section helper ────────────────────────────────────

    def section(title: str):
        story.append(HRFlowable(width="100%", thickness=1, color=BORDER))
        story.append(Spacer(1, 0.2 * cm))
        story.append(Paragraph(title, ParagraphStyle(
            "sec_title", parent=styles["Heading3"],
            fontSize=11, textColor=BLUE, spaceAfter=6,
        )))

    def info_table(rows: list[tuple[str, str]]):
        data = [[Paragraph(k, ParagraphStyle("k", parent=styles["Normal"], fontSize=9, textColor=TEXT_MUTE)),
                 Paragraph(str(v), ParagraphStyle("v", parent=styles["Normal"], fontSize=9, textColor=TEXT_DARK))]
                for k, v in rows]
        t = Table(data, colWidths=["35%", "65%"])
        t.setStyle(TableStyle([
            ("ROWPADDING",  (0, 0), (-1, -1), 5),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [LIGHT_BG, colors.white]),
            ("GRID",        (0, 0), (-1, -1), 0.5, BORDER),
            ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(t)
        story.append(Spacer(1, 0.4 * cm))

    # ── Patient information ───────────────────────────────
    section("Patient Information")
    info_table([
        ("Name",              patient.name),
        ("Patient ID",        patient.patient_id),
        ("Age",               f"{patient.age} years"),
        ("Gender",            patient.gender),
        ("Blood Group",       patient.blood_group),
        ("Height",            patient.height or "—"),
        ("Weight",            patient.weight or "—"),
        ("Guardian",          patient.guardian_name or "—"),
        ("Emergency Contact", patient.guardian_phone or "—"),
    ])

    # ── Session summary ───────────────────────────────────
    section("Monitoring Session Summary")
    info_table([
        ("Session ID",    session.session_id),
        ("Start Time",    _fmt_dt(session.start_time)),
        ("End Time",      _fmt_dt(session.end_time)),
        ("Duration",      session.duration or "—"),
        ("Average BPM",   f"{session.average_bpm:.1f}" if session.average_bpm else "—"),
        ("Maximum BPM",   f"{session.maximum_bpm:.1f}" if session.maximum_bpm else "—"),
        ("Minimum BPM",   f"{session.minimum_bpm:.1f}" if session.minimum_bpm else "—"),
    ])

    # ── Weekly health ─────────────────────────────────────
    if weekly_health:
        section("Latest Health Values")
        info_table([
            ("Blood Pressure", weekly_health.blood_pressure or "—"),
            ("Blood Sugar",    weekly_health.blood_sugar    or "—"),
            ("Weight",         weekly_health.weight         or "—"),
            ("Last Updated",   _fmt_dt(weekly_health.date)),
            ("Updated By",     weekly_health.updated_by     or "—"),
        ])

    # ── Alerts ────────────────────────────────────────────
    section(f"Alerts  ({len(alerts)} total)")
    if alerts:
        alert_data = [["Time", "Type", "Severity", "Message", "Resolved"]]
        for a in alerts:
            alert_data.append([
                _fmt_dt(a.timestamp),
                a.alert_type,
                a.severity.upper(),
                Paragraph(a.message, ParagraphStyle("am", parent=styles["Normal"], fontSize=7)),
                "Yes" if a.resolved else "No",
            ])
        at = Table(alert_data, colWidths=["18%", "15%", "10%", "47%", "10%"])
        at.setStyle(TableStyle([
            ("BACKGROUND",  (0, 0), (-1, 0), BLUE),
            ("TEXTCOLOR",   (0, 0), (-1, 0), colors.white),
            ("FONTSIZE",    (0, 0), (-1, -1), 7),
            ("ROWPADDING",  (0, 0), (-1, -1), 4),
            ("GRID",        (0, 0), (-1, -1), 0.5, BORDER),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [LIGHT_BG, colors.white]),
        ]))
        story.append(at)
    else:
        story.append(Paragraph("No alerts during this session.", styles["Normal"]))
    story.append(Spacer(1, 0.4 * cm))

    # ── Doctor notes ──────────────────────────────────────
    if doctor_notes:
        section("Doctor Notes")
        for note in doctor_notes:
            story.append(Paragraph(
                f"<b>{note.doctor}</b>  –  {_fmt_dt(note.timestamp)}",
                ParagraphStyle("dn_hdr", parent=styles["Normal"], fontSize=9, textColor=TEXT_MUTE)
            ))
            story.append(Paragraph(note.note, styles["Normal"]))
            story.append(Spacer(1, 0.3 * cm))

    # ── Footer ─────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=1, color=BORDER))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(
        "ECG Guardian – Educational Prototype. Not for clinical use without physician supervision.",
        ParagraphStyle("footer", parent=styles["Normal"], fontSize=7, textColor=TEXT_MUTE, alignment=1)
    ))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    logger.info("PDF report generated for session %s (%d bytes)", session.session_id, len(pdf_bytes))
    return pdf_bytes
