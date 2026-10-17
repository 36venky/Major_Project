"""
serial/wifi_manager.py
───────────────────────
ESP32 WiFi WebSocket device manager.

The ESP32 connects to /ws/device and streams raw ADC integer strings ("2048\\n").
Each value is forwarded to ECGService via the on_sample callback.

Simulation has been fully removed.  When no ESP32 is connected:
  - is_connected is False
  - no samples are pushed
  - the ECG service broadcasts a "no data" status frame to the frontend

INFO log messages are printed for every connection/disconnection event so the
console shows clearly whether hardware data is being received.
"""

from __future__ import annotations

import asyncio
from typing import Callable, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.logger import get_logger

logger = get_logger("serial.wifi_manager")

_ADC_MIN = 0
_ADC_MAX = 4095


class WiFiManager:
    """
    Manages the ESP32 WiFi WebSocket connection.

    Public interface:
      start() / stop()
      is_connected  – True only when a real ESP32 is actively sending data
      router        – FastAPI APIRouter owning /ws/device  (register in main.py)
    """

    def __init__(self, on_sample: Callable[[float], None]):
        self._on_sample:   Callable[[float], None] = on_sample
        self._running:     bool = False
        self.is_connected: bool = False
        self._device_ws:   Optional[WebSocket] = None
        self._sample_count: int = 0   # samples received in current connection

        self.router = APIRouter(tags=["Device"])
        self.router.add_api_websocket_route("/ws/device", self._device_endpoint)

    # ── Lifecycle ──────────────────────────────────────────

    async def start(self) -> None:
        """Start the manager (called from ECGService.start)."""
        if self._running:
            return
        self._running = True
        logger.info(
            "WiFiManager ready — waiting for ESP32 on /ws/device  "
            "(no simulation; hardware required)"
        )

    async def stop(self) -> None:
        """Stop the manager."""
        self._running = False
        self.is_connected = False
        logger.info("WiFiManager stopped")

    # ── /ws/device WebSocket endpoint ─────────────────────

    async def _device_endpoint(self, ws: WebSocket) -> None:
        """
        ESP32 connects here and streams raw ADC integer strings, e.g. '2048'.
        One integer value per WebSocket message (matches the ESP32 firmware protocol).
        """
        await ws.accept()
        self._device_ws   = ws
        self.is_connected = True
        self._sample_count = 0

        client = ws.client
        logger.info(
            "━━━ ESP32 CONNECTED via WiFi WebSocket  client=%s:%s ━━━",
            client.host if client else "?",
            client.port if client else "?",
        )

        try:
            while True:
                data = await ws.receive_text()
                raw  = data.strip()

                if not raw or raw == "!":   # lead-off / disconnected marker
                    continue

                try:
                    adc_value = float(raw.split(",")[0].strip())
                except ValueError:
                    logger.debug("Discarding malformed frame: %r", raw[:40])
                    continue

                if _ADC_MIN <= adc_value <= _ADC_MAX:
                    self._on_sample(adc_value)
                    self._sample_count += 1
                    if self._sample_count % 192 == 0:
                        logger.info(
                            "ESP32 data  sample_count=%d  latest_adc=%.0f",
                            self._sample_count, adc_value,
                        )
                else:
                    logger.debug("ADC value out of range [0–4095]: %.0f", adc_value)

        except WebSocketDisconnect:
            logger.info(
                "━━━ ESP32 DISCONNECTED  (received %d samples this session) ━━━",
                self._sample_count,
            )
        except Exception as exc:
            logger.error("ESP32 WebSocket error: %s", exc)
        finally:
            self._device_ws   = None
            self.is_connected = False
            self._sample_count = 0
            logger.info("No hardware connected — ECG chart will show 'No Data'")
