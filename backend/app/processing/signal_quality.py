"""
processing/signal_quality.py
─────────────────────────────
ECG signal quality assessment.

Quality is estimated from three heuristics:
  1. SNR proxy   – ratio of signal variance to high-frequency noise variance
  2. Flatline    – detects flat-line / lead-off (near-zero variance)
  3. Clipping    – detects ADC saturation (many samples near min/max)

Returns a 0–100 integer score and a human-readable label.

Labels: Excellent (≥ 85) | Good (≥ 65) | Moderate (≥ 40) | Poor (< 40)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger("processing.signal_quality")


# ── Quality result ─────────────────────────────────────────

@dataclass
class SignalQualityResult:
    score: int              # 0–100
    label: str              # Excellent | Good | Moderate | Poor
    reason: Optional[str]   # Human-readable cause (for alerts)
    is_flatline: bool
    is_clipped:  bool


_LABELS = [
    (85, "Excellent"),
    (65, "Good"),
    (40, "Moderate"),
    (0,  "Poor"),
]


def _score_to_label(score: int) -> str:
    for threshold, label in _LABELS:
        if score >= threshold:
            return label
    return "Poor"


# ── Public API ────────────────────────────────────────────

def assess_signal_quality(
    raw_signal: np.ndarray,
    filtered_signal: Optional[np.ndarray] = None,
    fs: int = None,
) -> SignalQualityResult:
    """
    Estimate signal quality for an ECG window.

    Args:
        raw_signal:      Raw ADC samples from the ECG sensor.
        filtered_signal: Bandpass-filtered version (optional; improves accuracy).
        fs:              Sampling frequency (Hz).

    Returns:
        SignalQualityResult with score (0–100), label, and reason.
    """
    fs = fs or settings.SAMPLING_RATE

    if len(raw_signal) < 2:
        return SignalQualityResult(score=0, label="Poor", reason="Insufficient data",
                                   is_flatline=True, is_clipped=False)

    arr = np.array(raw_signal, dtype=np.float64)
    score = 100
    reason: Optional[str] = None
    is_flatline = False
    is_clipped  = False

    # ── Check 1: Flatline / lead-off detection ────────────
    std = float(np.std(arr))
    if std < 1e-4:
        return SignalQualityResult(score=0, label="Poor",
                                   reason="Flatline – possible lead-off",
                                   is_flatline=True, is_clipped=False)

    # ── Check 2: Clipping (ADC saturation) ────────────────
    mn, mx = float(np.min(arr)), float(np.max(arr))
    range_val = mx - mn
    if range_val > 0:
        clip_ratio_low  = float(np.mean(arr <= mn + 0.01 * range_val))
        clip_ratio_high = float(np.mean(arr >= mx - 0.01 * range_val))
        clip_ratio = max(clip_ratio_low, clip_ratio_high)
        if clip_ratio > 0.05:   # >5% samples at rail
            penalty = min(60, int(clip_ratio * 300))
            score -= penalty
            is_clipped = True
            reason = "Signal clipping – possible electrode saturation"

    # ── Check 3: High-frequency noise via SNR proxy ───────
    if filtered_signal is not None and len(filtered_signal) == len(arr):
        filt = np.array(filtered_signal, dtype=np.float64)
        noise = arr - filt
        signal_power = float(np.var(filt))
        noise_power  = float(np.var(noise))
        if signal_power > 0:
            snr = signal_power / (noise_power + 1e-10)
            # Map SNR to score contribution (log scale)
            snr_score = int(min(40, 10 * np.log10(snr + 1)))
        else:
            snr_score = 0
        # Blend: 60% base score + 40% SNR score
        score = int(0.6 * score + 0.4 * (60 + snr_score))
    else:
        # Rough quality from peak-to-peak amplitude normalisation
        if range_val > 0:
            normalised_std = std / range_val
            amplitude_score = int(min(40, normalised_std * 200))
            score = int(0.6 * score + 0.4 * (60 + amplitude_score))

    # Clamp
    score = max(0, min(100, score))
    label = _score_to_label(score)

    if not reason:
        if score < settings.SIGNAL_QUALITY_POOR:
            reason = "High electrical noise or motion artifact"
        elif score < settings.SIGNAL_QUALITY_WARN:
            reason = "Moderate noise – check electrode contact"

    return SignalQualityResult(
        score=score,
        label=label,
        reason=reason,
        is_flatline=is_flatline,
        is_clipped=is_clipped,
    )
