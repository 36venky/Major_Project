"""
serial/serial_reader.py
────────────────────────
Low-level async serial port reader.

Responsibilities:
  - Open / close COM port
  - Read raw bytes line by line
  - Parse and validate incoming ECG samples
  - Yield validated float values to the caller
  - Never interact with the database or WebSocket directly

Data format expected from device:
  One ECG ADC value per line, e.g.:
    512
    503
    521
  Values outside [0, 4095] (12-bit ADC range) are treated as corrupt.

Mock mode:
  When the COM port is unavailable and MOCK_WHEN_UNAVAILABLE=true,
  this module yields synthetic ECG samples so development can continue
  without hardware.
"""

from __future__ import annotations

import asyncio
import math
import random
import time
from typing import AsyncGenerator, Optional

from app.core.config import settings
from app.core.exceptions import SerialConnectionError
from app.core.logger import get_logger

logger = get_logger("serial.reader")

# Clamp window for valid 12-bit ADC values
_ADC_MIN = 0
_ADC_MAX = 4095

# ── Mock ECG generator ────────────────────────────────────

def _mock_ecg_sample(t: float) -> float:
    """
    Generate a realistic synthetic ECG sample at time `t` (in seconds).

    Produces a textbook ECG shape: P wave → QRS complex → T wave at ~75 BPM.
    The sample index `t` is derived from a monotonic counter so the waveform
    is perfectly periodic — no jitter from asyncio.sleep timing.

    Args:
        t: Elapsed time in seconds (monotonic, not wall-clock).

    Returns:
        Synthetic ADC value in [0, 4095].
    """
    # 75 BPM → cycle period = 0.8 s
    period = 0.8
    cycle = (t % period) / period   # normalised 0→1 within each beat

    ecg = 0.0

    # Baseline wander (very slow, 0.15 Hz)
    ecg += 15.0 * math.sin(2 * math.pi * 0.15 * t)

    # P wave  (0.08 – 0.22 of cycle)
    if 0.08 < cycle < 0.22:
        p = (cycle - 0.08) / 0.14      # 0→1 within P-wave window
        ecg += 60.0 * math.sin(math.pi * p)

    # Q dip   (0.28 – 0.33)
    if 0.28 < cycle < 0.33:
        q = (cycle - 0.28) / 0.05
        ecg -= 25.0 * math.sin(math.pi * q)

    # R peak  (0.33 – 0.42)  ← dominant spike
    if 0.33 < cycle < 0.42:
        r = (cycle - 0.33) / 0.09
        ecg += 900.0 * math.sin(math.pi * r)

    # S dip   (0.42 – 0.47)
    if 0.42 < cycle < 0.47:
        s = (cycle - 0.42) / 0.05
        ecg -= 40.0 * math.sin(math.pi * s)

    # T wave  (0.52 – 0.72)
    if 0.52 < cycle < 0.72:
        tw = (cycle - 0.52) / 0.20
        ecg += 130.0 * math.sin(math.pi * tw)

    # Gaussian noise (σ = 4 ADC counts — realistic electrode noise)
    ecg += random.gauss(0, 4.0)

    # Centre around 2048 (mid 12-bit ADC range)
    return max(0.0, min(4095.0, 2048.0 + ecg))


# ── Async serial reader ───────────────────────────────────

class SerialReader:
    """
    Async iterator that yields validated ECG float samples from the serial port.

    Usage:
        reader = SerialReader()
        async for sample in reader.stream():
            process(sample)
    """

    def __init__(self):
        self._serial = None
        self._mock_mode = False
        self._running = False
        self._t: float = 0.0    # mock time counter

    async def open(self) -> bool:
        """
        Attempt to open the configured COM port.

        Returns:
            True if port opened successfully, False if falling back to mock.
        """
        try:
            import serial  # pyserial
            self._serial = serial.Serial(
                port=settings.SERIAL_PORT,
                baudrate=settings.BAUD_RATE,
                timeout=settings.SERIAL_TIMEOUT,
            )
            self._mock_mode = False
            logger.info("Serial port %s opened at %d baud", settings.SERIAL_PORT, settings.BAUD_RATE)
            return True
        except Exception as exc:
            if settings.MOCK_WHEN_UNAVAILABLE:
                logger.warning(
                    "Cannot open %s (%s) — running in MOCK mode",
                    settings.SERIAL_PORT, exc,
                )
                self._mock_mode = True
                return False
            raise SerialConnectionError(f"Cannot open {settings.SERIAL_PORT}: {exc}") from exc

    async def close(self) -> None:
        """Close the serial port gracefully."""
        self._running = False
        if self._serial and self._serial.is_open:
            self._serial.close()
            logger.info("Serial port %s closed", settings.SERIAL_PORT)

    def _read_line(self) -> Optional[str]:
        """
        Read one line from the serial port (blocking, called via executor).

        Returns:
            Decoded string or None on error.
        """
        try:
            raw = self._serial.readline()
            return raw.decode("utf-8", errors="replace").strip()
        except Exception as exc:
            logger.debug("Serial read error: %s", exc)
            return None

    @staticmethod
    def _validate(raw_value: str) -> Optional[float]:
        """
        Parse and validate a raw serial line as an ECG ADC value.

        Args:
            raw_value: Raw string from the serial port.

        Returns:
            Float ECG value if valid, None if corrupt/out-of-range.
        """
        try:
            value = float(raw_value.split(",")[0].strip())
            if _ADC_MIN <= value <= _ADC_MAX:
                return value
            logger.debug("Sample out of range: %s", value)
            return None
        except (ValueError, IndexError):
            return None

    async def stream(self) -> AsyncGenerator[float, None]:
        """
        Async generator that yields validated ECG float samples indefinitely.

        Yields:
            float: Validated ECG ADC value.
        """
        self._running = True
        interval = 1.0 / settings.SAMPLING_RATE  # seconds per sample

        if self._mock_mode:
            logger.info("Mock ECG stream started at %d Hz", settings.SAMPLING_RATE)
            # Use a sample counter for the waveform time so the ECG shape is
            # always perfectly periodic, regardless of asyncio.sleep jitter.
            sample_index = 0
            # Batch size: emit N samples per sleep to reduce scheduling overhead
            batch = max(1, settings.SAMPLING_RATE // 25)   # ~25 yields/sec
            batch_interval = batch * interval

            while self._running:
                t0 = time.monotonic()
                for _ in range(batch):
                    t_sec = sample_index * interval
                    yield _mock_ecg_sample(t_sec)
                    sample_index += 1

                # Sleep for the remainder of the batch window (drift-compensated)
                elapsed = time.monotonic() - t0
                sleep_time = max(0.0, batch_interval - elapsed)
                await asyncio.sleep(sleep_time)
            return

        # Real hardware stream
        loop = asyncio.get_event_loop()
        while self._running:
            try:
                line = await loop.run_in_executor(None, self._read_line)
                if line:
                    value = self._validate(line)
                    if value is not None:
                        yield value
                    # else: silently discard corrupt packet
                else:
                    await asyncio.sleep(0.001)
            except Exception as exc:
                logger.error("Serial stream error: %s", exc)
                await asyncio.sleep(1.0)   # brief pause before retry
