"""
serial/wifi_manager.py
───────────────────────
ESP32 WiFi WebSocket device manager.

Replaces the old COM-port SerialManager with a WebSocket-based approach
that mirrors Trail/app.py:

  ESP32  ──sends "2048\n"──►  /ws/device   (this module owns that endpoint)
  ECGService ◄── on_sample(float) callback ──  (same interface as before)

Architecture
────────────
  WiFiManager owns a FastAPI WebSocket endpoint (/ws/device).
  When the ESP32 connects, raw ADC integer strings are accepted and
  pushed directly into the existing ECGService._on_sample() callback.

  If no ESP32 is connected and MOCK_WHEN_UNAVAILABLE is True, a background
  task generates the same synthetic ECG waveform as the old SerialReader so
  development can continue without hardware.

  The `is_connected` bool property is preserved so ECGService and the
  AlertEngine work without changes.

Mock fallback
─────────────
  Mock mode starts automatically when the manager is started and no real
  ESP32 connects within MOCK_CONNECT_TIMEOUT seconds (default 10 s from
  config).  As soon as a real device connects the mock task is cancelled;
  when the device disconnects and no new connection arrives within the
  timeout, mock mode resumes.
"""

from __future__ import annotations

import asyncio
import math
import random
import time
from typing import Callable, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger("serial.wifi_manager")

# ── Synthetic ECG generator (identical to old serial_reader) ───────────────

_ADC_MIN = 0
_ADC_MAX = 4095


def _mock_ecg_sample(t: float) -> float:
    """
    Generate a realistic synthetic ECG sample at time `t` (seconds).

    75 BPM textbook waveform: P → QRS → T, centred on ADC mid-range (2048).
    """
    period = 0.8
    cycle = (t % period) / period

    ecg = 0.0
    ecg += 15.0 * math.sin(2 * math.pi * 0.15 * t)   # baseline wander

    if 0.08 < cycle < 0.22:
        p = (cycle - 0.08) / 0.14
        ecg += 60.0 * math.sin(math.pi * p)            # P wave

    if 0.28 < cycle < 0.33:
        q = (cycle - 0.28) / 0.05
        ecg -= 25.0 * math.sin(math.pi * q)            # Q dip

    if 0.33 < cycle < 0.42:
        r = (cycle - 0.33) / 0.09
        ecg += 900.0 * math.sin(math.pi * r)           # R peak

    if 0.42 < cycle < 0.47:
        s = (cycle - 0.42) / 0.05
        ecg -= 40.0 * math.sin(math.pi * s)            # S dip

    if 0.52 < cycle < 0.72:
        tw = (cycle - 0.52) / 0.20
        ecg += 130.0 * math.sin(math.pi * tw)          # T wave

    ecg += random.gauss(0, 4.0)                        # electrode noise σ=4
    return max(float(_ADC_MIN), min(float(_ADC_MAX), 2048.0 + ecg))


# ── WiFiManager ────────────────────────────────────────────────────────────

class WiFiManager:
    """
    Manages the ESP32 WiFi WebSocket connection with automatic mock fallback.

    Public interface mirrors the old SerialManager so ECGService needs
    minimal changes:
      - start() / stop()
      - is_connected  (bool property)
      - router        (FastAPI APIRouter — register in main.py)
    """

    # How long to wait for an ESP32 before starting mock mode (seconds)
    _CONNECT_TIMEOUT: float = 10.0

    def __init__(self, on_sample: Callable[[float], None]):
        self._on_sample:    Callable[[float], None] = on_sample
        self._running:      bool = False
        self.is_connected:  bool = False

        # Pull timeout from config (falls back to class default if not set)
        self._CONNECT_TIMEOUT = getattr(settings, "MOCK_CONNECT_TIMEOUT", 10.0)

        # Set when an ESP32 WebSocket is active
        self._device_ws:    Optional[WebSocket] = None

        # Background tasks
        self._mock_task:    Optional[asyncio.Task] = None
        self._watchdog_task: Optional[asyncio.Task] = None

        # Event: set when a real device connects, cleared on disconnect
        self._device_event: asyncio.Event = asyncio.Event()

        # FastAPI router — register this in main.py
        self.router = APIRouter(tags=["Device"])
        self.router.add_api_websocket_route("/ws/device", self._device_endpoint)

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the manager (called from ECGService.start)."""
        if self._running:
            return
        self._running = True
        self._watchdog_task = asyncio.create_task(
            self._watchdog_loop(), name="wifi_watchdog"
        )
        logger.info("WiFiManager started — waiting for ESP32 on /ws/device")

    async def stop(self) -> None:
        """Stop the manager and cancel all background tasks."""
        self._running = False
        self._device_event.set()          # unblock the watchdog
        for task in (self._watchdog_task, self._mock_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self.is_connected = False
        logger.info("WiFiManager stopped")

    # ── Watchdog: starts/stops mock based on device presence ──────────────

    async def _watchdog_loop(self) -> None:
        """
        Monitors device connectivity.
        Starts mock mode after CONNECT_TIMEOUT with no real device,
        cancels mock as soon as a real device connects.
        """
        while self._running:
            # Wait for a real device to connect (with timeout for mock fallback)
            connected = await asyncio.wait_for(
                self._wait_for_device(), timeout=self._CONNECT_TIMEOUT
            ) if settings.MOCK_WHEN_UNAVAILABLE else await self._wait_for_device_no_timeout()

            if not self._running:
                break

            if connected:
                # Real device just connected — cancel mock if running
                self._stop_mock()
                logger.info("ESP32 connected — mock mode deactivated")
                # Wait for device to disconnect
                await self._device_event.wait()
                self._device_event.clear()
                self.is_connected = False
                logger.info("ESP32 disconnected")
            else:
                # Timeout expired without a real device → start mock
                if not self._is_mock_running():
                    self._start_mock()

            # Small sleep to avoid tight loop when no device ever connects
            await asyncio.sleep(0.5)

    async def _wait_for_device(self) -> bool:
        """
        Wait until the device event fires (real ESP32 arrived).
        Returns True if a device connected, False on timeout.
        """
        try:
            self._device_event.clear()
            # We only get here when the event is set (device connected)
            await asyncio.wait_for(
                _wait_event(self._device_event), timeout=self._CONNECT_TIMEOUT
            )
            return True
        except asyncio.TimeoutError:
            return False

    async def _wait_for_device_no_timeout(self) -> bool:
        """Wait indefinitely (mock disabled)."""
        self._device_event.clear()
        await _wait_event(self._device_event)
        return True

    # ── Mock ECG task ──────────────────────────────────────────────────────

    def _start_mock(self) -> None:
        if not settings.MOCK_WHEN_UNAVAILABLE:
            return
        self._mock_task = asyncio.create_task(
            self._mock_loop(), name="wifi_mock"
        )
        self.is_connected = True     # mock counts as "connected" for UI
        logger.warning(
            "No ESP32 connected — running MOCK ECG at %d Hz", settings.SAMPLING_RATE
        )

    def _stop_mock(self) -> None:
        if self._mock_task and not self._mock_task.done():
            self._mock_task.cancel()
            self._mock_task = None

    def _is_mock_running(self) -> bool:
        return self._mock_task is not None and not self._mock_task.done()

    async def _mock_loop(self) -> None:
        """Generate synthetic ECG samples at SAMPLING_RATE Hz."""
        interval = 1.0 / settings.SAMPLING_RATE
        batch    = max(1, settings.SAMPLING_RATE // 25)   # ~25 yields/sec
        batch_interval = batch * interval
        sample_index   = 0

        try:
            while self._running:
                t0 = time.monotonic()
                for _ in range(batch):
                    t_sec = sample_index * interval
                    self._on_sample(_mock_ecg_sample(t_sec))
                    sample_index += 1
                elapsed    = time.monotonic() - t0
                sleep_time = max(0.0, batch_interval - elapsed)
                await asyncio.sleep(sleep_time)
        except asyncio.CancelledError:
            pass

    # ── /ws/device WebSocket endpoint ─────────────────────────────────────

    async def _device_endpoint(self, ws: WebSocket) -> None:
        """
        The ESP32 connects here and streams raw ADC integer strings, e.g. "2048".
        One value per message (matches Trail/app.py protocol).
        """
        await ws.accept()
        self._device_ws = ws
        self.is_connected = True
        self._device_event.set()          # signal watchdog: real device arrived
        self._stop_mock()                 # immediately kill mock if running
        logger.info("ESP32 connected via WiFi WebSocket")

        try:
            while True:
                data = await ws.receive_text()
                raw  = data.strip()

                if not raw or raw == "!":  # lead-off / disconnected marker
                    continue

                try:
                    adc_value = float(raw.split(",")[0].strip())
                except ValueError:
                    continue              # discard malformed frame

                if _ADC_MIN <= adc_value <= _ADC_MAX:
                    self._on_sample(adc_value)
                else:
                    logger.debug("ADC value out of range: %s", adc_value)

        except WebSocketDisconnect:
            logger.info("ESP32 WebSocket disconnected normally")
        except Exception as exc:
            logger.error("ESP32 WebSocket error: %s", exc)
        finally:
            self._device_ws   = None
            self.is_connected = False
            self._device_event.set()      # unblock watchdog so it can restart mock


# ── Helpers ────────────────────────────────────────────────────────────────

async def _wait_event(event: asyncio.Event) -> None:
    """Await an asyncio.Event without a timeout."""
    await event.wait()
