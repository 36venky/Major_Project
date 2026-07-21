"""
services/prediction_service.py
────────────────────────────────
ML-based cardiac risk prediction (Feature 5).

Wraps Model/predict.py.  Runs at most once per minute per patient.
Extracts 32 ECG features from the raw buffer, calls the ensemble model,
maps label → Risk_Level, and persists the result.
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

# Add Model/ directory to sys.path so predict.py can be imported
_MODEL_DIR = Path(__file__).resolve().parent.parent.parent.parent / "Model"
if str(_MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(_MODEL_DIR))

# Label → Risk_Level mapping
_LABEL_TO_RISK: dict[str, str] = {
    "N":    "Low",
    "SVEB": "Moderate",
    "F":    "Moderate",
    "VEB":  "High",
    "Q":    "Moderate",
}

# Minimum seconds between predictions per patient
_PREDICTION_INTERVAL = 60


class PredictionService:
    """
    Generates per-patient cardiac risk predictions from live ECG data.

    Call `maybe_predict(patient_id, raw_buffer)` after each analysis cycle.
    The service enforces a 60-second minimum interval per patient.
    """

    def __init__(self) -> None:
        self._last_predicted: dict[str, datetime] = {}
        self._predict_fn = None   # loaded lazily
        self._proba_fn   = None
        self._available  = False
        self._load_model()

    def _load_model(self) -> None:
        try:
            import predict as _predict  # noqa: PLC0415
            self._predict_fn = _predict.predict
            self._proba_fn   = _predict.predict_proba
            self._available  = True
            logger.info("Prediction model loaded from %s", _MODEL_DIR)
        except Exception as exc:
            logger.warning("Prediction model not available: %s — risk prediction disabled.", exc)

    # ── Public API ────────────────────────────────────────

    async def maybe_predict(
        self,
        patient_id: str,
        raw_buffer: deque,
        fs: int = 250,
    ) -> Optional[dict]:
        """
        Run a prediction if the cooldown has elapsed and enough data exists.

        Returns a dict with keys: risk_percentage, risk_level, majority_label
        or None if skipped / unavailable.
        """
        if not self._available:
            return None

        now = datetime.now(timezone.utc)
        last = self._last_predicted.get(patient_id)
        if last and (now - last) < timedelta(seconds=_PREDICTION_INTERVAL):
            return None

        features = await asyncio.get_event_loop().run_in_executor(
            None, self._extract_features, list(raw_buffer), fs
        )
        if features is None:
            logger.debug("Not enough ECG features for patient=%s — skipping prediction.", patient_id)
            return None

        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None, self._predict_fn, features, "all"
            )
            majority = result.get("majority", "N")
            risk_level = _LABEL_TO_RISK.get(majority, "Moderate")

            proba_dict = await asyncio.get_event_loop().run_in_executor(
                None, self._proba_fn, features, "xgb"
            )
            risk_pct = round(proba_dict.get(majority, 0.0) * 100, 1)

            self._last_predicted[patient_id] = now

            await self._persist(patient_id, risk_pct, risk_level, majority)

            logger.info(
                "Risk prediction for patient=%s: %s (%.1f%%) label=%s",
                patient_id, risk_level, risk_pct, majority,
            )
            return {"risk_percentage": risk_pct, "risk_level": risk_level, "majority_label": majority}

        except Exception as exc:
            logger.error("Prediction failed for patient=%s: %s", patient_id, exc)
            return None

    # ── Feature extraction ────────────────────────────────

    @staticmethod
    def _extract_features(raw_buffer: list[float], fs: int) -> Optional[list[float]]:
        """
        Extract 32 ECG features from raw ADC buffer.

        Uses a simplified approach: compute RR-interval statistics and
        waveform morphology from the last detected beat pair.
        Returns None if there is insufficient data.
        """
        try:
            from scipy.signal import find_peaks, butter, filtfilt

            if len(raw_buffer) < fs * 5:   # need at least 5 seconds
                return None

            # Normalise
            arr = np.array(raw_buffer[-fs * 10:], dtype=np.float64)
            arr = (arr - arr.mean()) / (arr.std() + 1e-8)

            # Bandpass filter 0.5–40 Hz
            b, a = butter(4, [0.5 / (fs / 2), 40.0 / (fs / 2)], btype="band")
            filtered = filtfilt(b, a, arr)

            # Detect R-peaks
            min_dist = int(0.5 * fs)
            peaks, _ = find_peaks(filtered, distance=min_dist, height=0.5)
            if len(peaks) < 3:
                return None

            # Use last 3 beats to compute 2-lead–like features (replicated for lead 1 and lead 2)
            rr_intervals = np.diff(peaks) / fs  # in seconds

            def _beat_features(peak_idx: int) -> list[float]:
                start = max(0, peak_idx - int(0.3 * fs))
                end   = min(len(filtered), peak_idx + int(0.5 * fs))
                segment = filtered[start:end]
                if len(segment) < 10:
                    return [0.0] * 16

                r_peak  = float(filtered[peak_idx])
                q_idx   = max(0, peak_idx - int(0.04 * fs))
                s_idx   = min(len(filtered) - 1, peak_idx + int(0.04 * fs))
                p_idx   = max(0, peak_idx - int(0.15 * fs))
                t_idx   = min(len(filtered) - 1, peak_idx + int(0.3 * fs))

                q_peak  = float(filtered[q_idx])
                s_peak  = float(filtered[s_idx])
                p_peak  = float(filtered[p_idx])
                t_peak  = float(filtered[t_idx])

                qrs_int = float(s_idx - q_idx) / fs
                pq_int  = float(peak_idx - p_idx) / fs
                qt_int  = float(t_idx - q_idx) / fs
                st_int  = float(t_idx - s_idx) / fs

                # QRS morphology: 5 equidistant samples in QRS window
                morph_pts = np.linspace(q_idx, s_idx, 5, dtype=int)
                morph = [float(filtered[i]) for i in morph_pts]

                pre_rr  = float(rr_intervals[-2]) if len(rr_intervals) >= 2 else 0.0
                post_rr = float(rr_intervals[-1]) if len(rr_intervals) >= 1 else 0.0

                return [pre_rr, post_rr, p_peak, t_peak, r_peak, s_peak, q_peak,
                        qrs_int, pq_int, qt_int, st_int] + morph  # 16 features

            # Two "leads" using the last two detected beats
            feat1 = _beat_features(peaks[-2])
            feat2 = _beat_features(peaks[-1])

            features = feat1 + feat2   # 32 total
            if len(features) != 32:
                return None
            return features

        except Exception as exc:
            logger.debug("Feature extraction error: %s", exc)
            return None

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
