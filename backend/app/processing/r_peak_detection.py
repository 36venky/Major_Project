"""
processing/r_peak_detection.py
───────────────────────────────
R-peak (QRS complex) detection in filtered ECG signals.

Algorithm:
  Simplified Pan–Tompkins inspired approach:
    1. Differentiate the filtered signal to emphasise slopes
    2. Square the derivative (amplify large peaks)
    3. Moving-window integration (smooth the energy envelope)
    4. Adaptive threshold on the integrated signal
    5. Enforce minimum inter-peak distance (refractory period)

This implementation is intentionally lightweight for real-time use.
More accurate algorithms (Hamilton–Tompkins, Christov, etc.) can be
plugged in by replacing the `detect_r_peaks` function signature.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import find_peaks

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger("processing.r_peak")


def detect_r_peaks(
    filtered_signal: np.ndarray,
    fs: int = None,
    min_distance: float = None,
    threshold_factor: float = None,
) -> np.ndarray:
    """
    Detect R-peak indices in a filtered ECG signal.

    Args:
        filtered_signal: 1-D array of bandpass-filtered ECG samples.
        fs:              Sampling frequency (Hz).
        min_distance:    Minimum seconds between R-peaks (default from settings).
        threshold_factor: Fraction of max signal used as peak threshold.

    Returns:
        1-D integer array of sample indices where R-peaks were detected.
        Returns empty array if signal is too short.
    """
    fs               = fs               or settings.SAMPLING_RATE
    min_distance     = min_distance     or settings.R_PEAK_MIN_DISTANCE
    threshold_factor = threshold_factor or settings.R_PEAK_THRESHOLD_FACTOR

    if len(filtered_signal) < fs:
        # Less than 1 second of data — not enough to detect peaks reliably
        return np.array([], dtype=int)

    try:
        # Step 1: Differentiate
        diff = np.diff(filtered_signal, prepend=filtered_signal[0])

        # Step 2: Square
        squared = diff ** 2

        # Step 3: Moving-window integration (window ≈ 150 ms)
        win = max(1, int(0.15 * fs))
        kernel = np.ones(win) / win
        integrated = np.convolve(squared, kernel, mode="same")

        # Step 4: Adaptive threshold
        threshold = threshold_factor * np.max(integrated)

        # Step 5: Find peaks
        min_samples = int(min_distance * fs)
        peaks, _ = find_peaks(
            integrated,
            height=threshold,
            distance=min_samples,
        )

        return peaks

    except Exception as exc:
        logger.warning("R-peak detection error: %s", exc)
        return np.array([], dtype=int)


def compute_rr_intervals(r_peaks: np.ndarray, fs: int = None) -> np.ndarray:
    """
    Calculate RR intervals (in seconds) from R-peak sample indices.

    Args:
        r_peaks: Array of R-peak sample indices.
        fs:      Sampling frequency (Hz).

    Returns:
        Array of RR intervals in seconds.
        Empty array if fewer than 2 peaks.
    """
    fs = fs or settings.SAMPLING_RATE
    if len(r_peaks) < 2:
        return np.array([], dtype=float)
    return np.diff(r_peaks).astype(float) / fs
