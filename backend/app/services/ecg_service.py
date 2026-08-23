"""
services/ecg_service.py
────────────────────────
Core ECG monitoring service.

Orchestrates the complete data flow:
  SerialManager → Signal Processing → DB write → WebSocket broadcast → Alert engine → WhatsApp → Risk Prediction
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
_BROADCAST_INTERVAL = settings.WS_BROADCAST_INTERVAL


class ECGService:
    """Singleton service that manages the ECG monitoring pipeline."""

    def __init__(self):
        self._patient_id:      Optional[str] = "P-001"
        self._session_id:      Optional[str] = None
        self._is_monitoring:   bool          = False

        self._raw_buffer:      deque[float] = deque(maxlen=settings.SAMPLING_RATE * 10)
        self._pending_samples: list[dict]   = []
        self._bpm_history:     list[float]  = []

        self._bpm_estimator  = RollingBPMEstimator(window_seconds=_ANALYSIS_WINDOW)
        self._alert_engine:  Optional[AlertEngine]  = None
        self._notifier       = NotificationDispatcher()

        self._current_bpm:        float                     = 0.0
        self._current_quality:    Optional[SignalQualityResult] = None
        self._current_arrhythmia: Optional[ArrhythmiaResult]  = None
        self._current_risk:       Optional[dict]            = None  # latest risk prediction

        self._ws_connections: Set[WebSocket] = set()
        self._wifi_manager = WiFiManager(on_sample=self._on_sample)

        self._db_flush_task:   Optional[asyncio.Task] = None
        self._broadcast_task:  Optional[asyncio.Task] = None
        self._analysis_task:   Optional[asyncio.Task] = None

    # ── Lifecycle ──────────────────────────────────────────

    async def start(self) -> None:
        logger.info("ECGService starting…")
        await self._wifi_manager.start()
        self._db_flush_task  = asyncio.create_task(self._db_flush_loop(),  name="db_flush")
        self._broadcast_task = asyncio.create_task(self._broadcast_loop(), name="ws_broadcast")
        self._analysis_task  = asyncio.create_task(self._analysis_loop(),  name="ecg_analysis")
        await self._open_session(self._patient_id)
        logger.info("ECGService started.")

    async def stop(self) -> None:
        logger.info("ECGService stopping…")
        if self._session_id:
            await self._close_session()
        await self._wifi_manager.stop()
        for task in (self._db_flush_task, self._broadcast_task, self._analysis_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        logger.info("ECGService stopped.")

    # ── Patient switching (Feature 2) ──────────────────────

    async def switch_patient(self, patient_id: str) -> None:
        """Switch the active monitored patient. Closes current session and opens a new one."""
        logger.info("Switching active patient from %s → %s", self._patient_id, patient_id)
        if self._session_id:
            try:
                await self._close_session()
            except Exception as exc:
                logger.warning("Could not cleanly close session during switch: %s", exc)
                self._session_id    = None
                self._is_monitoring = False
        self._patient_id = patient_id
        self._raw_buffer.clear()
        self._pending_samples.clear()
        self._bpm_history.clear()
        self._bpm_estimator.reset()
        self._current_risk = None
        await self._open_session(patient_id)

    # ── Session management ─────────────────────────────────

    async def _open_session(self, patient_id: str) -> None:
        async with AsyncSessionLocal() as db:
            session = await crud.create_session(db, patient_id)
            await db.commit()
            self._session_id = session.session_id
            self._bpm_history.clear()
            self._bpm_estimator.reset()
            self._is_monitoring = True
            self._alert_engine = AlertEngine(
                patient_id=patient_id,
                on_alert=self._on_alert,
                cooldown_seconds=60,
            )
        logger.info("ECG session opened: %s", self._session_id)

        # Notify guardian that monitoring has started (Feature 4 – informational)
        asyncio.create_task(self._notify_monitoring_started(patient_id))

    async def _close_session(self) -> None:
        if not self._session_id:
            self._is_monitoring = False
            return
        if not self._bpm_history:
            # No BPM data — just mark session inactive without aggregates
            async with AsyncSessionLocal() as db:
                await crud.close_session(db, self._session_id, 0.0, 0.0, 0.0)
                await db.commit()
            self._session_id    = None
            self._is_monitoring = False
            return
        avg_bpm = float(np.mean(self._bpm_history))
        min_bpm = float(np.min(self._bpm_history))
        max_bpm = float(np.max(self._bpm_history))
        async with AsyncSessionLocal() as db:
            await crud.close_session(db, self._session_id, avg_bpm, min_bpm, max_bpm)
            await db.commit()
        logger.info("Session %s closed  avg=%.1f", self._session_id, avg_bpm)
        self._session_id    = None
        self._is_monitoring = False

    # ── Sample ingestion ───────────────────────────────────

    def _on_sample(self, value: float) -> None:
        self._raw_buffer.append(value)
        self._bpm_estimator.push(value)
        if self._session_id:
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
            if not self._pending_samples:
                continue
            batch = self._pending_samples.copy()
            self._pending_samples.clear()
            try:
                async with AsyncSessionLocal() as db:
                    await crud.bulk_insert_samples(db, batch)
                    if self._current_bpm > 0 and self._patient_id:
                        await crud.save_heart_rate(db, self._patient_id, self._current_bpm, self._session_id)
                    await db.commit()
            except Exception as exc:
                logger.error("DB flush error: %s", exc)

    async def _analysis_loop(self) -> None:
        fs     = settings.SAMPLING_RATE
        window = _ANALYSIS_WINDOW * fs

        while True:
            await asyncio.sleep(_ANALYSIS_WINDOW)
            if len(self._raw_buffer) < fs:
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

                if self._alert_engine:
                    self._alert_engine.evaluate(
                        bpm=self._current_bpm,
                        quality=self._current_quality,
                        arrhythmia=self._current_arrhythmia,
                        device_connected=self._wifi_manager.is_connected,
                    )

                # Run ML risk prediction (Feature 5)
                from app.services.prediction_service import prediction_service
                risk = await prediction_service.maybe_predict(
                    patient_id=self._patient_id,
                    raw_buffer=self._raw_buffer,
                    fs=fs,
                )
                if risk:
                    self._current_risk = risk

            except Exception as exc:
                logger.error("Analysis loop error: %s", exc)

    async def _broadcast_loop(self) -> None:
        while True:
            await asyncio.sleep(_BROADCAST_INTERVAL)
            if not self._ws_connections or not self._raw_buffer:
                continue
            try:
                quality    = self._current_quality
                arrhythmia = self._current_arrhythmia

                # Send all samples accumulated since last broadcast (typically ~10 at 250 Hz / 25 fps)
                # so the frontend graph receives every real sample, not just the latest one.
                samples_per_frame = max(1, int(settings.SAMPLING_RATE * _BROADCAST_INTERVAL))
                recent = list(self._raw_buffer)[-samples_per_frame:]

                for ecg_val in recent:
                    payload = WSPayload(
                        timestamp   = datetime.now(timezone.utc).isoformat(),
                        ecg         = round(ecg_val, 2),
                        bpm         = int(self._current_bpm),
                        quality     = quality.label if quality else "Good",
                        quality_pct = quality.score if quality else 90,
                        status      = arrhythmia.rhythm if arrhythmia else "Normal Sinus Rhythm",
                        session_id  = self._session_id,
                        analysis    = {
                            "rhythm":        arrhythmia.rhythm      if arrhythmia else None,
                            "confidence":    arrhythmia.confidence  if arrhythmia else None,
                            "riskLevel":     arrhythmia.risk_level  if arrhythmia else None,
                            "signalQuality": quality.label          if quality    else "Good",
                            "heartRateTrend": "Stable",
                            "riskPrediction": self._current_risk,
                        } if arrhythmia else None,
                    )
                    await self._send_to_all(payload.model_dump_json())
            except Exception as exc:
                logger.debug("Broadcast error: %s", exc)

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
        logger.info("WebSocket client connected. Total: %d", len(self._ws_connections))

    async def disconnect_ws(self, websocket: WebSocket) -> None:
        self._ws_connections.discard(websocket)
        logger.info("WebSocket client disconnected. Total: %d", len(self._ws_connections))

    # ── Monitoring-started notification ────────────────────

    async def _notify_monitoring_started(self, patient_id: str) -> None:
        """
        Send a WhatsApp notification to ALL of the patient's contacts when a
        new ECG monitoring session opens.
        """
        try:
            from app.services.twilio_service import whatsapp_service, e164, _collect_recipients
            if not whatsapp_service._enabled:
                logger.warning(
                    "Monitoring-started WhatsApp skipped — Twilio service disabled "
                    "(check TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_WHATSAPP_FROM in .env)"
                )
                return

            async with AsyncSessionLocal() as db:
                patient = await crud.get_patient(db, patient_id)

            if not patient:
                logger.warning(
                    "Monitoring-started WhatsApp skipped — patient %s not found", patient_id
                )
                return

            recipients = _collect_recipients(
                patient.guardian_phone,
                patient.emergency_contact,
                patient.phone,
            )
            if not recipients:
                logger.warning(
                    "Monitoring-started WhatsApp skipped — no contact numbers for patient %s",
                    patient_id,
                )
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
                    # Log to DB
                    async with AsyncSessionLocal() as db:
                        await crud.create_alert_log(
                            db,
                            patient_id=patient_id,
                            alert_type="MONITORING_STARTED",
                            recipient=num,
                            status="sent",
                        )
                        await db.commit()
                    logger.info(
                        "Monitoring-started WhatsApp sent to %s for patient=%s session=%s",
                        num, patient_id, self._session_id,
                    )
                    return {"phone": num, "status": "sent", "error": None}
                except Exception as exc:
                    err = str(exc)
                    async with AsyncSessionLocal() as db:
                        await crud.create_alert_log(
                            db,
                            patient_id=patient_id,
                            alert_type="MONITORING_STARTED",
                            recipient=num,
                            status="failed",
                            error_message=err,
                        )
                        await db.commit()
                    logger.warning(
                        "Monitoring-started WhatsApp failed to %s patient=%s: %s",
                        num, patient_id, err,
                    )
                    return {"phone": num, "status": "failed", "error": err}

            results = await asyncio.gather(*[_send_one(num) for num in recipients])

            # Push a toast notification to all connected frontend clients
            for r in results:
                status_ok   = r["status"] == "sent"
                phone_short = r["phone"][-4:] if len(r["phone"]) >= 4 else r["phone"]
                notif_payload = json.dumps({
                    "type":        "whatsapp_status",
                    "status":      r["status"],
                    "phone":       r["phone"],
                    "alert_type":  "MONITORING_STARTED",
                    "severity":    "info",
                    "title":       (
                        f"✅ Session alert sent to …{phone_short}"
                        if status_ok else
                        f"❌ Session alert failed to …{phone_short}"
                    ),
                    "description": (
                        f"Monitoring-started notification delivered."
                        if status_ok else
                        f"Could not deliver to …{phone_short}: {r['error'] or 'unknown error'}"
                    ),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                await self._send_to_all(notif_payload)

        except Exception as exc:
            logger.warning("Could not send monitoring-started WhatsApp: %s", exc)

    # ── Alert callback ─────────────────────────────────────

    def _on_alert(self, event: AlertEvent) -> None:
        self._notifier.dispatch(event)
        asyncio.create_task(self._handle_alert(event))

    async def _handle_alert(self, event: AlertEvent) -> None:
        # Persist to DB
        try:
            async with AsyncSessionLocal() as db:
                await crud.create_alert(
                    db,
                    patient_id=event.patient_id,
                    alert_type=event.alert_type,
                    severity=event.severity,
                    message=event.message,
                )
                await db.commit()
        except Exception as exc:
            logger.error("Failed to persist alert: %s", exc)

        # Send WhatsApp notification to all patient contacts (Feature 4)
        try:
            from app.services.twilio_service import whatsapp_service
            async with AsyncSessionLocal() as db:
                patient = await crud.get_patient(db, event.patient_id)

            if patient:
                # Capture alert details for the result callback closure
                alert_type_label = event.alert_type
                severity_label   = event.severity

                async def _on_whatsapp_result(results: list[dict]) -> None:
                    """Push a toast notification to the frontend for each send attempt."""
                    for r in results:
                        status_ok   = r["status"] == "sent"
                        phone_short = r["phone"][-4:] if len(r["phone"]) >= 4 else r["phone"]
                        notif_payload = json.dumps({
                            "type":        "whatsapp_status",
                            "status":      r["status"],
                            "phone":       r["phone"],
                            "alert_type":  alert_type_label,
                            "severity":    severity_label,
                            "title":       (
                                f"✅ Alert sent to …{phone_short}"
                                if status_ok else
                                f"❌ Alert failed to …{phone_short}"
                            ),
                            "description": (
                                f"WhatsApp {alert_type_label} alert delivered."
                                if status_ok else
                                f"Could not deliver to …{phone_short}: {r['error'] or 'unknown error'}"
                            ),
                            "timestamp":   datetime.now(timezone.utc).isoformat(),
                        })
                        await self._send_to_all(notif_payload)

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
                    ecg_status        = event.alert_type,
                    risk_level        = self._current_arrhythmia.risk_level if self._current_arrhythmia else "Low",
                    alert_message     = event.message,
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
    def is_connected(self) -> bool:           return self._wifi_manager.is_connected
    @property
    def active_patient_id(self) -> Optional[str]: return self._patient_id

    @property
    def device_router(self):
        """FastAPI router that owns /ws/device — register in main.py."""
        return self._wifi_manager.router

    def get_live_ecg_window(self, n: int = 250) -> list[float]:
        return list(self._raw_buffer)[-n:]


# ── Singleton ──────────────────────────────────────────────
ecg_service = ECGService()
