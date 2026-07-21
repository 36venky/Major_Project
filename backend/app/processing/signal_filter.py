"""
processing/signal_filter.py
────────────────────────────
Bandpass filter for raw ECG signals.

Pipeline stages implemented here:
  1. High-pass filter  → removes baseline wander (DC drift)
  2. Low-pass filter   → removes high-frequency noise (EMI, motion)
  3. Combined bandpass → single-call convenience wrapper

All filters are zero-phase (forward-backward pass via filtfilt) to avoid
phase distortion in the QRS complex.

References:
  - Pan & Tompkins (1985) — real-time QRS detection algorithm
  - AHA/AAMI EC11 standard ECG frequency range: 0.05–150 Hz
"""

from __future__ import annotations

import numpy as np
from scipy.signal import butter, filtfilt, iirnotch

from app.core.config import settings
from app.core.exceptions import SignalProcessingError
from app.core.logger import get_logger

logger = get_logger("processing.signal_filter")


# ── Filter coefficient cache (reuse for performance) ──────

_filter_cache: dict[tuple, tuple] = {}


def _butter_bandpass(
    lowcut: float,
    highcut: float,
    fs: int,
    order: int,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute Butterworth bandpass filter coefficients.

    Args:
        lowcut:  High-pass cutoff frequency (Hz) — removes baseline wander.
        highcut: Low-pass cutoff frequency (Hz)  — removes noise.
        fs:      Sampling frequency (Hz).
        order:   Filter order (higher = steeper roll-off, more lag).

    Returns:
        (b, a) filter coefficient arrays.
    """
    cache_key = (lowcut, highcut, fs, order)
    if cache_key not in _filter_cache:
        nyq = fs / 2.0
        low  = lowcut  / nyq
        high = highcut / nyq
        # Clamp to valid range (0, 1) exclusive
        low  = max(1e-6, min(low,  0.999))
        high = max(1e-6, min(high, 0.999))
        if low >= high:
            raise SignalProcessingError(
                f"Invalid bandpass range: lowcut={lowcut} >= highcut={highcut}"
            )
        b, a = butter(order, [low, high], btype="band")
        _filter_cache[cache_key] = (b, a)
    return _filter_cache[cache_key]


def _butter_notch(freq: float, fs: int, quality: float = 30.0) -> tuple:
    """
    Compute IIR notch filter coefficients to suppress power-line interference.

    Args:
        freq:    Notch frequency (Hz), typically 50 or 60.
        fs:      Sampling frequency (Hz).
        quality: Q factor — higher = narrower notch.
    """
    cache_key = ("notch", freq, fs, quality)
    if cache_key not in _filter_cache:
        w0 = freq / (fs / 2.0)
        b, a = iirnotch(w0, quality)
        _filter_cache[cache_key] = (b, a)
    return _filter_cache[cache_key]


# ── Public API ────────────────────────────────────────────

def bandpass_filter(
    signal: np.ndarray,
    fs: int = None,
    lowcut: float = None,
    highcut: float = None,
    order: int = None,
) -> np.ndarray:
    """
    Apply zero-phase Butterworth bandpass filter to an ECG signal array.

    Defaults are read from settings (config.yaml).

    Args:
        signal:  1-D numpy array of raw ECG samples.
        fs:      Sampling frequency (Hz).
        lowcut:  High-pass cutoff (Hz) — defaults to settings.HIGHPASS_CUTOFF.
        highcut: Low-pass cutoff (Hz)  — defaults to settings.LOWPASS_CUTOFF.
        order:   Filter order          — defaults to settings.FILTER_ORDER.

    Returns:
        Filtered signal as float64 numpy array.

    Raises:
        SignalProcessingError: if signal is too short or parameters are invalid.
    """
    fs      = fs      or settings.SAMPLING_RATE
    lowcut  = lowcut  or settings.HIGHPASS_CUTOFF
    highcut = highcut or settings.LOWPASS_CUTOFF
    order   = order   or settings.FILTER_ORDER

    if len(signal) < 3 * order:
        # Not enough samples to filter — return as-is
        return signal.astype(np.float64)

    try:
        b, a = _butter_bandpass(lowcut, highcut, fs, order)
        filtered = filtfilt(b, a, signal)
        return filtered.astype(np.float64)
    except Exception as exc:
        logger.warning("Bandpass filter error: %s", exc)
        raise SignalProcessingError(f"Bandpass filter failed: {exc}") from exc


def notch_filter(
    signal: np.ndarray,
    freq: float = 50.0,
    fs: int = None,
    quality: float = 30.0,
) -> np.ndarray:
    """
    Apply a notch filter to remove power-line interference (50/60 Hz).

    Args:
        signal:  1-D numpy array of ECG samples.
        freq:    Interference frequency to remove (50 Hz for India, 60 Hz for USA).
        fs:      Sampling frequency (Hz).
        quality: Q factor — width of the notch.

    Returns:
        Filtered signal array.
    """
    fs = fs or settings.SAMPLING_RATE
    if len(signal) < 10:
        return signal.astype(np.float64)

    try:
        b, a = _butter_notch(freq, fs, quality)
        return filtfilt(b, a, signal).astype(np.float64)
    except Exception as exc:
        logger.warning("Notch filter error: %s", exc)
        return signal.astype(np.float64)


def full_filter_pipeline(
    signal: np.ndarray,
    fs: int = None,
) -> np.ndarray:
    """
    Run the complete ECG filter chain:
      1. Bandpass (0.5–40 Hz)
      2. 50 Hz notch

    Args:
        signal: Raw ECG sample array.
        fs:     Sampling frequency.

    Returns:
        Fully filtered ECG signal.
    """
    fs = fs or settings.SAMPLING_RATE
    filtered = bandpass_filter(signal, fs=fs)
    filtered = notch_filter(filtered, freq=50.0, fs=fs)
    return filtered
