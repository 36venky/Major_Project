"""
services/report_service.py
───────────────────────────
PDF report generation using ReportLab.

Generates a clinical-style patient monitoring report including:
  - Patient demographics
  - Session summary (BPM statistics)
  - BPM trend line chart (from HeartRate history)
  - Blood Sugar & Blood Pressure trend line charts (from WeeklyHealth history)
  - Alert history table
  - Weekly health values table
  - Doctor notes
"""

from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from typing import Sequence

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable, Paragraph, SimpleDocTemplate,
    Spacer, Table, TableStyle,
)

# ReportLab graphics (line charts)
from reportlab.graphics.shapes import Drawing, String
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.widgets.markers import makeMarker
from reportlab.graphics import renderPDF

from app.core.logger import get_logger
from app.database.models import Alert, ECGSession, HeartRate, Patient, WeeklyHealth

logger = get_logger("app.report_service")

# ── Colour palette ─────────────────────────────────────────
BLUE      = colors.HexColor("#1d4ed8")
LIGHT_BG  = colors.HexColor("#f8fafc")
BORDER    = colors.HexColor("#e2e8f0")
GREEN     = colors.HexColor("#059669")
RED       = colors.HexColor("#dc2626")
AMBER     = colors.HexColor("#d97706")
PURPLE    = colors.HexColor("#7c3aed")
TEXT_DARK = colors.HexColor("#1e293b")
TEXT_MUTE = colors.HexColor("#64748b")

PAGE_W = A4[0] - 4 * cm   # usable width (left+right margins = 2+2 cm)


# ── Helpers ────────────────────────────────────────────────

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


def _parse_numeric(value: str | None) -> float | None:
    """Extract the first number from a health string, e.g. '98 mg/dL' → 98.0."""
    if not value:
        return None
    m = re.search(r"[\d.]+", value)
    return float(m.group()) if m else None


def _parse_bp_systolic(value: str | None) -> float | None:
    """Extract systolic from '120/80 mmHg' → 120.0."""
    if not value:
        return None
    m = re.match(r"([\d.]+)\s*/", value.strip())
    return float(m.group(1)) if m else _parse_numeric(value)


# ── Chart builders ─────────────────────────────────────────

def _bpm_chart(heart_rates: Sequence[HeartRate], width: float = PAGE_W) -> Drawing | None:
    """Return a ReportLab Drawing of the BPM trend, or None if no data."""
    # Take last 60 readings, oldest first
    hrs = list(heart_rates)[-60:]
    if len(hrs) < 2:
        return None

    data = [float(h.bpm) for h in hrs]
    xs   = list(range(len(data)))
    y_min = max(0, min(data) - 10)
    y_max = max(data) + 10

    height = 120
    d = Drawing(width, height + 30)

    chart = HorizontalLineChart()
    chart.x      = 40
    chart.y      = 20
    chart.width  = width - 55
    chart.height = height
    chart.data   = [data]

    chart.categoryAxis.categoryNames   = [
        hrs[i].timestamp.strftime("%H:%M") if i % max(1, len(hrs) // 6) == 0 else ""
        for i in range(len(hrs))
    ]
    chart.categoryAxis.labels.fontSize  = 6
    chart.categoryAxis.labels.angle     = 30
    chart.categoryAxis.labels.boxAnchor = "ne"

    chart.valueAxis.valueMin    = y_min
    chart.valueAxis.valueMax    = y_max
    chart.valueAxis.valueStep   = max(5, round((y_max - y_min) / 5 / 5) * 5)
    chart.valueAxis.labels.fontSize = 6

    chart.lines[0].strokeColor = GREEN
    chart.lines[0].strokeWidth = 1.5

    d.add(chart)

    # Title
    d.add(String(width / 2, height + 25, "Heart Rate Trend (BPM)",
                 fontSize=9, fillColor=TEXT_DARK,
                 textAnchor="middle", fontName="Helvetica-Bold"))
    return d


def _health_chart(
    history: Sequence[WeeklyHealth],
    extractor,
    title: str,
    line_color: colors.Color,
    unit: str,
    width: float = PAGE_W / 2 - 0.5 * cm,
) -> Drawing | None:
    """Return a small line chart for a single health metric over time."""
    entries = [(h.date, extractor(h)) for h in history if extractor(h) is not None]
    entries.sort(key=lambda x: x[0])  # oldest first
    if len(entries) < 2:
        return None

    dates, values = zip(*entries)
    y_min = max(0, min(values) - 10)
    y_max = max(values) + 10

    height = 90
    d = Drawing(width, height + 30)

    chart = HorizontalLineChart()
    chart.x      = 38
    chart.y      = 18
    chart.width  = width - 50
    chart.height = height
    chart.data   = [list(values)]

    labels = [d.strftime("%d/%m") for d in dates]
    chart.categoryAxis.categoryNames   = labels
    chart.categoryAxis.labels.fontSize  = 6
    chart.categoryAxis.labels.angle     = 30
    chart.categoryAxis.labels.boxAnchor = "ne"

    chart.valueAxis.valueMin  = y_min
    chart.valueAxis.valueMax  = y_max
    chart.valueAxis.valueStep = max(5, round((y_max - y_min) / 4 / 5) * 5)
    chart.valueAxis.labels.fontSize = 6

    chart.lines[0].strokeColor = line_color
    chart.lines[0].strokeWidth = 1.5

    d.add(chart)
    d.add(String(width / 2, height + 24,
                 f"{title}  ({unit})",
                 fontSize=8, fillColor=TEXT_DARK,
                 textAnchor="middle", fontName="Helvetica-Bold"))
    return d


# ── Main report generator ──────────────────────────────────

def generate_session_report(
    patient:        Patient,
    session:        ECGSession,
    alerts:         list[Alert],
    weekly_health:  WeeklyHealth | None,
    doctor_notes:   list,
    heart_rate_history:   Sequence[HeartRate]    = (),
    weekly_health_history: Sequence[WeeklyHealth] = (),
) -> bytes:
    """
    Generate a PDF monitoring report for a single ECG session.

    Args:
        patient:               Patient ORM record.
        session:               ECGSession ORM record.
        alerts:                Alert records for this session.
        weekly_health:         Latest WeeklyHealth record (may be None).
        doctor_notes:          DoctorNote records.
        heart_rate_history:    Recent HeartRate readings (for BPM chart).
        weekly_health_history: Historical WeeklyHealth rows (for BP/Sugar charts).

    Returns:
        PDF content as bytes.
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
        "title", parent=styles["Heading1"],
        fontSize=18, textColor=colors.white, spaceAfter=4,
    )
    sub_style = ParagraphStyle(
        "sub", parent=styles["Normal"],
        fontSize=9, textColor=colors.HexColor("#bfdbfe"),
    )
    header_data = [[
        Paragraph("ECG Guardian", title_style),
        Paragraph("AI-Based Patient Monitoring Report", sub_style),
    ]]
    header_table = Table(header_data, colWidths=["40%", "60%"])
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BLUE),
        ("ROWPADDING", (0, 0), (-1, -1), 12),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph(
        f"Generated: {_fmt_dt(datetime.now(timezone.utc))}&nbsp;&nbsp; "
        f"Session: {session.session_id}",
        ParagraphStyle("meta", parent=styles["Normal"], fontSize=8, textColor=TEXT_MUTE),
    ))
    story.append(Spacer(1, 0.6 * cm))

    # ── Section / table helpers ───────────────────────────

    def section(title: str) -> None:
        story.append(HRFlowable(width="100%", thickness=1, color=BORDER))
        story.append(Spacer(1, 0.2 * cm))
        story.append(Paragraph(title, ParagraphStyle(
            "sec_title", parent=styles["Heading3"],
            fontSize=11, textColor=BLUE, spaceAfter=6,
        )))

    def info_table(rows: list[tuple[str, str]]) -> None:
        data = [
            [
                Paragraph(k, ParagraphStyle("k", parent=styles["Normal"],
                                            fontSize=9, textColor=TEXT_MUTE)),
                Paragraph(str(v), ParagraphStyle("v", parent=styles["Normal"],
                                                 fontSize=9, textColor=TEXT_DARK)),
            ]
            for k, v in rows
        ]
        t = Table(data, colWidths=["35%", "65%"])
        t.setStyle(TableStyle([
            ("ROWPADDING",    (0, 0), (-1, -1), 5),
            ("ROWBACKGROUNDS",(0, 0), (-1, -1), [LIGHT_BG, colors.white]),
            ("GRID",          (0, 0), (-1, -1), 0.5, BORDER),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
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
        ("Doctor Contact",    getattr(patient, "doctor_phone", None) or "—"),
        ("Ambulance",         getattr(patient, "ambulance_phone", None) or "—"),
    ])

    # ── Session summary ───────────────────────────────────
    section("Monitoring Session Summary")
    info_table([
        ("Session ID",  session.session_id),
        ("Start Time",  _fmt_dt(session.start_time)),
        ("End Time",    _fmt_dt(session.end_time)),
        ("Duration",    session.duration or "—"),
        ("Average BPM", f"{session.average_bpm:.1f}" if session.average_bpm else "—"),
        ("Maximum BPM", f"{session.maximum_bpm:.1f}" if session.maximum_bpm else "—"),
        ("Minimum BPM", f"{session.minimum_bpm:.1f}" if session.minimum_bpm else "—"),
    ])

    # ── BPM trend chart ───────────────────────────────────
    if heart_rate_history:
        section("Heart Rate Trend")
        bpm_drawing = _bpm_chart(heart_rate_history, width=PAGE_W)
        if bpm_drawing:
            story.append(bpm_drawing)
            story.append(Spacer(1, 0.4 * cm))
        else:
            story.append(Paragraph(
                "Insufficient heart rate data to render chart.",
                ParagraphStyle("nd", parent=styles["Normal"], fontSize=8, textColor=TEXT_MUTE),
            ))
            story.append(Spacer(1, 0.3 * cm))

    # ── Weekly health values ──────────────────────────────
    if weekly_health:
        section("Latest Health Values")
        info_table([
            ("Blood Pressure", weekly_health.blood_pressure or "—"),
            ("Blood Sugar",    weekly_health.blood_sugar    or "—"),
            ("Weight",         weekly_health.weight         or "—"),
            ("Last Updated",   _fmt_dt(weekly_health.date)),
            ("Updated By",     weekly_health.updated_by     or "—"),
        ])

    # ── Blood Sugar & Blood Pressure trend charts ─────────
    if weekly_health_history and len(list(weekly_health_history)) >= 2:
        section("Health Metrics Trend")
        col_w = PAGE_W / 2 - 0.3 * cm

        sugar_d = _health_chart(
            weekly_health_history,
            extractor=lambda h: _parse_numeric(h.blood_sugar),
            title="Blood Sugar",
            line_color=AMBER,
            unit="mg/dL",
            width=col_w,
        )
        bp_d = _health_chart(
            weekly_health_history,
            extractor=lambda h: _parse_bp_systolic(h.blood_pressure),
            title="Blood Pressure (Systolic)",
            line_color=PURPLE,
            unit="mmHg",
            width=col_w,
        )

        if sugar_d or bp_d:
            # Side-by-side in a two-column table
            left  = sugar_d  if sugar_d else Paragraph("No blood sugar data.", styles["Normal"])
            right = bp_d     if bp_d    else Paragraph("No blood pressure data.", styles["Normal"])
            chart_row = Table([[left, right]], colWidths=[col_w, col_w])
            chart_row.setStyle(TableStyle([
                ("VALIGN",     (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING",(0, 0), (-1, -1), 4),
                ("RIGHTPADDING",(0, 0), (-1, -1), 4),
            ]))
            story.append(chart_row)
            story.append(Spacer(1, 0.5 * cm))
        else:
            story.append(Paragraph(
                "Insufficient health metric data to render charts.",
                ParagraphStyle("nd", parent=styles["Normal"], fontSize=8, textColor=TEXT_MUTE),
            ))
            story.append(Spacer(1, 0.3 * cm))

    # ── Alerts ────────────────────────────────────────────
    section(f"Alerts  ({len(alerts)} total)")
    if alerts:
        alert_data = [["Time", "Type", "Severity", "Message", "Resolved"]]
        for a in alerts:
            alert_data.append([
                _fmt_dt(a.timestamp),
                a.alert_type,
                a.severity.upper(),
                Paragraph(a.message, ParagraphStyle(
                    "am", parent=styles["Normal"], fontSize=7)),
                "Yes" if a.resolved else "No",
            ])
        at = Table(alert_data, colWidths=["18%", "15%", "10%", "47%", "10%"])
        at.setStyle(TableStyle([
            ("BACKGROUND",     (0, 0), (-1, 0),  BLUE),
            ("TEXTCOLOR",      (0, 0), (-1, 0),  colors.white),
            ("FONTSIZE",       (0, 0), (-1, -1), 7),
            ("ROWPADDING",     (0, 0), (-1, -1), 4),
            ("GRID",           (0, 0), (-1, -1), 0.5, BORDER),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [LIGHT_BG, colors.white]),
        ]))
        story.append(at)
    else:
        story.append(Paragraph(
            "No alerts were generated during this session.",
            styles["Normal"],
        ))
    story.append(Spacer(1, 0.4 * cm))

    # ── Doctor notes ──────────────────────────────────────
    if doctor_notes:
        section("Doctor Notes")
        for note in doctor_notes:
            story.append(Paragraph(
                f"<b>{note.doctor}</b>  –  {_fmt_dt(note.timestamp)}",
                ParagraphStyle("dn_hdr", parent=styles["Normal"],
                               fontSize=9, textColor=TEXT_MUTE),
            ))
            story.append(Paragraph(note.note, styles["Normal"]))
            story.append(Spacer(1, 0.3 * cm))

    # ── Footer ────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=1, color=BORDER))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(
        "ECG Guardian – Educational Prototype. Not for clinical use without physician supervision.",
        ParagraphStyle("footer", parent=styles["Normal"],
                       fontSize=7, textColor=TEXT_MUTE, alignment=1),
    ))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    logger.info(
        "PDF report generated for session %s (%d bytes)", session.session_id, len(pdf_bytes)
    )
    return pdf_bytes
