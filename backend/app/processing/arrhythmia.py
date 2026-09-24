"""
processing/arrhythmia.py
─────────────────────────
Rule-based arrhythmia detector.

This module implements interpretable heuristic rules derived from clinical
ECG criteria. It is designed as a plug-in point for ML-based classification:
the `classify` function signature is stable and can be replaced with a model
inference call without modifying any other module.

Detected conditions:
  - Normal Sinus Rhythm
  - Sinus Tachycardia
  - Sinus Bradycardia
  - Possible Atrial Fibrillation (irregular RR intervals)
  - Possible Premature Beat (ectopic beat)
  - High Heart Rate (> critical threshold)
  - Low Heart Rate  (< critical threshold)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from app.core.config import settings
from app.core.logger import get_logger
from app.processing.r_peak_detection import compute_rr_intervals

logger = get_logger("processing.arrhythmia")


# ── Result model ──────────────────────────────────────────

@dataclass
class ArrhythmiaResult:
    rhythm:     str             # Human-readable rhythm label
    confidence: int             # 0–100 %
    risk_level: str             # Low | Medium | High | Critical
    is_abnormal: bool
    details:    str = ""        # Extra clinical detail
    flags:      list[str] = field(default_factory=list)  # raw flag names


# ── Internal helpers ──────────────────────────────────────

def _rmssd(rr: np.ndarray) -> float:
    """Root mean square of successive RR differences (HRV metric)."""
    if len(rr) < 2:
        return 0.0
    return float(np.sqrt(np.mean(np.diff(rr) ** 2)))


def _cv(rr: np.ndarray) -> float:
    """Coefficient of variation of RR intervals."""
    if len(rr) == 0 or np.mean(rr) == 0:
        return 0.0
    return float(np.std(rr) / np.mean(rr))


# ── Main classifier ───────────────────────────────────────

def classify(
    r_peaks: np.ndarray,
    bpm: float,
    fs: int = None,
) -> ArrhythmiaResult:
    """
    Classify cardiac rhythm from detected R-peaks and current BPM.

    This function implements rule-based classification. Replace the body
    of this function with ML model inference to upgrade without breaking
    any downstream code.

    Args:
        r_peaks: Sorted array of R-peak sample indices.
        bpm:     Current heart rate in BPM.
        fs:      Sampling frequency (Hz).

    Returns:
        ArrhythmiaResult containing rhythm label, confidence, and risk.
    """
    fs = fs or settings.SAMPLING_RATE
    rr = compute_rr_intervals(r_peaks, fs)

    flags: list[str] = []
    rhythm    = "Normal Sinus Rhythm"
    confidence = 95
    risk       = "Low"
    is_abnormal = False
    details    = ""

    # ── Rule 1: Not enough data ───────────────────────────
    if len(rr) < 3:
        return ArrhythmiaResult(
            rhythm="Insufficient Data",
            confidence=0,
            risk_level="Low",
            is_abnormal=False,
            details="Need more R-peaks for analysis",
        )

    # Valid RR filter
    valid_rr = rr[(rr >= 0.25) & (rr <= 2.5)]
    if len(valid_rr) < 2:
        valid_rr = rr

    # Need at least 5 valid RR intervals for reliable rhythm classification
    if len(valid_rr) < 5:
        return ArrhythmiaResult(
            rhythm="Insufficient Data",
            confidence=0,
            risk_level="Low",
            is_abnormal=False,
            details="Need more beats for rhythm analysis",
        )

    mean_rr = float(np.mean(valid_rr))
    cv      = _cv(valid_rr)

    # ── Rule 2: Critical BPM ──────────────────────────────
    if bpm >= settings.HR_CRITICAL_HIGH:
        flags.append("CRITICAL_TACHYCARDIA")
        rhythm      = "Critical Tachycardia"
        confidence  = 98
        risk        = "Critical"
        is_abnormal = True
        details     = f"Heart rate {bpm:.0f} BPM is critically elevated."
        return ArrhythmiaResult(rhythm=rhythm, confidence=confidence,
                                risk_level=risk, is_abnormal=is_abnormal,
                                details=details, flags=flags)

    if bpm <= settings.HR_CRITICAL_LOW and bpm > 0:
        flags.append("CRITICAL_BRADYCARDIA")
        rhythm      = "Critical Bradycardia"
        confidence  = 98
        risk        = "Critical"
        is_abnormal = True
        details     = f"Heart rate {bpm:.0f} BPM is critically low."
        return ArrhythmiaResult(rhythm=rhythm, confidence=confidence,
                                risk_level=risk, is_abnormal=is_abnormal,
                                details=details, flags=flags)

    # ── Rule 3: Irregular RR → possible AFib ──────────────
    # CV > 0.30 is a conservative threshold that reduces false positives
    # from signal noise while still catching clinically significant irregularity.
    # Require at least 6 valid RR intervals for this classification.
    if cv > 0.30 and len(valid_rr) >= 6:
        flags.append("IRREGULAR_RR")
        is_abnormal = True
        rhythm      = "Possible Atrial Fibrillation"
        confidence  = min(90, int((cv - 0.30) * 200 + 60))
        risk        = "High"
        details     = f"Irregular RR intervals (CV={cv:.2f}). Consult physician."
        logger.warning("Possible AFib detected — CV=%.3f bpm=%.1f", cv, bpm)
        return ArrhythmiaResult(rhythm=rhythm, confidence=confidence,
                                risk_level=risk, is_abnormal=is_abnormal,
                                details=details, flags=flags)

    # ── Rule 4: Premature beats (single short RR) ─────────
    successive_diffs = np.abs(np.diff(valid_rr))
    if len(successive_diffs) > 0:
        premature_threshold = 0.25 * mean_rr
        if np.any(successive_diffs > premature_threshold):
            flags.append("PREMATURE_BEAT")
            is_abnormal = True
            rhythm      = "Possible Premature Beat"
            confidence  = 75
            risk        = "Medium"
            details     = "Isolated ectopic beat detected in RR sequence."

    # ── Rule 5: Tachycardia / Bradycardia ─────────────────
    if not is_abnormal:
        if bpm > settings.HR_HIGH:
            flags.append("TACHYCARDIA")
            rhythm      = "Sinus Tachycardia"
            confidence  = 90
            risk        = "Medium"
            is_abnormal = True
            details     = f"BPM {bpm:.0f} exceeds normal range (>{settings.HR_HIGH})."
        elif bpm < settings.HR_LOW and bpm > 0:
            flags.append("BRADYCARDIA")
            rhythm      = "Sinus Bradycardia"
            confidence  = 90
            risk        = "Medium"
            is_abnormal = True
            details     = f"BPM {bpm:.0f} below normal range (<{settings.HR_LOW})."

    # ── Default: normal ───────────────────────────────────
    if not flags:
        flags.append("NORMAL")
        rhythm     = "Normal Sinus Rhythm"
        confidence = 97
        risk       = "Low"
        details    = "Rhythm is regular with normal rate."

    return ArrhythmiaResult(
        rhythm=rhythm,
        confidence=confidence,
        risk_level=risk,
        is_abnormal=is_abnormal,
        details=details,
        flags=flags,
    )
