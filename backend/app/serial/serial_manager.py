"""
serial/serial_manager.py
─────────────────────────
Robust serial port lifecycle manager (Feature 6 — fixed).

Improvements over the original:
  - Thread-safe asyncio.Queue between executor thread and async consumer
  - Queue capacity capped at 1000; drops and warns when full
  - is_connected transitions atomically on SerialException
  - Reconnect interval from settings.RECONNECT_INTERVAL
  - All errors logged to serial.log via get_logger("serial.manager")
"""

from __future__ import annotations

import asyncio
import queue
import threading
import time
from typing import Callable, Optional

from app.core.config import settings
from app.core.logger import get_logger
from app.serial.serial_reader import SerialReader

logger = get_logger("serial.manager")

_QUEUE_MAX  = 1000
_WARN_EVERY = 5.0   # seconds between "queue full" warnings


class SerialManager:
    """
    Manages the COM port connection with automatic reconnection.

    Uses a thread-safe queue to decouple the blocking readline() executor
    thread from the asyncio consumer loop, preventing race conditions.
    """

    def __init__(self, on_sample: Callable[[float], None]):
        self._on_sample    = on_sample
        self._running:     bool = False
        self.is_connected: bool = False

        # Thread-safe sample transfer queue
        self._sample_queue: asyncio.Queue[Optional[float]] = asyncio.Queue(maxsize=_QUEUE_MAX)

        self._producer_task:  Optional[asyncio.Task] = None
        self._consumer_task:  Optional[asyncio.Task] = None
        self._last_warn_time: float = 0.0

    # ── Lifecycle ─────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._producer_task = asyncio.create_task(self._producer_loop(), name="serial_producer")
        self._consumer_task = asyncio.create_task(self._consumer_loop(), name="serial_consumer")
        logger.info("SerialManager started")

    async def stop(self) -> None:
        self._running = False
        # Signal consumer to exit
        try:
            self._sample_queue.put_nowait(None)
        except asyncio.QueueFull:
            pass
        for task in (self._producer_task, self._consumer_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self.is_connected = False
        logger.info("SerialManager stopped")

    # ── Producer: reads serial and feeds queue ─────────────

    async def _producer_loop(self) -> None:
        """Open port, stream samples into queue, reconnect on failure."""
        while self._running:
            reader = SerialReader()
            opened = await reader.open()
            self.is_connected = opened or reader._mock_mode

            if self.is_connected:
                logger.info("Serial connection established (mock=%s)", reader._mock_mode)
            else:
                logger.warning("Serial not connected — waiting %ds before retry",
                               settings.RECONNECT_INTERVAL)
                await asyncio.sleep(settings.RECONNECT_INTERVAL)
                continue

            try:
                async for sample in reader.stream():
                    if not self._running:
                        break
                    try:
                        self._sample_queue.put_nowait(sample)
                    except asyncio.QueueFull:
                        now = time.monotonic()
                        if now - self._last_warn_time >= _WARN_EVERY:
                            logger.warning("Sample queue full — dropping incoming samples")
                            self._last_warn_time = now
            except Exception as exc:
                logger.error("Serial stream error: %s — reconnecting in %ds",
                             exc, settings.RECONNECT_INTERVAL)
                self.is_connected = False
            finally:
                await reader.close()
                self.is_connected = False

            if self._running:
                logger.info("Reconnecting serial in %ds…", settings.RECONNECT_INTERVAL)
                await asyncio.sleep(settings.RECONNECT_INTERVAL)

    # ── Consumer: drains queue and calls on_sample ─────────

    async def _consumer_loop(self) -> None:
        """Pull samples from queue and deliver to ECGService callback."""
        while self._running:
            try:
                sample = await asyncio.wait_for(self._sample_queue.get(), timeout=1.0)
                if sample is None:
                    break
                self._on_sample(sample)
            except asyncio.TimeoutError:
                continue
            except Exception as exc:
                logger.error("Consumer loop error: %s", exc)
