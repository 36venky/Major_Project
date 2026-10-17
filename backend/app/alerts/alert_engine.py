"""
alerts/alert_engine.py
───────────────────────
Rule-based alert engine.

Evaluates processed ECG metrics and generates structured alerts.
Alerts are deduplicated using a cooldown window to prevent floods.

Cooldown design
───────────────
AlertEngine keeps a per-alert-type cooldown (default 60 s).  This prevents
the analysis loop (runs every 2 s) from firing the same alert hundreds of
times in a single session.

A separate, longer cooldown (default 300 s = 5 min) lives in
TwilioWhatsAppService._last_sent and gates *WhatsApp dispatch*.  The two
cooldowns are independent so that:
  • The alert is still logged to the DB on every AlertEngine fire.
  • WhatsApp is only sent once per 5-minute window regardless of how many
    AlertEngine fires happened within that window.

Cooldown persistence
────────────────────
Both cooldown dicts are in-process memory.  They reset on:
  • AlertEngine  : when a new monitoring session opens (start_monitoring) — an
                   intentional reset so a new session can send its first alert.
  • TwilioService: only on backend restart — survives session restarts so
                   guardians are not spammed even if the user starts/stops
                   monitoring rapidly.

Alert types:
  HIGH_HR          – BPM above warning threshold
  CRITICAL_HR      – BPM above critical threshold
  LOW_HR           – BPM below warning threshold
  CRITICAL_LOW_HR  – BPM below critical threshold
  IRREGULAR_RHYTHM – Possible arrhythmia
  POOR_SIGNAL      – Signal quality below warning threshold
  DEVICE_DISCONNECT– WiFi device lost connection
  LEAD_OFF         – Flatline detected (electrode disconnected)
  VENTRICULAR_BEAT – XGBoost detected Ventricular ectopic beat (High risk)
  HIGH_RISK_SCORE  – XGBoost composite risk score ≥ 45 / 100
"""

from __future__ import annotations

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
        on_alert:         Callback invoked when a new alert fires.
                          Signature: (event: AlertEvent) -> None
        cooldown_seconds: Minimum seconds between repeated alerts of the
                          same type within one monitoring session (default 60 s).
                          This is the *engine-level* cooldown — it prevents the
                          DB from being flooded with duplicate alert rows.
                          The separate Twilio-level cooldown (5 min) controls
                          WhatsApp dispatch independently.
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

        logger.info(
            "AlertEngine created for patient=%s  engine_cooldown=%ds",
            patient_id, cooldown_seconds,
        )

    # ── Cooldown helpers ──────────────────────────────────

    def _should_fire(self, alert_type: str) -> bool:
        """Return True if the engine-level cooldown has passed for this alert type."""
        last = self._last_fired.get(alert_type)
        if last is None:
            return True
        elapsed = (datetime.now(timezone.utc) - last).total_seconds()
        remaining = self._cooldown.total_seconds() - elapsed
        if remaining > 0:
            logger.debug(
                "AlertEngine cooldown active: type=%s  remaining=%.0fs",
                alert_type, remaining,
            )
            return False
        return True

    def _fire(self, event: AlertEvent) -> None:
        """Record fire time and invoke the callback."""
        self._last_fired[event.alert_type] = event.timestamp
        logger.info(
            "[ALERT FIRED] %s | %s | patient=%s | %s",
            event.severity.upper(), event.alert_type,
            event.patient_id, event.message[:120],
        )
        self._on_alert(event)

    def cooldown_status(self) -> dict[str, float]:
        """
        Return remaining cooldown seconds for every alert type that has fired.
        Useful for debug endpoints or log summaries.
        """
        now = datetime.now(timezone.utc)
        return {
            k: max(0.0, round(self._cooldown.total_seconds() - (now - v).total_seconds(), 1))
            for k, v in self._last_fired.items()
        }

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

        Called from ECGService._analysis_loop() every 2 seconds while
        recording is active.  Each check is gated by the engine-level
        cooldown before the callback (and therefore Twilio) is invoked.
        """
        self._check_heart_rate(bpm)
        self._check_signal_quality(quality)
        self._check_arrhythmia(arrhythmia)
        if not device_connected:
            self._check_device(device_connected)

    def _check_heart_rate(self, bpm: float) -> None:
        if bpm <= 0:
            return

        # Critical thresholds take priority — suppress warning if critical fires
        if bpm >= settings.HR_CRITICAL_HIGH:
            if self._should_fire("CRITICAL_HR"):
                self._fire(AlertEvent(
                    alert_type="CRITICAL_HR",
                    severity="critical",
                    message=(
                        f"Critical tachycardia: {bpm:.0f} BPM "
                        f"(≥{settings.HR_CRITICAL_HIGH}). Immediate attention required."
                    ),
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
                    message=(
                        f"Critical bradycardia: {bpm:.0f} BPM "
                        f"(≤{settings.HR_CRITICAL_LOW}). Immediate attention required."
                    ),
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
                    message=(
                        f"Poor signal quality ({quality.score}%). "
                        f"{quality.reason or 'Check electrode contact.'}"
                    ),
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
                    message=(
                        f"Irregular rhythm detected: {arrhythmia.rhythm}. "
                        f"{arrhythmia.details}"
                    ),
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

    # ── XGBoost risk alerts ───────────────────────────────

    def check_xgboost_risk(self, risk: dict) -> None:
        """
        Evaluate the XGBoost prediction result dict (from PredictionService)
        and fire alerts when warranted.

        Called from ECGService._analysis_loop() after every successful
        2-second prediction window.

        Fires:
          VENTRICULAR_BEAT  (critical) — majority_label == "V"
          HIGH_RISK_SCORE   (warning)  — composite risk_score ≥ 45
        """
        if not risk:
            return

        majority    = risk.get("majority_label", "N")
        risk_score  = risk.get("risk_score",     0)
        risk_label  = risk.get("risk_label",     "Low")
        xgb_bpm     = risk.get("xgb_bpm",        0.0)
        confidence  = risk.get("confidence",     0.0)
        sdnn_ms     = risk.get("sdnn_ms",        0.0)
        rmssd_ms    = risk.get("rmssd_ms",       0.0)
        abn_pct     = risk.get("abnormal_pct",   0.0)

        # ── Ventricular ectopic beat detected ─────────────
        if majority == "V" and self._should_fire("VENTRICULAR_BEAT"):
            self._fire(AlertEvent(
                alert_type="VENTRICULAR_BEAT",
                severity="critical",
                message=(
                    f"⚠️ Ventricular ectopic beat detected by XGBoost.\n"
                    f"BPM: {xgb_bpm:.1f}  |  Confidence: {confidence:.1f}%  |  "
                    f"Risk Score: {risk_score}/100 [{risk_label}]\n"
                    f"HRV — SDNN: {sdnn_ms:.1f} ms  |  RMSSD: {rmssd_ms:.1f} ms\n"
                    f"Abnormal Beats: {abn_pct:.1f}%\n"
                    f"[PROTOTYPE — not a clinical diagnosis]"
                ),
                patient_id=self._patient_id,
            ))

        # ── High composite risk score ──────────────────────
        if (risk_score >= 45
                and risk_label in ("High", "Critical")
                and self._should_fire("HIGH_RISK_SCORE")):
            self._fire(AlertEvent(
                alert_type="HIGH_RISK_SCORE",
                severity="warning" if risk_label == "High" else "critical",
                message=(
                    f"⚠️ Elevated XGBoost risk score: {risk_score}/100 [{risk_label}].\n"
                    f"Beat: {risk.get('beat_type', majority)}  |  "
                    f"Confidence: {confidence:.1f}%\n"
                    f"BPM: {xgb_bpm:.1f}  |  Abnormal Beats: {abn_pct:.1f}%\n"
                    f"HRV — SDNN: {sdnn_ms:.1f} ms  |  RMSSD: {rmssd_ms:.1f} ms\n"
                    f"[PROTOTYPE — not a clinical diagnosis]"
                ),
                patient_id=self._patient_id,
            ))
