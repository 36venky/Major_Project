"""
services/prediction_service.py
────────────────────────────────
ML-based cardiac risk prediction — M2 XGBoost pipeline.

Directly ports the M2/PreprocessClassifyLog.py pipeline into the backend
so no external script or Model/predict.py shim is needed.

Pipeline (every 2 seconds, per patient):
  1.  Grab the last WINDOW_SECONDS of raw ADC samples from the live buffer
  2.  ADC → mV  : (adc - ADC_BASELINE) * ADC_TO_MV
  3.  Streaming Butterworth bandpass 0.5–45 Hz via sosfilt + persistent zi
  4.  Pan-Tompkins R-peak detection on the window
  5.  BPM  = (60 * SAMPLING_FREQ) / rr_samples   (no magic numbers)
  6.  Beat extraction: [peak-90 : peak+100] = 190 samples, z-score normalised
  7.  XGBoost predict_proba on every new beat (dedup via global peak index)
  8.  Majority vote across beats in window → AAMI class
  9.  Confidence = max predict_proba of the majority class
  10. SDNN / RMSSD from valid RR intervals (physiological gate)
  11. Abnormal-beat ratio
  12. Risk score 0-100  (BPM deviation + abnormal ratio + HRV penalty)
  13. Persist to DB  →  return enriched dict for WebSocket broadcast

AAMI class → risk level:
    N → Low
    S → Moderate
    V → High          ← triggers VENTRICULAR_BEAT alert
    F → Moderate
    Q → Moderate

NOTE: The 0-100 risk score is a prototype/project metric.
      It is NOT a clinically validated diagnostic score.
"""

from __future__ import annotations

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

# ── XGBoost model import (loaded once at module level) ────
try:
    from xgboost import XGBClassifier as _XGBClassifier
    _XGBOOST_AVAILABLE = True
except ImportError:
    _XGBClassifier = None
    _XGBOOST_AVAILABLE = False

# ── scipy imports ─────────────────────────────────────────
try:
    from scipy.signal import butter, sosfilt, sosfilt_zi
    _SCIPY_AVAILABLE = True
except ImportError:
    _SCIPY_AVAILABLE = False

# ===========================================================
# ███  PIPELINE CONSTANTS  (single source of truth)  ███
# ===========================================================
SAMPLING_FREQ   = 192          # Hz — must match ESP32 firmware

# ADC calibration — measured from real hardware (ESP32 + AD8232)
# Observed resting ADC values: 1600–2000, midpoint ≈ 1800.
# ADC_BASELINE : resting (0 mV) ADC count
# ADC_TO_MV    : (3.3 V full-scale) / (4095 counts) ≈ 0.000806 V/count = 0.806 mV/count
#                For the AD8232 the ECG swing is typically ±1 mV, i.e. ±~1240 counts
#                around the baseline, so 1 count ≈ 0.000806 mV is correct.
ADC_BASELINE    = 1800         # raw ADC at 0 mV — real hardware midpoint
ADC_TO_MV       = 0.000806     # mV per ADC count  (3.3 V / 4095)

WINDOW_SECONDS  = 10           # seconds of ECG per analysis window
WINDOW_STEP_S   = 2            # seconds between successive windows  ← every 2 s
WINDOW_SAMPLES  = SAMPLING_FREQ * WINDOW_SECONDS    # 1920
WINDOW_STEP     = SAMPLING_FREQ * WINDOW_STEP_S     # 384

LOW_HZ          = 0.5
HIGH_HZ         = 45.0
FILTER_ORDER    = 2

WINDOW_B4_PEAK  = 90
WINDOW_AF_PEAK  = 100
BEAT_LENGTH     = WINDOW_B4_PEAK + WINDOW_AF_PEAK   # 190

# Physiological BPM gates
BPM_MIN         = 30
BPM_MAX         = 220
RR_MIN_SAMPLES  = int((60 / BPM_MAX) * SAMPLING_FREQ)   # ≈52
RR_MAX_SAMPLES  = int((60 / BPM_MIN) * SAMPLING_FREQ)   # ≈384
ROLLING_RR_WIN  = 8

MODEL_PATH = str(Path(__file__).resolve().parent.parent.parent / ".." / "M2" / "saved_models" / "ecg_xgboost.json")

# AAMI mappings
_LABEL_TO_RISK: dict[str, str] = {
    "N": "Low",
    "S": "Moderate",
    "V": "High",
    "F": "Moderate",
    "Q": "Moderate",
}
_LABEL_DISPLAY: dict[str, str] = {
    "N": "Normal Sinus Beat",
    "S": "Supraventricular Ectopic",
    "V": "Ventricular Ectopic",
    "F": "Fusion Beat",
    "Q": "Unclassifiable Beat",
}
CLASS_NAMES: dict[int, str] = {0: "N", 1: "S", 2: "V", 3: "F", 4: "Q"}


# ===========================================================
# ADC → mV conversion
# ===========================================================
def adc_to_mv(adc: float) -> float:
    """Convert raw ESP32 ADC sample to millivolts."""
    return (adc - ADC_BASELINE) * ADC_TO_MV


# ===========================================================
# Streaming Butterworth filter
# ===========================================================
class _StreamingFilter:
    """
    Butterworth bandpass (sosfilt) with persistent zi so successive
    chunks are phase-continuous.  Thread-safe per-instance.
    """
    def __init__(self):
        if not _SCIPY_AVAILABLE:
            self.sos = None
            self.zi  = None
            return
        nyq = SAMPLING_FREQ / 2.0
        self.sos = butter(FILTER_ORDER, [LOW_HZ / nyq, HIGH_HZ / nyq],
                          btype="band", output="sos")
        self.zi  = sosfilt_zi(self.sos)

    def filter(self, chunk: np.ndarray) -> np.ndarray:
        if self.sos is None or len(chunk) == 0:
            return chunk
        out, self.zi = sosfilt(self.sos, chunk, zi=self.zi)
        return out

    def reset(self):
        if self.sos is not None:
            self.zi = sosfilt_zi(self.sos)


# ===========================================================
# Pan-Tompkins R-peak detector
# ===========================================================
def _detect_r_peaks(signal: np.ndarray) -> np.ndarray:
    """Return R-peak indices for a finite signal window."""
    fs = SAMPLING_FREQ

    # Feature: derivative → square → moving-window integrate
    deriv    = np.diff(signal, prepend=signal[0])
    sq       = deriv ** 2
    win      = max(1, int(0.15 * fs))
    integral = np.convolve(sq, np.ones(win) / win, mode="same")

    init_len     = min(len(integral), int(2 * fs))
    init_block   = integral[:init_len]
    sig_lev      = 0.25 * np.max(init_block)  if len(init_block) > 0 else 0.0
    noise_lev    = 0.50 * np.mean(init_block) if len(init_block) > 0 else 0.0
    thr1         = noise_lev + 0.25 * (sig_lev - noise_lev)
    cool_down    = int(0.20 * fs)

    all_peaks = np.where(
        (integral[1:-1] > integral[:-2]) & (integral[1:-1] >= integral[2:])
    )[0] + 1
    all_peaks = all_peaks.astype(int)

    actual   = []
    rr_hist  = []
    last_p   = -np.inf

    for idx in all_peaks:
        val = integral[idx]
        if val >= thr1:
            if idx - last_p < cool_down:
                noise_lev = 0.125 * val + 0.875 * noise_lev
            else:
                actual.append(idx)
                if last_p != -np.inf:
                    rr = idx - last_p
                    rr_hist.append(rr)
                    if len(rr_hist) > ROLLING_RR_WIN:
                        rr_hist.pop(0)
                last_p    = idx
                sig_lev   = 0.125 * val + 0.875 * sig_lev
        else:
            noise_lev = 0.125 * val + 0.875 * noise_lev
        thr1 = noise_lev + 0.25 * (sig_lev - noise_lev)

    # Search-back for missed beats
    if len(actual) >= 2 and rr_hist:
        avg_rr  = np.mean(rr_hist)
        thr2    = 0.5 * thr1
        extras  = []
        for i in range(1, len(actual)):
            gap = actual[i] - actual[i - 1]
            if gap > 1.66 * avg_rr:
                cands = all_peaks[(all_peaks > actual[i-1]) & (all_peaks < actual[i])]
                best_p, best_v = None, -np.inf
                for c in cands:
                    if integral[c] > thr2 and integral[c] > best_v:
                        best_v, best_p = integral[c], c
                if best_p is not None:
                    extras.append(best_p)
        actual.extend(extras)
        actual = sorted(set(actual))

    # Refine to true signal maxima
    r_peaks  = []
    sr       = int(0.08 * fs)
    for p in actual:
        s = max(0, p - sr)
        e = min(len(signal), p + sr + 1)
        local = signal[s:e]
        if len(local) == 0:
            continue
        rp = s + int(np.argmax(local))
        if not r_peaks or (rp - r_peaks[-1] >= cool_down):
            r_peaks.append(rp)

    return np.asarray(r_peaks, dtype=int)


# ===========================================================
# Risk score (0-100)   — prototype metric, not clinical
# ===========================================================
def _risk_score(avg_bpm: float,
                abnormal_ratio: float,
                sdnn_ms: float) -> tuple[int, str]:
    if   avg_bpm < 40  or avg_bpm > 150: bpm_s = 40
    elif avg_bpm < 50  or avg_bpm > 120: bpm_s = 25
    elif avg_bpm < 60  or avg_bpm > 100: bpm_s = 10
    else:                                bpm_s =  0

    abn_s = min(40, int(abnormal_ratio * 40 / 0.30))   # 30% abnormal → 40 pts

    if   sdnn_ms < 20: hrv_s = 20
    elif sdnn_ms < 50: hrv_s = 10
    else:              hrv_s =  0

    total = int(min(100, bpm_s + abn_s + hrv_s))

    if   total >= 70: label = "Critical"
    elif total >= 45: label = "High"
    elif total >= 20: label = "Moderate"
    else:             label = "Low"

    return total, label


# ===========================================================
# Per-patient stateful processor
# ===========================================================
class _PatientProcessor:
    """
    Holds per-patient streaming state so the filter zi is continuous
    and beat deduplication works correctly across windows.
    """
    def __init__(self):
        self._filt              = _StreamingFilter()
        self._global_idx        = 0          # total samples processed
        self._last_rpeak_global = -1         # dedup fence
        self._all_class_names:  list[str] = []
        self._all_bpms:         list[float] = []
        self._rr_buf:           deque[int]  = deque(maxlen=ROLLING_RR_WIN)

    def reset(self):
        self._filt.reset()
        self._global_idx        = 0
        self._last_rpeak_global = -1
        self._all_class_names.clear()
        self._all_bpms.clear()
        self._rr_buf.clear()

    # ── Window processing ──────────────────────────────────
    def process_window(
        self,
        window_mv: np.ndarray,
        model,
    ) -> Optional[dict]:
        """
        Process one WINDOW_SAMPLES-length mV array through the full pipeline.

        Returns an enriched result dict or None if nothing new was detected.
        """
        if len(window_mv) < WINDOW_SAMPLES:
            return None

        # 1. Stream-filter the new chunk only (avoid re-filtering old data)
        filtered = self._filt.filter(window_mv.copy())

        # 2. R-peak detection on the filtered window
        local_peaks = _detect_r_peaks(filtered)
        if len(local_peaks) == 0:
            return None

        window_offset = self._global_idx
        global_peaks  = local_peaks + window_offset

        # 3. Deduplicate
        new_peaks = [gp for gp in global_peaks if gp > self._last_rpeak_global]
        if not new_peaks:
            return None

        # 4. BPM from RR intervals (physiological gate)
        fence = self._last_rpeak_global
        prev  = fence if fence >= 0 else new_peaks[0]
        for gp in new_peaks:
            rr = int(gp - prev)
            if RR_MIN_SAMPLES <= rr <= RR_MAX_SAMPLES:
                self._rr_buf.append(rr)
                bpm = (60 * SAMPLING_FREQ) / rr
                self._all_bpms.append(bpm)
            prev = gp

        # 5. Beat extraction + XGBoost on new peaks
        beat_classes: list[str]  = []
        beat_confidences: list[float] = []

        for gp in new_peaks:
            # Map global index → window-local index
            local_gp = int(gp - window_offset)
            start    = local_gp - WINDOW_B4_PEAK
            end      = local_gp + WINDOW_AF_PEAK

            if start < 0 or end > len(filtered):
                continue

            beat = filtered[start:end]
            if len(beat) != BEAT_LENGTH:
                continue

            mean = float(np.mean(beat))
            std  = float(np.std(beat))
            norm = (beat - mean) / std if std != 0 else beat - mean

            X = norm.astype(np.float32).reshape(1, -1)
            try:
                pred  = int(model.predict(X)[0])
                proba = model.predict_proba(X)[0]
                cls   = CLASS_NAMES.get(pred, "N")
                conf  = float(np.max(proba)) * 100.0
                beat_classes.append(cls)
                beat_confidences.append(conf)
                self._all_class_names.append(cls)
            except Exception as exc:
                logger.debug("XGBoost inference error: %s", exc)
                continue

        self._last_rpeak_global = max(new_peaks)
        self._global_idx       += len(window_mv)   # advance the global index counter

        if not beat_classes:
            return None

        # 6. Majority vote across beats in this window
        from collections import Counter
        counts    = Counter(beat_classes)
        majority  = counts.most_common(1)[0][0]

        # Confidence = mean proba of beats that matched majority
        maj_confs = [c for cls, c in zip(beat_classes, beat_confidences) if cls == majority]
        confidence = round(float(np.mean(maj_confs)), 2) if maj_confs else 0.0

        # 7. BPM metrics
        rr_arr_s = np.array(list(self._rr_buf), dtype=float)
        if len(rr_arr_s) > 0:
            rr_ms    = (rr_arr_s / SAMPLING_FREQ) * 1000.0
            avg_bpm  = float(60_000.0 / np.mean(rr_ms))
            min_bpm  = float(min(self._all_bpms[-30:])) if self._all_bpms else avg_bpm
            max_bpm  = float(max(self._all_bpms[-30:])) if self._all_bpms else avg_bpm
            sdnn_ms  = float(np.std(rr_ms, ddof=1)) if len(rr_ms) > 1 else 0.0
            diffs    = np.diff(rr_ms)
            rmssd_ms = float(np.sqrt(np.mean(diffs ** 2))) if len(diffs) > 0 else 0.0
        else:
            avg_bpm = min_bpm = max_bpm = 0.0
            sdnn_ms = rmssd_ms = 0.0
            rr_ms   = np.array([])

        # 8. Abnormal ratio (all-time, rolling)
        total_beats   = len(self._all_class_names)
        abnormal      = sum(1 for c in self._all_class_names if c != "N")
        abn_ratio     = abnormal / total_beats if total_beats > 0 else 0.0

        # 9. Composite risk score 0-100
        risk_score, risk_label = _risk_score(avg_bpm or 75.0, abn_ratio, sdnn_ms)

        return {
            # Beat-level
            "majority_label":   majority,
            "beat_type":        _LABEL_DISPLAY.get(majority, majority),
            "confidence":       confidence,
            # BPM
            "xgb_bpm":          round(avg_bpm, 1),
            "min_bpm":          round(min_bpm, 1),
            "max_bpm":          round(max_bpm, 1),
            # HRV
            "sdnn_ms":          round(sdnn_ms,  2),
            "rmssd_ms":         round(rmssd_ms, 2),
            # Abnormal
            "abnormal_ratio":   round(abn_ratio, 4),
            "abnormal_pct":     round(abn_ratio * 100, 1),
            # Risk
            "risk_score":       risk_score,
            "risk_label":       risk_label,
            "risk_level":       _LABEL_TO_RISK.get(majority, "Moderate"),
            # Kept for RiskCard backward-compat
            "risk_percentage":  confidence,
        }


# ===========================================================
# PredictionService — singleton
# ===========================================================
class PredictionService:
    """
    Generates per-patient cardiac risk predictions from live ECG data
    every WINDOW_STEP_S seconds (2 s by default).

    Call `maybe_predict(patient_id, raw_buffer, fs)` from the analysis loop.
    """

    def __init__(self) -> None:
        self._model:     Optional[object]          = None
        self._available: bool                      = False
        self._processors: dict[str, _PatientProcessor] = {}
        self._last_run:   dict[str, datetime]      = {}
        self._load_model()

    def _load_model(self) -> None:
        if not _XGBOOST_AVAILABLE:
            logger.warning("xgboost not installed — risk prediction disabled.")
            return
        try:
            m = _XGBClassifier()
            m.load_model(MODEL_PATH)
            self._model     = m
            self._available = True
            logger.info("M2 XGBoost model loaded from %s", MODEL_PATH)
        except Exception as exc:
            logger.warning("Could not load XGBoost model (%s): %s — disabled.", MODEL_PATH, exc)

    def _processor(self, patient_id: str) -> _PatientProcessor:
        if patient_id not in self._processors:
            self._processors[patient_id] = _PatientProcessor()
        return self._processors[patient_id]

    def reset_patient(self, patient_id: str) -> None:
        """Call this when the patient session is switched."""
        if patient_id in self._processors:
            self._processors[patient_id].reset()
        self._last_run.pop(patient_id, None)

    # ── Public API ─────────────────────────────────────────

    async def maybe_predict(
        self,
        patient_id:  str,
        raw_buffer:  deque,
    ) -> Optional[dict]:
        """
        Run one prediction window if WINDOW_STEP_S seconds have elapsed
        and WINDOW_SAMPLES samples are available.

        The sampling frequency is always SAMPLING_FREQ (192 Hz) — the fs
        parameter has been removed to prevent callers from accidentally
        passing a different value and silently producing wrong BPMs.

        Returns enriched dict or None.
        """
        if not self._available:
            return None

        now  = datetime.now(timezone.utc)
        last = self._last_run.get(patient_id)
        if last and (now - last) < timedelta(seconds=WINDOW_STEP_S):
            return None

        buf_list = list(raw_buffer)
        if len(buf_list) < WINDOW_SAMPLES:
            return None

        # Take last WINDOW_SAMPLES, convert ADC → mV
        raw_window = np.array(buf_list[-WINDOW_SAMPLES:], dtype=np.float64)
        mv_window  = np.vectorize(adc_to_mv)(raw_window)

        proc   = self._processor(patient_id)
        model  = self._model

        result = await asyncio.get_event_loop().run_in_executor(
            None, proc.process_window, mv_window, model
        )

        if result is None:
            return None

        self._last_run[patient_id] = now

        await self._persist(
            patient_id      = patient_id,
            risk_percentage = result["confidence"],
            risk_level      = result["risk_level"],
            majority_label  = result["majority_label"],
        )

        logger.info(
            "XGBoost prediction  patient=%s  label=%s (%s)  "
            "conf=%.1f%%  bpm=%.1f  risk=%d/100 [%s]  sdnn=%.1fms",
            patient_id,
            result["majority_label"], result["beat_type"],
            result["confidence"],
            result["xgb_bpm"],
            result["risk_score"], result["risk_label"],
            result["sdnn_ms"],
        )

        return result

    # ── Persistence ────────────────────────────────────────

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
                    patient_id      = patient_id,
                    risk_percentage = risk_percentage,
                    risk_level      = risk_level,
                    majority_label  = majority_label,
                )
                await db.commit()
        except Exception as exc:
            logger.error("Failed to persist risk prediction: %s", exc)

    @property
    def available(self) -> bool:
        return self._available


# ── Singleton ─────────────────────────────────────────────
prediction_service = PredictionService()
