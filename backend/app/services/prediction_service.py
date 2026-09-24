"""
services/prediction_service.py
────────────────────────────────
ML-based cardiac risk prediction.

Wraps Model/predict.py (M2 XGBoost — AAMI 5-class beat classifier).
Runs at most once per minute per patient.

Pipeline:
  1. Bandpass-filter the raw buffer  (0.5 – 45 Hz, same as M2/Preprocess.py)
  2. Detect R-peaks
  3. Extract the most recent valid beat window  (90 samples before + 100 after R-peak)
  4. Z-score normalise the window
  5. Run XGBoost inference  → integer label 0-4
  6. Map label → risk level  → persist + broadcast

AAMI label → risk level:
    N (Normal)                 → Low
    S (Supraventricular)       → Moderate
    V (Ventricular ectopic)    → High
    F (Fusion)                 → Moderate
    Q (Unclassifiable / Paced) → Moderate
"""

from __future__ import annotations

import sys
import asyncio
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import numpy as np

from app.core.logger import get_logger
from app.database.database import AsyncSessionLocal
from app.database import crud

logger = get_logger("services.prediction")

# ---------------------------------------------------------------------------
# Add Model/ directory to sys.path so predict.py can be imported directly
# ---------------------------------------------------------------------------
_MODEL_DIR = Path(__file__).resolve().parent.parent.parent.parent / "Model"
if str(_MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(_MODEL_DIR))

# ---------------------------------------------------------------------------
# AAMI label → clinical risk level (aligned with M2 class scheme)
# ---------------------------------------------------------------------------
_LABEL_TO_RISK: dict[str, str] = {
    "N": "Low",       # Normal sinus beat
    "S": "Moderate",  # Supraventricular ectopic (PAC, etc.)
    "V": "High",      # Ventricular ectopic (PVC, etc.)
    "F": "Moderate",  # Fusion beat
    "Q": "Moderate",  # Unclassifiable / paced beat
}

# Human-readable beat-type names shown in the frontend RiskCard
_LABEL_DISPLAY: dict[str, str] = {
    "N": "Normal Sinus Beat",
    "S": "Supraventricular Ectopic",
    "V": "Ventricular Ectopic",
    "F": "Fusion Beat",
    "Q": "Unclassifiable Beat",
}

# Preprocessing constants — must match M2/Preprocess.py exactly
_WINDOW_BEFORE = 90
_WINDOW_AFTER  = 100
_N_FEATURES    = _WINDOW_BEFORE + _WINDOW_AFTER   # 190

# Minimum seconds between predictions per patient
_PREDICTION_INTERVAL = 60


class PredictionService:
    """
    Generates per-patient cardiac risk predictions from live ECG data.

    Call `maybe_predict(patient_id, raw_buffer, fs)` after each analysis cycle.
    The service enforces a 60-second minimum interval per patient.
    """

    def __init__(self) -> None:
        self._last_predicted: dict[str, datetime] = {}
        self._predict_fn     = None   # loaded lazily
        self._proba_fn       = None
        self._available      = False
        self._load_model()

    def _load_model(self) -> None:
        try:
            import predict as _predict  # noqa: PLC0415
            self._predict_fn = _predict.predict
            self._proba_fn   = _predict.predict_proba
            self._available  = True
            logger.info("M2 XGBoost model loaded from %s", _MODEL_DIR)
        except Exception as exc:
            logger.warning(
                "Prediction model not available: %s — risk prediction disabled.", exc
            )

    # ── Public API ────────────────────────────────────────

    async def maybe_predict(
        self,
        patient_id: str,
        raw_buffer: deque,
        fs: int = 360,
    ) -> Optional[dict]:
        """
        Run a prediction if the cooldown has elapsed and enough data exists.

        Returns a dict:
            {
                "risk_percentage": float,
                "risk_level":      str,   # "Low" | "Moderate" | "High"
                "majority_label":  str,   # short AAMI code, e.g. "N"
                "beat_type":       str,   # human-readable, e.g. "Normal Sinus Beat"
            }
        or None if skipped / unavailable.
        """
        if not self._available:
            return None

        now  = datetime.now(timezone.utc)
        last = self._last_predicted.get(patient_id)
        if last and (now - last) < timedelta(seconds=_PREDICTION_INTERVAL):
            return None

        beat = await asyncio.get_event_loop().run_in_executor(
            None, self._extract_beat, list(raw_buffer), fs
        )
        if beat is None:
            logger.debug(
                "Could not extract a valid beat window for patient=%s — skipping.", patient_id
            )
            return None

        try:
            result     = await asyncio.get_event_loop().run_in_executor(
                None, self._predict_fn, beat, "all"
            )
            majority   = result.get("majority", "N")
            risk_level = _LABEL_TO_RISK.get(majority, "Moderate")
            beat_type  = _LABEL_DISPLAY.get(majority, majority)

            proba_dict = await asyncio.get_event_loop().run_in_executor(
                None, self._proba_fn, beat, "xgb"
            )
            # Risk percentage = confidence in the predicted class
            risk_pct = round(proba_dict.get(majority, 0.0) * 100, 1)

            self._last_predicted[patient_id] = now

            await self._persist(patient_id, risk_pct, risk_level, majority)

            logger.info(
                "Risk prediction  patient=%s  label=%s (%s)  risk=%s  confidence=%.1f%%",
                patient_id, majority, beat_type, risk_level, risk_pct,
            )

            return {
                "risk_percentage": risk_pct,
                "risk_level":      risk_level,
                "majority_label":  majority,
                "beat_type":       beat_type,
            }

        except Exception as exc:
            logger.error("Prediction failed for patient=%s: %s", patient_id, exc)
            return None

    # ── Beat extraction (M2/Preprocess.py pipeline) ───────

    @staticmethod
    def _extract_beat(raw_buffer: list[float], fs: int) -> Optional[np.ndarray]:
        """
        Extract and preprocess the most recent valid beat window from the buffer.

        Replicates M2/Preprocess.py exactly:
          1. Bandpass filter  0.5 – 45 Hz  (Butterworth order 2, zero-phase)
          2. Detect R-peaks   (scipy find_peaks, min distance 0.3 s)
          3. Slice window     [peak - 90 : peak + 100]  → 190 samples
          4. Z-score normalise

        Returns a float32 array of shape (190,), or None if extraction fails.
        """
        try:
            from scipy.signal import butter, filtfilt, find_peaks

            # Need at least 3 seconds of data to detect reliable peaks
            min_samples = int(fs * 3)
            if len(raw_buffer) < min_samples:
                return None

            arr = np.array(raw_buffer, dtype=np.float64)

            # ── Step 1: bandpass filter (matches Preprocess.py) ──
            nyquist = 0.5 * fs
            b, a = butter(2, [0.5 / nyquist, 45.0 / nyquist], btype="band")
            filtered = filtfilt(b, a, arr)

            # ── Step 2: R-peak detection ──
            min_dist = max(1, int(0.3 * fs))   # 0.3 s → up to ~200 BPM
            peaks, _ = find_peaks(
                filtered,
                distance=min_dist,
                height=np.mean(filtered),
            )
            if len(peaks) < 1:
                return None

            # Use the last valid R-peak that has a full window around it
            for peak in reversed(peaks):
                start = peak - _WINDOW_BEFORE
                end   = peak + _WINDOW_AFTER
                if start >= 0 and end < len(filtered):
                    segment = filtered[start:end]
                    # ── Step 4: z-score normalise ──
                    std = np.std(segment)
                    if std == 0:
                        normalised = segment - np.mean(segment)
                    else:
                        normalised = (segment - np.mean(segment)) / std
                    return normalised.astype(np.float32)

            return None

        except Exception as exc:
            logger.debug("Beat extraction error: %s", exc)
            return None

    # ── Persistence ───────────────────────────────────────

    async def _persist(
        self,
        patient_id:      str,
        risk_percentage: float,
        risk_level:      str,
        majority_label:  str,
    ) -> None:
        try:
            async with AsyncSessionLocal() as db:
                await crud.save_risk_prediction(
                    db,
                    patient_id=patient_id,
                    risk_percentage=risk_percentage,
                    risk_level=risk_level,
                    majority_label=majority_label,
                )
                await db.commit()
        except Exception as exc:
            logger.error("Failed to persist risk prediction: %s", exc)

    @property
    def available(self) -> bool:
        return self._available


# ── Singleton ─────────────────────────────────────────────
prediction_service = PredictionService()
