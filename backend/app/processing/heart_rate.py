"""
processing/heart_rate.py
─────────────────────────
Heart rate (BPM) calculation from RR intervals.

Provides:
  - instantaneous BPM from a single RR interval
  - average BPM from a window of R-peaks
  - rolling BPM estimator for real-time streaming
"""

from __future__ import annotations

from collections import deque
from typing import Optional

import numpy as np

from app.core.config import settings
from app.core.logger import get_logger
from app.processing.r_peak_detection import compute_rr_intervals, detect_r_peaks

logger = get_logger("processing.heart_rate")


# ── Stateless functions ───────────────────────────────────

def bpm_from_rr(rr_seconds: float) -> float:
    """
    Convert a single RR interval to beats per minute.

    Args:
        rr_seconds: Duration between two consecutive R-peaks in seconds.

    Returns:
        Heart rate in BPM. Returns 0.0 for invalid input.
    """
    if rr_seconds <= 0:
        return 0.0
    return round(60.0 / rr_seconds, 1)


def average_bpm(r_peaks: np.ndarray, fs: int = None) -> float:
    """
    Calculate mean heart rate from a set of R-peak positions.

    Args:
        r_peaks: Sorted array of R-peak sample indices.
        fs:      Sampling frequency (Hz).

    Returns:
        Average BPM as float. Returns 0.0 if fewer than 2 peaks.
    """
    fs = fs or settings.SAMPLING_RATE
    rr = compute_rr_intervals(r_peaks, fs)
    if len(rr) == 0:
        return 0.0
    # Exclude physiologically impossible intervals (< 0.3 s or > 2.0 s)
    valid = rr[(rr >= 0.3) & (rr <= 2.0)]
    if len(valid) == 0:
        return 0.0
    return round(60.0 / float(np.mean(valid)), 1)


def bpm_from_signal_window(
    signal_window: np.ndarray,
    fs: int = None,
) -> float:
    """
    End-to-end BPM from a raw signal window.

    Applies filtering internally — accepts raw ECG samples.

    Args:
        signal_window: Raw ECG sample array (≥ 1 second recommended).
        fs:            Sampling frequency (Hz).

    Returns:
        Estimated BPM. Returns 0.0 on error or insufficient data.
    """
    from app.processing.signal_filter import full_filter_pipeline  # avoid circular import

    fs = fs or settings.SAMPLING_RATE
    try:
        filtered = full_filter_pipeline(signal_window, fs=fs)
        peaks    = detect_r_peaks(filtered, fs=fs)
        return average_bpm(peaks, fs)
    except Exception as exc:
        logger.debug("BPM from window failed: %s", exc)
        return 0.0


# ── Stateful rolling estimator ────────────────────────────

class RollingBPMEstimator:
    """
    Maintains a sliding window of raw ECG samples for continuous BPM estimation.

    Designed for streaming use: call `push(sample)` for each incoming sample.
    Call `get_bpm()` to retrieve the current BPM estimate.

    Args:
        window_seconds: Duration of the analysis window (default: 5 s).
        fs:             Sampling frequency (Hz).
    """

    def __init__(self, window_seconds: float = 5.0, fs: int = None):
        self.fs = fs or settings.SAMPLING_RATE
        self._window_size = int(window_seconds * self.fs)
        self._buffer: deque[float] = deque(maxlen=self._window_size)
        self._current_bpm: float = 0.0

    def push(self, sample: float) -> None:
        """Add a single ECG sample to the rolling buffer."""
        self._buffer.append(sample)

    def push_batch(self, samples: list[float]) -> None:
        """Add multiple samples at once."""
        self._buffer.extend(samples)

    def get_bpm(self) -> float:
        """
        Estimate current BPM from the buffered window.

        Returns 0.0 if the buffer doesn't have enough data.
        """
        if len(self._buffer) < self.fs:  # need at least 1 second
            return self._current_bpm

        arr = np.array(self._buffer, dtype=np.float64)
        bpm = bpm_from_signal_window(arr, fs=self.fs)

        # Smoothing: blend new estimate with previous (reduces jitter)
        if bpm > 0:
            if self._current_bpm == 0:
                self._current_bpm = bpm
            else:
                self._current_bpm = round(0.7 * self._current_bpm + 0.3 * bpm, 1)

        return self._current_bpm

    def reset(self) -> None:
        """Clear buffer and reset BPM estimate."""
        self._buffer.clear()
        self._current_bpm = 0.0
