"""
alerts/alert_engine.py
───────────────────────
Rule-based alert engine.

Evaluates processed ECG metrics and generates structured alerts.
Alerts are deduplicated using a cooldown window to prevent floods.

Alert types:
  HIGH_HR          – BPM above warning threshold
  CRITICAL_HR      – BPM above critical threshold
  LOW_HR           – BPM below warning threshold
  CRITICAL_LOW_HR  – BPM below critical threshold
  IRREGULAR_RHYTHM – Possible arrhythmia
  POOR_SIGNAL      – Signal quality below warning threshold
  DEVICE_DISCONNECT– COM port lost connection
  LEAD_OFF         – Flatline detected (electrode disconnected)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from app.core.config import settings
from app.core.logger import get_logger
from app.processing.arrhythmia import ArrhythmiaResult
from app.processing.signal_quality import SignalQualityResult

logger = get_logger("alerts")


# ── Alert data class ──────────────────────────────────────

class AlertEvent:
    """In-memory alert event before DB persistence."""

    __slots__ = ("alert_type", "severity", "message", "timestamp", "patient_id")

    def __init__(
        self,
        alert_type: str,
        severity:   str,
        message:    str,
        patient_id: str,
    ):
        self.alert_type = alert_type
        self.severity   = severity
        self.message    = message
        self.patient_id = patient_id
        self.timestamp  = datetime.now(timezone.utc)


# ── Alert engine ──────────────────────────────────────────

class AlertEngine:
    """
    Stateful alert evaluator with per-type cooldown deduplication.

    Args:
        patient_id:       The patient being monitored.
        on_alert:         Async callback invoked when a new alert fires.
                          Signature: async (event: AlertEvent) -> None
        cooldown_seconds: Minimum seconds between repeated alerts of the same type.
    """

    def __init__(
        self,
        patient_id: str,
        on_alert: Callable[[AlertEvent], None],
        cooldown_seconds: int = 60,
    ):
        self._patient_id      = patient_id
        self._on_alert        = on_alert
        self._cooldown        = timedelta(seconds=cooldown_seconds)
        self._last_fired: dict[str, datetime] = {}

    def _should_fire(self, alert_type: str) -> bool:
        """Return True if the cooldown window has passed for this alert type."""
        last = self._last_fired.get(alert_type)
        if last is None:
            return True
        return (datetime.now(timezone.utc) - last) >= self._cooldown

    def _fire(self, event: AlertEvent) -> None:
        """Record fire time and invoke the callback."""
        self._last_fired[event.alert_type] = event.timestamp
        logger.info("[ALERT] %s | %s | %s", event.severity.upper(), event.alert_type, event.message)
        self._on_alert(event)

    # ── Public evaluate API ───────────────────────────────

    def evaluate(
        self,
        bpm: float,
        quality: SignalQualityResult,
        arrhythmia: Optional[ArrhythmiaResult],
        device_connected: bool,
    ) -> None:
        """
        Evaluate current metrics and fire alerts as needed.

        Args:
            bpm:              Current heart rate.
            quality:          Signal quality assessment result.
            arrhythmia:       Arrhythmia classification result.
            device_connected: Whether the serial device is connected.
        """
        self._check_heart_rate(bpm)
        self._check_signal_quality(quality)
        self._check_arrhythmia(arrhythmia)
        if not device_connected:
            self._check_device(device_connected)

    def _check_heart_rate(self, bpm: float) -> None:
        if bpm <= 0:
            return

        if bpm >= settings.HR_CRITICAL_HIGH:
            if self._should_fire("CRITICAL_HR"):
                self._fire(AlertEvent(
                    alert_type="CRITICAL_HR",
                    severity="critical",
                    message=f"Critical tachycardia: {bpm:.0f} BPM (≥{settings.HR_CRITICAL_HIGH}). Immediate attention required.",
                    patient_id=self._patient_id,
                ))
        elif bpm >= settings.HR_HIGH:
            if self._should_fire("HIGH_HR"):
                self._fire(AlertEvent(
                    alert_type="HIGH_HR",
                    severity="warning",
                    message=f"High heart rate: {bpm:.0f} BPM (normal ≤{settings.HR_HIGH}).",
                    patient_id=self._patient_id,
                ))

        if bpm <= settings.HR_CRITICAL_LOW:
            if self._should_fire("CRITICAL_LOW_HR"):
                self._fire(AlertEvent(
                    alert_type="CRITICAL_LOW_HR",
                    severity="critical",
                    message=f"Critical bradycardia: {bpm:.0f} BPM (≤{settings.HR_CRITICAL_LOW}). Immediate attention required.",
                    patient_id=self._patient_id,
                ))
        elif bpm <= settings.HR_LOW:
            if self._should_fire("LOW_HR"):
                self._fire(AlertEvent(
                    alert_type="LOW_HR",
                    severity="warning",
                    message=f"Low heart rate: {bpm:.0f} BPM (normal ≥{settings.HR_LOW}).",
                    patient_id=self._patient_id,
                ))

    def _check_signal_quality(self, quality: SignalQualityResult) -> None:
        if quality.is_flatline:
            if self._should_fire("LEAD_OFF"):
                self._fire(AlertEvent(
                    alert_type="LEAD_OFF",
                    severity="critical",
                    message="Flatline detected. Electrode may be disconnected (lead-off).",
                    patient_id=self._patient_id,
                ))
        elif quality.score < settings.SIGNAL_QUALITY_POOR:
            if self._should_fire("POOR_SIGNAL"):
                self._fire(AlertEvent(
                    alert_type="POOR_SIGNAL",
                    severity="warning",
                    message=f"Poor signal quality ({quality.score}%). {quality.reason or 'Check electrode contact.'}",
                    patient_id=self._patient_id,
                ))

    def _check_arrhythmia(self, arrhythmia: Optional[ArrhythmiaResult]) -> None:
        if arrhythmia is None or not arrhythmia.is_abnormal:
            return
        if "IRREGULAR_RR" in arrhythmia.flags:
            if self._should_fire("IRREGULAR_RHYTHM"):
                self._fire(AlertEvent(
                    alert_type="IRREGULAR_RHYTHM",
                    severity="warning",
                    message=f"Irregular rhythm detected: {arrhythmia.rhythm}. {arrhythmia.details}",
                    patient_id=self._patient_id,
                ))

    def _check_device(self, connected: bool) -> None:
        if not connected and self._should_fire("DEVICE_DISCONNECT"):
            self._fire(AlertEvent(
                alert_type="DEVICE_DISCONNECT",
                severity="critical",
                message="ESP32 device disconnected (WiFi).",
                patient_id=self._patient_id,
            ))
