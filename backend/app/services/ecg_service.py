"""
services/ecg_service.py
────────────────────────
Core ECG monitoring service.

Data flow (hardware only — simulation removed):
  ESP32 /ws/device  →  WiFiManager._on_sample()
  →  ECGService._on_sample()
  →  always: raw buffer + BPM estimator + WebSocket broadcast (live preview)
  →  only when _storage_enabled=True: DB write + analysis + alert engine

Two-phase operation
───────────────────
Phase 1 — "preview" (hardware connected, user has NOT clicked Start):
  • Raw ADC samples fill _raw_buffer
  • _broadcast_loop streams live ECG frames to the frontend
  • _analysis_loop runs arrhythmia detection + XGBoost predictions
  • Nothing is written to the DB; alert engine does NOT fire

Phase 2 — "recording" (user clicked Start on the dashboard):
  • start_monitoring() opens a DB session and sets _storage_enabled = True
  • _on_sample now also appends to _pending_samples
  • _db_flush_loop batches samples to DB every second
  • Alert engine and WhatsApp notifications become active
  • stop_monitoring() closes the session and sets _storage_enabled = False

When no ESP32 is connected the broadcast loop sends a "no_data" status frame
to all connected frontend clients every second so the UI can show
"Hardware not connected" instead of stale or empty charts.
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from datetime import datetime, timezone
from typing import Optional, Set

import numpy as np
from fastapi import WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.alert_engine import AlertEngine, AlertEvent
from app.alerts.notification import NotificationDispatcher
from app.core.config import settings
from app.core.logger import get_logger
from app.database import crud
from app.database.database import AsyncSessionLocal
from app.database.schemas import WSPayload
from app.processing.arrhythmia import ArrhythmiaResult, classify
from app.processing.heart_rate import RollingBPMEstimator
from app.processing.signal_filter import full_filter_pipeline
from app.processing.signal_quality import SignalQualityResult, assess_signal_quality
from app.serial.wifi_manager import WiFiManager

logger = get_logger("app.ecg_service")

_ANALYSIS_WINDOW    = 5       # seconds of data for full analysis
_DB_FLUSH_INTERVAL  = 1.0     # seconds between DB batch writes
_NO_DATA_INTERVAL   = 1.0     # seconds between "no data" status frames
_BROADCAST_INTERVAL = settings.WS_BROADCAST_INTERVAL


class ECGService:
    """Singleton service that manages the ECG monitoring pipeline."""

    def __init__(self):
        self._patient_id:      Optional[str] = None   # set after first patient is loaded
        self._session_id:      Optional[str] = None
        self._is_monitoring:   bool          = False

        # ── Storage gate ──────────────────────────────────
        # When False: hardware data still flows to _raw_buffer and is broadcast
        # to the frontend for live preview, but nothing is written to the DB and
        # the analysis / alert pipeline does not run.
        # Set to True by start_monitoring(), False by stop_monitoring().
        self._storage_enabled: bool          = False

        self._raw_buffer:      deque[float] = deque(maxlen=settings.SAMPLING_RATE * 10)
        self._pending_samples: list[dict]   = []
        self._bpm_history:     list[float]  = []

        self._bpm_estimator  = RollingBPMEstimator(window_seconds=_ANALYSIS_WINDOW)
        self._alert_engine:  Optional[AlertEngine]  = None
        self._notifier       = NotificationDispatcher()

        self._current_bpm:        float                     = 0.0
        self._current_quality:    Optional[SignalQualityResult] = None
        self._current_arrhythmia: Optional[ArrhythmiaResult]  = None
        self._current_risk:       Optional[dict]            = None

        self._ws_connections: Set[WebSocket] = set()

        self._wifi_manager = WiFiManager(on_sample=self._on_sample)

        self._db_flush_task:   Optional[asyncio.Task] = None
        self._broadcast_task:  Optional[asyncio.Task] = None
        self._analysis_task:   Optional[asyncio.Task] = None
        self._no_data_task:    Optional[asyncio.Task] = None

        self._hardware_ever_connected: bool = False
        # Guard flag: prevents duplicate session-open tasks when many samples
        # arrive before the first asyncio.create_task(_open_session) completes.
        self._opening_session: bool = False

    # ── Lifecycle ──────────────────────────────────────────

    async def start(self) -> None:
        logger.info("ECGService starting…")
        await self._wifi_manager.start()
        self._db_flush_task  = asyncio.create_task(self._db_flush_loop(),  name="db_flush")
        self._broadcast_task = asyncio.create_task(self._broadcast_loop(), name="ws_broadcast")
        self._analysis_task  = asyncio.create_task(self._analysis_loop(),  name="ecg_analysis")
        self._no_data_task   = asyncio.create_task(self._no_data_loop(),   name="no_data_broadcast")
        # NOTE: no session is opened here.  A session is opened only when the
        # user explicitly clicks Start on the dashboard (start_monitoring()).
        # Hardware data still streams to the frontend for live preview.
        logger.info(
            "ECGService started — waiting for ESP32 on /ws/device. "
            "Click Start on the dashboard to begin recording."
        )

    async def stop(self) -> None:
        logger.info("ECGService stopping…")
        if self._session_id:
            await self._close_session()
        await self._wifi_manager.stop()
        for task in (self._db_flush_task, self._broadcast_task,
                     self._analysis_task, self._no_data_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        logger.info("ECGService stopped.")

    # ── Manual Start / Stop ────────────────────────────────

    async def start_monitoring(self) -> dict:
        """
        Called when the user clicks Start on the dashboard.

        Opens a new ECG session in the DB and enables data storage +
        the analysis / alert pipeline.  Hardware must be connected.
        Returns a status dict for the HTTP response.
        """
        if not self._wifi_manager.is_connected:
            logger.warning("start_monitoring called but no ESP32 connected")
            return {"success": False, "message": "No hardware connected — connect ESP32 first."}

        if self._storage_enabled:
            logger.info("start_monitoring: already recording (session=%s)", self._session_id)
            return {"success": True, "message": "Already recording.", "session_id": self._session_id}

        if not self._patient_id:
            logger.warning("start_monitoring called but no patient set")
            return {"success": False, "message": "No patient selected."}

        logger.info("start_monitoring: opening session for patient=%s", self._patient_id)

        # Reset per-patient buffers so the new session starts clean
        self._raw_buffer.clear()
        self._pending_samples.clear()
        self._bpm_history.clear()
        self._bpm_estimator.reset()
        self._current_risk = None
        self._current_bpm  = 0.0
        self._current_quality    = None
        self._current_arrhythmia = None

        # Reset XGBoost streaming state
        from app.services.prediction_service import prediction_service
        prediction_service.reset_patient(self._patient_id)

        # Open DB session first, then enable storage
        await self._open_session(self._patient_id)
        self._storage_enabled = True

        logger.info(
            "Recording started — session=%s  patient=%s",
            self._session_id, self._patient_id,
        )
        return {
            "success":    True,
            "message":    "Recording started.",
            "session_id": self._session_id,
        }

    async def stop_monitoring(self) -> dict:
        """
        Called when the user clicks Stop on the dashboard.

        Flushes any pending samples to the DB, closes the session,
        and disables storage + the analysis pipeline.
        Returns a status dict for the HTTP response.
        """
        if not self._storage_enabled:
            logger.info("stop_monitoring: not currently recording")
            return {"success": True, "message": "Not recording."}

        logger.info("stop_monitoring: closing session=%s", self._session_id)

        # Flush any remaining samples before closing
        if self._pending_samples:
            batch = self._pending_samples.copy()
            self._pending_samples.clear()
            try:
                async with AsyncSessionLocal() as db:
                    await crud.bulk_insert_samples(db, batch)
                    await db.commit()
            except Exception as exc:
                logger.error("Final DB flush error on stop: %s", exc)

        self._storage_enabled = False
        await self._close_session()

        logger.info("Recording stopped.")
        return {"success": True, "message": "Recording stopped."}

    # ── Patient switching ──────────────────────────────────

    async def switch_patient(self, patient_id: str) -> None:
        """Switch the active monitored patient."""
        logger.info("Switching active patient → %s", patient_id)
        if self._session_id:
            try:
                await self._close_session()
            except Exception as exc:
                logger.warning("Could not cleanly close session during switch: %s", exc)
                self._session_id    = None
                self._is_monitoring = False
        self._patient_id = patient_id
        self._storage_enabled = False   # require a new Start click for the new patient
        self._raw_buffer.clear()
        self._pending_samples.clear()
        self._bpm_history.clear()
        self._bpm_estimator.reset()
        self._current_risk = None
        # Reset per-patient XGBoost streaming state
        from app.services.prediction_service import prediction_service
        prediction_service.reset_patient(patient_id)
        # Do NOT auto-open a session — user must click Start again

    # ── Session management ─────────────────────────────────

    async def _open_session(self, patient_id: str) -> None:
        async with AsyncSessionLocal() as db:
            session = await crud.create_session(db, patient_id)
            await db.commit()
            self._session_id = session.session_id
            self._opening_session = False   # allow a new session to be opened after close
            self._bpm_history.clear()
            self._bpm_estimator.reset()
            self._is_monitoring = True
            self._alert_engine = AlertEngine(
                patient_id=patient_id,
                on_alert=self._on_alert,
                cooldown_seconds=60,
            )
        logger.info("ECG session opened: %s  patient=%s", self._session_id, patient_id)
        # Only send WhatsApp if a logged-in user is actively viewing the dashboard.
        # This prevents spam when the backend restarts or the ESP32 reconnects
        # without any user present.
        if self._ws_connections:
            asyncio.create_task(self._notify_monitoring_started(patient_id))
        else:
            logger.info(
                "Monitoring-started WhatsApp suppressed — no frontend users connected"
            )

    async def _close_session(self) -> None:
        if not self._session_id:
            self._is_monitoring = False
            return
        if not self._bpm_history:
            async with AsyncSessionLocal() as db:
                await crud.close_session(db, self._session_id, 0.0, 0.0, 0.0)
                await db.commit()
            self._session_id    = None
            self._opening_session = False
            self._is_monitoring = False
            return
        avg_bpm = float(np.mean(self._bpm_history))
        min_bpm = float(np.min(self._bpm_history))
        max_bpm = float(np.max(self._bpm_history))
        async with AsyncSessionLocal() as db:
            await crud.close_session(db, self._session_id, avg_bpm, min_bpm, max_bpm)
            await db.commit()
        logger.info("Session %s closed  avg=%.1f bpm", self._session_id, avg_bpm)
        self._session_id    = None
        self._opening_session = False
        self._is_monitoring = False

    # ── Sample ingestion ───────────────────────────────────

    def _on_sample(self, value: float) -> None:
        """Called by WiFiManager for every ADC sample from the ESP32."""
        # Log the very first hardware sample we ever see
        if not self._hardware_ever_connected:
            self._hardware_ever_connected = True
            logger.info(
                "First ESP32 sample received (ADC=%.0f) — "
                "hardware streaming to frontend; click Start to record.",
                value,
            )

        # Always fill the ring buffer and feed the BPM estimator so the live
        # ECG preview on the frontend works before the user clicks Start.
        self._raw_buffer.append(value)
        self._bpm_estimator.push(value)

        # Only accumulate samples for DB storage when recording is active.
        if self._storage_enabled and self._session_id:
            self._pending_samples.append({
                "session_id": self._session_id,
                "patient_id": self._patient_id,
                "ecg_value":  value,
                "timestamp":  datetime.now(timezone.utc),
            })

    # ── Background tasks ───────────────────────────────────

    async def _db_flush_loop(self) -> None:
        while True:
            await asyncio.sleep(_DB_FLUSH_INTERVAL)
            # Only flush when recording is active — preview mode does NOT write to DB
            if not self._storage_enabled or not self._pending_samples:
                continue
            batch = self._pending_samples.copy()
            self._pending_samples.clear()
            try:
                async with AsyncSessionLocal() as db:
                    await crud.bulk_insert_samples(db, batch)
                    if self._current_bpm > 0 and self._patient_id:
                        await crud.save_heart_rate(
                            db, self._patient_id, self._current_bpm, self._session_id
                        )
                    await db.commit()
            except Exception as exc:
                logger.error("DB flush error: %s", exc)

    async def _analysis_loop(self) -> None:
        fs     = settings.SAMPLING_RATE
        window = _ANALYSIS_WINDOW * fs

        while True:
            # Run every 2 s to match the XGBoost prediction cadence
            await asyncio.sleep(2)
            # Analysis runs unconditionally when hardware is connected
            # (DB writes and alerts remain gated by _storage_enabled)
            if not self._wifi_manager.is_connected or len(self._raw_buffer) < fs:
                continue
            try:
                arr      = np.array(list(self._raw_buffer)[-window:], dtype=np.float64)
                filtered = full_filter_pipeline(arr, fs=fs)

                self._current_quality = assess_signal_quality(arr, filtered, fs)

                bpm = self._bpm_estimator.get_bpm()
                if bpm > 0:
                    self._current_bpm = bpm
                    self._bpm_history.append(bpm)

                from app.processing.r_peak_detection import detect_r_peaks
                peaks = detect_r_peaks(filtered, fs)
                self._current_arrhythmia = classify(peaks, bpm, fs)

                # Alerts only fire during recording
                if self._storage_enabled and self._alert_engine:
                    self._alert_engine.evaluate(
                        bpm=self._current_bpm,
                        quality=self._current_quality,
                        arrhythmia=self._current_arrhythmia,
                        device_connected=self._wifi_manager.is_connected,
                    )

                from app.services.prediction_service import prediction_service
                risk = await prediction_service.maybe_predict(
                    patient_id=self._patient_id,
                    raw_buffer=self._raw_buffer,
                )
                if risk:
                    self._current_risk = risk
                    # Fire XGBoost-specific alerts (VENTRICULAR_BEAT, HIGH_RISK_SCORE)
                    if self._storage_enabled and self._alert_engine:
                        self._alert_engine.check_xgboost_risk(risk)

            except Exception as exc:
                logger.error("Analysis loop error: %s", exc)

    async def _broadcast_loop(self) -> None:
        """Broadcast live ECG frames to connected frontend WebSocket clients.

        Runs unconditionally — hardware data is always streamed to the frontend
        so the user can verify signal quality before clicking Start.
        DB session state (_storage_enabled) is reported in each frame so the
        UI can show the correct recording indicator.
        """
        while True:
            await asyncio.sleep(_BROADCAST_INTERVAL)
            if not self._ws_connections:
                continue
            if not self._wifi_manager.is_connected or not self._raw_buffer:
                continue   # _no_data_loop handles the "no hardware" case
            try:
                quality    = self._current_quality
                arrhythmia = self._current_arrhythmia
                risk       = self._current_risk   # XGBoost enriched dict or None

                samples_per_frame = max(1, int(settings.SAMPLING_RATE * _BROADCAST_INTERVAL))
                recent = list(self._raw_buffer)[-samples_per_frame:]

                # Build the riskPrediction sub-object once per broadcast tick
                risk_prediction = None
                if risk:
                    risk_prediction = {
                        # backward-compat fields (RiskCard already uses these)
                        "risk_percentage": risk.get("confidence",     0.0),
                        "risk_level":      risk.get("risk_level",     "Low"),
                        "majority_label":  risk.get("majority_label", "N"),
                        "beat_type":       risk.get("beat_type",      "Normal Sinus Beat"),
                        # new XGBoost fields
                        "xgb_bpm":         risk.get("xgb_bpm",        0.0),
                        "min_bpm":         risk.get("min_bpm",         0.0),
                        "max_bpm":         risk.get("max_bpm",         0.0),
                        "confidence":      risk.get("confidence",      0.0),
                        "sdnn_ms":         risk.get("sdnn_ms",         0.0),
                        "rmssd_ms":        risk.get("rmssd_ms",        0.0),
                        "abnormal_ratio":  risk.get("abnormal_ratio",  0.0),
                        "abnormal_pct":    risk.get("abnormal_pct",    0.0),
                        "risk_score":      risk.get("risk_score",      0),
                        "risk_label":      risk.get("risk_label",      "Low"),
                    }

                for ecg_val in recent:
                    # Send raw ADC value — frontend normalises it for display.
                    # ADC→mV conversion is only done inside prediction_service
                    # where the correct per-hardware baseline is applied.
                    payload = WSPayload(
                        timestamp   = datetime.now(timezone.utc).isoformat(),
                        ecg         = round(ecg_val, 2),
                        bpm         = int(self._current_bpm),
                        quality     = quality.label if quality else "Good",
                        quality_pct = quality.score if quality else 90,
                        status      = arrhythmia.rhythm if arrhythmia else "Analysing…",
                        session_id  = self._session_id,
                        analysis    = {
                            # arrhythmia fields (existing)
                            "rhythm":         arrhythmia.rhythm      if arrhythmia else None,
                            "confidence":     arrhythmia.confidence  if arrhythmia else None,
                            "riskLevel":      arrhythmia.risk_level  if arrhythmia else None,
                            "signalQuality":  quality.label          if quality    else "—",
                            "heartRateTrend": "Stable",
                            # XGBoost fields (new — also available top-level for easy access)
                            "xgbBpm":         risk.get("xgb_bpm",        0.0)  if risk else None,
                            "xgbConfidence":  risk.get("confidence",     0.0)  if risk else None,
                            "xgbRiskScore":   risk.get("risk_score",     0)    if risk else None,
                            "xgbRiskLabel":   risk.get("risk_label",     None) if risk else None,
                            "xgbBeatClass":   risk.get("majority_label", None) if risk else None,
                            "xgbBeatType":    risk.get("beat_type",      None) if risk else None,
                            "sdnn":           risk.get("sdnn_ms",        0.0)  if risk else None,
                            "rmssd":          risk.get("rmssd_ms",       0.0)  if risk else None,
                            "abnormalPct":    risk.get("abnormal_pct",   0.0)  if risk else None,
                            # full riskPrediction object (RiskCard uses this)
                            "riskPrediction": risk_prediction,
                        },
                    )
                    # Inject is_recording so the frontend can reflect state
                    # without a separate HTTP poll
                    frame = payload.model_dump()
                    frame["is_recording"] = self._storage_enabled
                    await self._send_to_all(json.dumps(frame))
            except Exception as exc:
                logger.error("Broadcast error: %s", exc, exc_info=True)

    async def _no_data_loop(self) -> None:
        """
        When no ESP32 is connected, broadcast a 'no_data' frame every second
        so the frontend can display 'Hardware not connected' instead of stale data.
        """
        while True:
            await asyncio.sleep(_NO_DATA_INTERVAL)
            if not self._ws_connections:
                continue
            if self._wifi_manager.is_connected:
                continue   # real data is flowing — nothing to do
            frame = json.dumps({
                "type":      "no_data",
                "connected": False,
                "message":   "No hardware connected — awaiting ESP32 on /ws/device",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            await self._send_to_all(frame)

    async def _send_to_all(self, message: str) -> None:
        disconnected = set()
        for ws in self._ws_connections.copy():
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.add(ws)
        self._ws_connections -= disconnected

    # ── WebSocket management ───────────────────────────────

    async def connect_ws(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._ws_connections.add(websocket)
        logger.info("Frontend WebSocket connected. Total: %d", len(self._ws_connections))

    async def disconnect_ws(self, websocket: WebSocket) -> None:
        self._ws_connections.discard(websocket)
        logger.info("Frontend WebSocket disconnected. Total: %d", len(self._ws_connections))

    # ── Monitoring-started notification ────────────────────

    async def _notify_monitoring_started(self, patient_id: str) -> None:
        try:
            from app.services.twilio_service import whatsapp_service, e164, _collect_recipients
            if not whatsapp_service._enabled:
                return

            async with AsyncSessionLocal() as db:
                patient = await crud.get_patient(db, patient_id)
            if not patient:
                return

            recipients = _collect_recipients(
                patient.guardian_phone,
                patient.emergency_contact,
                patient.phone,
            )
            if not recipients:
                return

            ts_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            location_line = ""
            if getattr(patient, "maps_link", None):
                location_line = f"\n📍 *Patient Location:* {patient.maps_link}"
            body = (
                f"\u2705 *ECG Guardian \u2013 Monitoring Started*\n\n"
                f"*Patient:* {patient.name}\n"
                f"*Session ID:* {self._session_id}\n"
                f"*Started at:* {ts_str}\n"
                f"*Device:* WiFi @ {settings.SAMPLING_RATE} Hz"
                f"{location_line}\n\n"
                f"Real-time ECG monitoring is now active. "
                f"You will receive alerts if any critical conditions are detected.\n\n"
                f"_ECG Guardian \u2014 Remote Cardiac Monitoring_"
            )

            account_sid = whatsapp_service._account_sid
            auth_token  = whatsapp_service._auth_token
            from_number = whatsapp_service._from_number
            loop = asyncio.get_event_loop()

            async def _send_one(num: str) -> dict:
                to_number = f"whatsapp:{num}"
                try:
                    def _do_send():
                        from twilio.rest import Client
                        Client(account_sid, auth_token).messages.create(
                            from_=from_number, to=to_number, body=body,
                        )
                    await loop.run_in_executor(None, _do_send)
                    async with AsyncSessionLocal() as db:
                        await crud.create_alert_log(db, patient_id=patient_id,
                            alert_type="MONITORING_STARTED", recipient=num, status="sent")
                        await db.commit()
                    logger.info("Monitoring-started WhatsApp sent to %s", num)
                    return {"phone": num, "status": "sent", "error": None}
                except Exception as exc:
                    async with AsyncSessionLocal() as db:
                        await crud.create_alert_log(db, patient_id=patient_id,
                            alert_type="MONITORING_STARTED", recipient=num,
                            status="failed", error_message=str(exc))
                        await db.commit()
                    logger.warning("Monitoring-started WhatsApp failed to %s: %s", num, exc)
                    return {"phone": num, "status": "failed", "error": str(exc)}

            results = await asyncio.gather(*[_send_one(num) for num in recipients])
            for r in results:
                ok = r["status"] == "sent"
                phone_short = r["phone"][-4:] if len(r["phone"]) >= 4 else r["phone"]
                await self._send_to_all(json.dumps({
                    "type":        "whatsapp_status",
                    "status":      r["status"],
                    "phone":       r["phone"],
                    "alert_type":  "MONITORING_STARTED",
                    "severity":    "info",
                    "title":       f"✅ Session alert sent to …{phone_short}" if ok
                                   else f"❌ Session alert failed to …{phone_short}",
                    "description": "Monitoring-started notification delivered." if ok
                                   else f"Could not deliver: {r['error'] or 'unknown'}",
                    "timestamp":   datetime.now(timezone.utc).isoformat(),
                }))
        except Exception as exc:
            logger.warning("Could not send monitoring-started WhatsApp: %s", exc)

    # ── Alert callback ─────────────────────────────────────

    def _on_alert(self, event: AlertEvent) -> None:
        self._notifier.dispatch(event)
        asyncio.create_task(self._handle_alert(event))

    async def _handle_alert(self, event: AlertEvent) -> None:
        try:
            async with AsyncSessionLocal() as db:
                await crud.create_alert(db, patient_id=event.patient_id,
                    alert_type=event.alert_type, severity=event.severity,
                    message=event.message)
                await db.commit()
        except Exception as exc:
            logger.error("Failed to persist alert: %s", exc)

        try:
            from app.services.twilio_service import whatsapp_service
            async with AsyncSessionLocal() as db:
                patient = await crud.get_patient(db, event.patient_id)
            if patient:
                alert_type_label = event.alert_type
                severity_label   = event.severity

                # ── Build enriched risk_level for WhatsApp ─────────
                # For XGBoost alerts, pull the full risk context from
                # _current_risk so the WhatsApp body has all parameters.
                risk = self._current_risk or {}
                is_xgb_alert = event.alert_type in ("VENTRICULAR_BEAT", "HIGH_RISK_SCORE")

                if is_xgb_alert and risk:
                    ecg_status_str = (
                        f"{risk.get('beat_type', event.alert_type)} "
                        f"[{risk.get('majority_label', '?')}]"
                    )
                    risk_level_str = (
                        f"{risk.get('risk_label', 'Unknown')} "
                        f"({risk.get('risk_score', 0)}/100)"
                    )
                else:
                    ecg_status_str = event.alert_type
                    risk_level_str = (
                        self._current_arrhythmia.risk_level
                        if self._current_arrhythmia else "Low"
                    )

                # ── XGBoost detail lines appended to alert_message ─
                extra_lines = ""
                if is_xgb_alert and risk:
                    extra_lines = (
                        f"\n\n📊 *XGBoost Analysis*\n"
                        f"• BPM            : {risk.get('xgb_bpm', 0.0):.1f}\n"
                        f"• Beat Class     : {risk.get('beat_type', '—')} "
                        f"[{risk.get('majority_label', '?')}]\n"
                        f"• Confidence     : {risk.get('confidence', 0.0):.1f}%\n"
                        f"• Risk Score     : {risk.get('risk_score', 0)}/100 "
                        f"[{risk.get('risk_label', '—')}]\n"
                        f"• HRV SDNN       : {risk.get('sdnn_ms', 0.0):.1f} ms\n"
                        f"• HRV RMSSD      : {risk.get('rmssd_ms', 0.0):.1f} ms\n"
                        f"• Abnormal Beats : {risk.get('abnormal_pct', 0.0):.1f}%\n"
                        f"_[PROTOTYPE — not a clinical diagnosis]_"
                    )

                async def _on_whatsapp_result(results: list[dict]) -> None:
                    for r in results:
                        ok = r["status"] == "sent"
                        phone_short = r["phone"][-4:] if len(r["phone"]) >= 4 else r["phone"]
                        await self._send_to_all(json.dumps({
                            "type":        "whatsapp_status",
                            "status":      r["status"],
                            "phone":       r["phone"],
                            "alert_type":  alert_type_label,
                            "severity":    severity_label,
                            "title":       f"✅ Alert sent to …{phone_short}" if ok
                                           else f"❌ Alert failed to …{phone_short}",
                            "description": f"WhatsApp {alert_type_label} alert delivered." if ok
                                           else f"Could not deliver to …{phone_short}: "
                                                f"{r['error'] or 'unknown error'}",
                            "timestamp":   datetime.now(timezone.utc).isoformat(),
                        }))

                whatsapp_service.dispatch(
                    patient_id        = event.patient_id,
                    patient_name      = patient.name,
                    guardian_phone    = patient.guardian_phone,
                    emergency_contact = patient.emergency_contact,
                    phone             = patient.phone,
                    doctor_phone      = getattr(patient, "doctor_phone", None),
                    ambulance_phone   = getattr(patient, "ambulance_phone", None),
                    maps_link         = getattr(patient, "maps_link", None),
                    alert_type        = event.alert_type,
                    severity          = event.severity,
                    ecg_status        = ecg_status_str,
                    risk_level        = risk_level_str,
                    alert_message     = event.message + extra_lines,
                    timestamp         = event.timestamp,
                    on_result         = _on_whatsapp_result,
                )
        except Exception as exc:
            logger.error("WhatsApp dispatch error: %s", exc)

    # ── Public accessors ───────────────────────────────────

    @property
    def current_bpm(self) -> float:           return self._current_bpm
    @property
    def current_quality(self):                return self._current_quality
    @property
    def current_arrhythmia(self):             return self._current_arrhythmia
    @property
    def current_risk(self) -> Optional[dict]: return self._current_risk
    @property
    def session_id(self) -> Optional[str]:    return self._session_id
    @property
    def is_monitoring(self) -> bool:          return self._is_monitoring
    @property
    def is_recording(self) -> bool:           return self._storage_enabled
    @property
    def is_connected(self) -> bool:           return self._wifi_manager.is_connected
    @property
    def active_patient_id(self) -> Optional[str]: return self._patient_id

    @property
    def device_router(self):
        return self._wifi_manager.router

    def get_live_ecg_window(self, n: int = 250) -> list[float]:
        return list(self._raw_buffer)[-n:]

    def set_patient_id(self, patient_id: str) -> None:
        """Called by main.py after the first patient is loaded from the DB."""
        if not self._patient_id:
            self._patient_id = patient_id
            logger.info("ECGService patient set to %s", patient_id)


# ── Singleton ──────────────────────────────────────────────
ecg_service = ECGService()
