"""
PreprocessClassifyLog.py
========================
Real-time ECG monitor for ESP32-over-Wi-Fi + XGBoost classification.

Supports two modes
------------------
  Mode 1 – CSV  : PredictFromCSV(path)        → offline / testing
  Mode 2 – Live : RunRealtime()                → ESP32 WebSocket stream

Architecture
------------
  WebSocketReceiver
      ↓  asyncio.Queue
  ECGBuffer  (rolling mV samples)
      ↓
  RealtimeECGProcessor
      ├── StreamingButterworthFilter  (sosfilt + persistent zi)
      ├── PanTompkinsDetector
      ├── BPMCalculator
      ├── BeatExtractor
      ├── XGBoostClassifier          (predict_proba)
      └── RiskAnalyzer
      ↓
  ECGLogger   (4 CSV files)
      ↓
  RealtimeDisplay (console + matplotlib live plot)

NOTE: The risk score (0–100) is a prototype/project metric.
      It is NOT a clinically validated medical diagnostic score.
"""

# ============================================================
# Imports
# ============================================================
import os
import csv
import sys
import time
import asyncio
import threading
import logging
from collections import deque
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("TkAgg")          # change to "Qt5Agg" if TkAgg unavailable
import matplotlib.pyplot as plt
import matplotlib.animation as animation

from scipy.signal import butter, sosfilt, sosfilt_zi, filtfilt
from xgboost import XGBClassifier

try:
    import websockets
    _HAS_WEBSOCKETS = True
except ImportError:
    _HAS_WEBSOCKETS = False

# ============================================================
# ███  CONFIGURATION  ███
# All tuneable constants live here — do NOT duplicate them.
# ============================================================

# --- Hardware / ADC -----------------------------------------
SAMPLING_FREQ  = 192          # Hz  (ESP32 actual sampling rate)
ADC_BASELINE   = 343          # raw ADC counts at 0 mV baseline
ADC_TO_MV      = 0.00806      # mV per ADC count (prototype calibration)
ADC_MIN        = 0            # valid ADC range low
ADC_MAX        = 4095         # valid ADC range high

# --- Network ------------------------------------------------
WEBSOCKET_HOST = "10.107.233.122"
WEBSOCKET_PORT = 8000
WEBSOCKET_PATH = "/ws/device"
WS_RECONNECT_DELAY_S = 3      # seconds between reconnect attempts

# --- Processing window --------------------------------------
WINDOW_SECONDS   = 10         # seconds of ECG per analysis window
WINDOW_STEP_S    = 2          # seconds to advance window each cycle
WINDOW_SAMPLES   = SAMPLING_FREQ * WINDOW_SECONDS   # 1920
WINDOW_STEP      = SAMPLING_FREQ * WINDOW_STEP_S    # 384

# --- Butterworth bandpass -----------------------------------
LOW_CUTOFF_HZ  = 0.5
HIGH_CUTOFF_HZ = 45.0
FILTER_ORDER   = 2

# --- Beat extraction ----------------------------------------
WINDOW_B4_PEAK  = 90          # samples before R-peak
WINDOW_AF_PEAK  = 100         # samples after  R-peak
BEAT_LENGTH     = WINDOW_B4_PEAK + WINDOW_AF_PEAK   # 190

# --- BPM physiological gates --------------------------------
BPM_MIN_VALID  = 30           # reject RR implying BPM < 30
BPM_MAX_VALID  = 220          # reject RR implying BPM > 220
RR_MIN_SAMPLES = int((60 / BPM_MAX_VALID) * SAMPLING_FREQ)   # ~52
RR_MAX_SAMPLES = int((60 / BPM_MIN_VALID)  * SAMPLING_FREQ)  # ~384
MIN_RPEAKS_FOR_BPM = 2        # need at least 2 peaks for one RR interval
ROLLING_RR_WINDOW  = 8        # number of recent RR intervals for stable BPM

# --- Display / plot -----------------------------------------
PLOT_WINDOW_S   = 7           # seconds shown in live waveform
PLOT_WINDOW_N   = SAMPLING_FREQ * PLOT_WINDOW_S
DISPLAY_INTERVAL_S = 2.0      # minimum seconds between console prints

# --- Model --------------------------------------------------
MODEL_PATH = "M2/saved_models/ecg_xgboost.json"

# --- AAMI class map -----------------------------------------
CLASS_NAMES = {0: "N", 1: "S", 2: "V", 3: "F", 4: "Q"}

# ============================================================
# Logging setup (Python logger → file, not the ECG CSV logs)
# ============================================================
os.makedirs("logs", exist_ok=True)
_pylog = logging.getLogger("ecg_monitor")
_pylog.setLevel(logging.DEBUG)
_fh = logging.FileHandler("logs/ecg_monitor.log", encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
_pylog.addHandler(_fh)


# ============================================================
# ADC → mV conversion
# ============================================================
def adc_to_mv(adc_value: float) -> float:
    """
    Convert raw ESP32 ADC integer to ECG millivolts.

    Formula : ECG_mV = (ADC - ADC_BASELINE) * ADC_TO_MV
    Example : adc_to_mv(343) → 0.000 mV
              adc_to_mv(476) → +1.072 mV
              adc_to_mv(210) → -1.072 mV
    """
    return (adc_value - ADC_BASELINE) * ADC_TO_MV


# ============================================================
# StreamingButterworthFilter
# ============================================================
class StreamingButterworthFilter:
    """
    Butterworth bandpass filter suitable for infinite streaming data.

    Uses scipy.signal.sosfilt() with persistent filter state (zi)
    so each new chunk continues seamlessly from where the last left off.
    filtfilt() is NOT used here because it requires future samples.
    """

    def __init__(self,
                 low_hz: float  = LOW_CUTOFF_HZ,
                 high_hz: float = HIGH_CUTOFF_HZ,
                 order: int     = FILTER_ORDER,
                 fs: int        = SAMPLING_FREQ):
        nyq = fs / 2.0
        self.sos = butter(order, [low_hz / nyq, high_hz / nyq],
                          btype="band", output="sos")
        self.zi  = sosfilt_zi(self.sos)   # shape (n_sections, 2)
        self._ready = False               # True once ≥1 chunk filtered

    def filter_chunk(self, chunk: np.ndarray) -> np.ndarray:
        """Filter an ndarray chunk; zi is updated in-place between calls."""
        if len(chunk) == 0:
            return chunk
        filtered, self.zi = sosfilt(self.sos, chunk, zi=self.zi)
        self._ready = True
        return filtered

    def reset(self):
        """Reset filter state (call if the stream restarts)."""
        self.zi = sosfilt_zi(self.sos)
        self._ready = False

    # ----------------------------------------------------------
    # Offline convenience: zero-phase filtfilt (CSV mode only)
    # ----------------------------------------------------------
    def filter_offline(self, signal: np.ndarray) -> np.ndarray:
        """
        Zero-phase Butterworth filter for offline/CSV data.
        Uses filtfilt — do NOT use this on an infinite stream.
        """
        nyq = SAMPLING_FREQ / 2.0
        b, a = butter(FILTER_ORDER,
                      [LOW_CUTOFF_HZ / nyq, HIGH_CUTOFF_HZ / nyq],
                      btype="band")
        return filtfilt(b, a, signal)


# ============================================================
# PanTompkinsDetector
# ============================================================
class PanTompkinsDetector:
    """
    Pan-Tompkins R-peak detector.

    Supports both:
      • windowed_detect(signal)  — for a finite buffer window
      • The existing stateful logic is retained inside the window call.

    For streaming use, the caller passes a fresh WINDOW_SAMPLES-length
    chunk each time and tracks 'last_global_rpeak' externally to avoid
    duplicate detections across overlapping windows.
    """

    def __init__(self, fs: int = SAMPLING_FREQ):
        self.fs = fs

    def _feature(self, signal: np.ndarray) -> np.ndarray:
        """Pan-Tompkins feature: derivative → square → moving-window integrate."""
        derivative        = np.diff(signal, prepend=signal[0])
        squared           = derivative ** 2
        win               = max(1, int(0.15 * self.fs))
        kernel            = np.ones(win) / win
        return np.convolve(squared, kernel, mode="same")

    def windowed_detect(self, signal: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """
        Detect R-peaks in a finite signal window.

        Returns
        -------
        r_peaks  : np.ndarray  (sample indices into `signal`)
        integral : np.ndarray  (Pan-Tompkins integrated signal, same length)
        """
        integral = self._feature(signal)

        init_len      = min(len(integral), int(2 * self.fs))
        init_block    = integral[:init_len]
        signal_level  = 0.25 * np.max(init_block)  if len(init_block) > 0 else 0.0
        noise_level   = 0.50 * np.mean(init_block) if len(init_block) > 0 else 0.0
        threshold1    = noise_level + 0.25 * (signal_level - noise_level)
        threshold2    = 0.50 * threshold1
        cool_down     = int(0.20 * self.fs)

        # Find all local maxima
        all_peaks = np.where(
            (integral[1:-1] > integral[:-2]) & (integral[1:-1] >= integral[2:])
        )[0] + 1
        all_peaks = all_peaks.astype(int)

        actual_peaks = []
        rr_history   = []
        last_peak    = -np.inf

        for idx in all_peaks:
            val = integral[idx]
            if val >= threshold1:
                if idx - last_peak < cool_down:
                    noise_level   = 0.125 * val + 0.875 * noise_level
                    threshold1    = noise_level + 0.25 * (signal_level - noise_level)
                    threshold2    = 0.50 * threshold1
                    continue
                actual_peaks.append(idx)
                if last_peak != -np.inf:
                    rr = idx - last_peak
                    rr_history.append(rr)
                    if len(rr_history) > ROLLING_RR_WINDOW:
                        rr_history.pop(0)
                last_peak     = idx
                signal_level  = 0.125 * val + 0.875 * signal_level
            else:
                noise_level   = 0.125 * val + 0.875 * noise_level

            threshold1 = noise_level + 0.25 * (signal_level - noise_level)
            threshold2 = 0.50 * threshold1

        # Search-back for missed beats in long gaps
        search_back = []
        if len(actual_peaks) >= 2:
            avg_rr = np.mean(rr_history) if rr_history else 0
            for i in range(1, len(actual_peaks)):
                prev_p = actual_peaks[i - 1]
                curr_p = actual_peaks[i]
                if avg_rr > 0 and (curr_p - prev_p) > 1.66 * avg_rr:
                    cands  = all_peaks[(all_peaks > prev_p) & (all_peaks < curr_p)]
                    best_p = None
                    best_v = -np.inf
                    for c in cands:
                        cv = integral[c]
                        if cv > threshold2 and cv > best_v:
                            best_v = cv
                            best_p = c
                    if best_p is not None:
                        search_back.append(best_p)

        actual_peaks.extend(search_back)
        actual_peaks = sorted(set(actual_peaks))

        # Refine to true signal maxima
        r_peaks   = []
        search_r  = int(0.08 * self.fs)
        for p in actual_peaks:
            s = max(0, p - search_r)
            e = min(len(signal), p + search_r + 1)
            local = signal[s:e]
            if len(local) == 0:
                continue
            rp = s + int(np.argmax(local))
            if not r_peaks or (rp - r_peaks[-1] >= cool_down):
                r_peaks.append(rp)

        return np.asarray(r_peaks, dtype=int), integral


# ============================================================
# BPMCalculator
# ============================================================
class BPMCalculator:
    """
    Maintains a rolling window of valid RR intervals and computes
    stable BPM, SDNN, and RMSSD.

    Only RR intervals that correspond to physiologically plausible
    BPMs (BPM_MIN_VALID – BPM_MAX_VALID) are accepted.
    """

    def __init__(self, fs: int = SAMPLING_FREQ):
        self.fs       = fs
        self._rr_buf  = deque(maxlen=ROLLING_RR_WINDOW)  # recent valid RR (samples)

    def add_rr(self, rr_samples: int) -> float | None:
        """
        Accept one RR interval (in samples).  Returns BPM if valid, else None.

        BPM = (60 * SAMPLING_FREQ) / rr_samples
        """
        if rr_samples < RR_MIN_SAMPLES or rr_samples > RR_MAX_SAMPLES:
            return None
        bpm = (60 * self.fs) / rr_samples
        self._rr_buf.append(rr_samples)
        return bpm

    @property
    def rolling_bpm(self) -> float | None:
        """Mean BPM over the recent RR window. None if insufficient data."""
        if len(self._rr_buf) < MIN_RPEAKS_FOR_BPM:
            return None
        rr_arr = np.asarray(self._rr_buf, dtype=float)
        rr_ms  = (rr_arr / self.fs) * 1000.0
        return float(60_000.0 / np.mean(rr_ms))

    @property
    def rr_intervals_ms(self) -> list[float]:
        rr_arr = np.asarray(self._rr_buf, dtype=float)
        return ((rr_arr / self.fs) * 1000.0).tolist()

    @property
    def sdnn_ms(self) -> float:
        rr_ms = self.rr_intervals_ms
        return float(np.std(rr_ms, ddof=1)) if len(rr_ms) > 1 else 0.0

    @property
    def rmssd_ms(self) -> float:
        rr_ms = self.rr_intervals_ms
        if len(rr_ms) < 2:
            return 0.0
        diffs = np.diff(rr_ms)
        return float(np.sqrt(np.mean(diffs ** 2)))

    def reset(self):
        self._rr_buf.clear()


# ============================================================
# RiskAnalyzer
# ============================================================
class RiskAnalyzer:
    """
    Computes a prototype risk score (0–100) from BPM, abnormal-beat
    ratio, and HRV (SDNN).

    Score breakdown:
        BPM deviation   : 0–40
        Abnormal beats  : 0–40
        HRV penalty     : 0–20
        Total           : 0–100

    Labels:
        0–19  → Low
        20–44 → Moderate
        45–69 → High
        70+   → Critical

    DISCLAIMER: This is a prototype/project metric, NOT a clinically
    validated diagnostic score.
    """

    @staticmethod
    def compute(avg_bpm: float,
                abnormal_ratio: float,
                sdnn_ms: float) -> tuple[int, str]:
        # BPM component
        if   avg_bpm < 40  or avg_bpm > 150: bpm_score = 40
        elif avg_bpm < 50  or avg_bpm > 120: bpm_score = 25
        elif avg_bpm < 60  or avg_bpm > 100: bpm_score = 10
        else:                                bpm_score =  0

        # Abnormal-beat component  (30% abnormal → max 40 pts)
        abn_score = min(40, int(abnormal_ratio * 40 / 0.30))

        # HRV component
        if   sdnn_ms < 20: hrv_score = 20
        elif sdnn_ms < 50: hrv_score = 10
        else:              hrv_score =  0

        total = int(min(100, bpm_score + abn_score + hrv_score))

        if   total >= 70: label = "Critical"
        elif total >= 45: label = "High"
        elif total >= 20: label = "Moderate"
        else:             label = "Low"

        return total, label


# ============================================================
# ECGLogger  –  4 CSV log files
# ============================================================
class ECGLogger:
    """
    Manages 4 real-time CSV log files.

    realtime_ecg.csv  : Timestamp, ADC_Value, ECG_mV
    r_peaks.csv       : Timestamp, RPeakIndex, RR_Samples, RR_ms, BPM
    predictions.csv   : Timestamp, BeatIndex, RPeakIndex, ClassID, Class, Confidence
    insights.csv      : Timestamp, BPM, MinBPM, MaxBPM, SDNN, RMSSD,
                        AbnormalRatio, RiskScore, RiskLabel
    """

    def __init__(self, log_dir: str = "logs"):
        os.makedirs(log_dir, exist_ok=True)

        self._ecg_path   = os.path.join(log_dir, "realtime_ecg.csv")
        self._rp_path    = os.path.join(log_dir, "r_peaks.csv")
        self._pred_path  = os.path.join(log_dir, "predictions.csv")
        self._ins_path   = os.path.join(log_dir, "insights.csv")

        # Also keep the legacy logs for CSV mode
        self._filter_path  = os.path.join(log_dir, "butterworth_filter_log.csv")
        self._pt_path      = os.path.join(log_dir, "pan_tompkins_log.csv")
        self._extract_path = os.path.join(log_dir, "beat_extraction_log.csv")
        self._xgb_path     = os.path.join(log_dir, "xgboost_predictions_log.csv")

        self._init_headers()

    def _init_headers(self):
        headers = {
            self._ecg_path   : ["Timestamp", "ADC_Value", "ECG_mV"],
            self._rp_path    : ["Timestamp", "RPeakIndex", "RR_Samples", "RR_ms", "BPM"],
            self._pred_path  : ["Timestamp", "BeatIndex", "RPeakIndex", "ClassID", "Class", "Confidence"],
            self._ins_path   : ["Timestamp", "BPM", "MinBPM", "MaxBPM", "SDNN", "RMSSD",
                                "AbnormalRatio", "RiskScore", "RiskLabel"],
            # Legacy
            self._filter_path  : ["Timestamp", "InputSamples", "OutputSamples",
                                  "LowerBound_Hz", "UpperBound_Hz", "Order"],
            self._pt_path      : ["Timestamp", "InitialSignalLevel", "NoiseLevel",
                                  "Threshold1", "Threshold2", "TotalCandidatePeaks", "RPeaksDetected"],
            self._extract_path : ["Timestamp", "BeatIndex", "RPeakIndex", "Mean", "Std", "Status"],
            self._xgb_path     : ["Timestamp", "BeatIndex", "RPeakIndex", "ClassID", "Class", "Confidence"],
        }
        for path, cols in headers.items():
            with open(path, mode="w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(cols)

    def _append(self, path: str, row: list):
        with open(path, mode="a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(row)

    def log_sample(self, adc: int, mv: float):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        self._append(self._ecg_path, [ts, adc, f"{mv:.5f}"])

    def log_rpeak(self, rpeak_idx: int, rr_samples: int | None,
                  rr_ms: float | None, bpm: float | None):
        ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        rrs = "" if rr_samples is None else rr_samples
        rrm = "" if rr_ms      is None else f"{rr_ms:.2f}"
        bv  = "" if bpm        is None else f"{bpm:.2f}"
        self._append(self._rp_path, [ts, rpeak_idx, rrs, rrm, bv])

    def log_prediction(self, beat_idx: int, rpeak_idx: int,
                       class_id: int, class_name: str, confidence: float):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        self._append(self._pred_path,
                     [ts, beat_idx, rpeak_idx, class_id, class_name,
                      f"{confidence:.4f}"])
        # also write to legacy log
        self._append(self._xgb_path,
                     [ts, beat_idx, rpeak_idx, class_id, class_name,
                      f"{confidence:.4f}"])

    def log_insights(self, bpm: float, min_bpm: float, max_bpm: float,
                     sdnn: float, rmssd: float, abn_ratio: float,
                     risk_score: int, risk_label: str):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        self._append(self._ins_path,
                     [ts, f"{bpm:.2f}", f"{min_bpm:.2f}", f"{max_bpm:.2f}",
                      f"{sdnn:.2f}", f"{rmssd:.2f}",
                      f"{abn_ratio:.4f}", risk_score, risk_label])

    # --- Legacy helpers used by ECGPreprocessor (CSV mode) ---------------
    def log_filter(self, n_in: int, n_out: int):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._append(self._filter_path,
                     [ts, n_in, n_out, LOW_CUTOFF_HZ, HIGH_CUTOFF_HZ, FILTER_ORDER])

    def log_pt(self, sig_lev, noise_lev, thr1, thr2, n_cands, n_rpeaks):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._append(self._pt_path,
                     [ts, round(sig_lev, 4), round(noise_lev, 4),
                      round(thr1, 4), round(thr2, 4), n_cands, n_rpeaks])

    def log_beat(self, beat_idx: int, rpeak_idx: int,
                 mean: float, std: float, status: str):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._append(self._extract_path,
                     [ts, beat_idx, rpeak_idx, round(mean, 4), round(std, 4), status])


# ============================================================
# RealtimeDisplay
# ============================================================
class RealtimeDisplay:
    """
    Console summary + live matplotlib waveform (runs in main thread).

    The waveform plot uses FuncAnimation so the window stays responsive
    without blocking WebSocket reception (which runs in a background thread).
    """

    def __init__(self):
        # Rolling buffer for plot (mV values only)
        self._plot_buf: deque[float] = deque(maxlen=PLOT_WINDOW_N)
        self._last_print = 0.0

        # Build figure once
        self._fig, self._ax = plt.subplots(figsize=(12, 3))
        self._fig.patch.set_facecolor("#111")
        self._ax.set_facecolor("#111")
        self._ax.set_title("Real-Time ECG Waveform", color="lime", fontsize=11)
        self._ax.set_xlabel("Time (s)", color="white")
        self._ax.set_ylabel("ECG (mV)", color="white")
        self._ax.tick_params(colors="white")
        for spine in self._ax.spines.values():
            spine.set_edgecolor("#444")
        self._line, = self._ax.plot([], [], color="lime", linewidth=0.8)
        self._ax.set_xlim(0, PLOT_WINDOW_S)
        self._ax.set_ylim(-2.0, 2.0)
        self._ax.grid(True, color="#333")
        plt.tight_layout()

        # Latest insight snapshot (updated from processing thread)
        self._snapshot: dict = {}
        self._snap_lock = threading.Lock()

    def push_sample(self, mv: float):
        """Called from processing thread — thread-safe append."""
        self._plot_buf.append(mv)

    def update_snapshot(self, snap: dict):
        """Called from processing thread with latest insights."""
        with self._snap_lock:
            self._snapshot = snap.copy()

    def _animate(self, _frame):
        """FuncAnimation callback — runs in the main thread."""
        buf = list(self._plot_buf)
        n   = len(buf)
        if n == 0:
            return (self._line,)
        t = np.arange(n) / SAMPLING_FREQ
        self._line.set_data(t, buf)
        # Keep x-axis anchored to a PLOT_WINDOW_S-wide view
        if t[-1] > PLOT_WINDOW_S:
            self._ax.set_xlim(t[-1] - PLOT_WINDOW_S, t[-1])
        else:
            self._ax.set_xlim(0, PLOT_WINDOW_S)
        return (self._line,)

    def start_animation(self):
        """Start FuncAnimation — must be called from main thread."""
        self._anim = animation.FuncAnimation(
            self._fig, self._animate,
            interval=50,        # ~20 fps
            blit=True, cache_frame_data=False
        )
        plt.ion()
        plt.show(block=False)

    def print_status(self, force: bool = False):
        """Print console dashboard (rate-limited to DISPLAY_INTERVAL_S)."""
        now = time.time()
        if not force and (now - self._last_print) < DISPLAY_INTERVAL_S:
            return
        self._last_print = now
        with self._snap_lock:
            s = self._snapshot.copy()
        if not s:
            return
        W = 52
        print("\n" + "=" * W)
        print("  REAL-TIME ECG MONITOR")
        print("=" * W)
        print(f"  Sampling Frequency : {SAMPLING_FREQ} Hz")
        print(f"  ADC                : {s.get('adc', '--')}")
        print(f"  ECG                : {s.get('ecg_mv', '--')} mV")
        print("-" * W)
        bpm  = s.get("bpm")
        rr   = s.get("rr_ms")
        print(f"  Heart Rate         : {f'{bpm:.1f} BPM'    if bpm  else 'Calculating...'}")
        print(f"  RR Interval        : {f'{rr:.1f} ms'      if rr   else '--'}")
        print("-" * W)
        beat = s.get("beat_index", "--")
        cls  = s.get("class_name", "--")
        conf = s.get("confidence")
        print(f"  Current Beat       : {beat}")
        print(f"  Classification     : {cls}")
        print(f"  Confidence         : {f'{conf:.2f}%' if conf else '--'}")
        print("-" * W)
        rs   = s.get("risk_score")
        rl   = s.get("risk_label", "--")
        sdnn = s.get("sdnn_ms")
        rmd  = s.get("rmssd_ms")
        abn  = s.get("abnormal_ratio")
        print(f"  Risk Score         : {f'{rs} / 100'       if rs is not None else '--'}")
        print(f"  Risk Level         : {rl}")
        print("-" * W)
        print(f"  HRV - SDNN         : {f'{sdnn:.2f} ms'    if sdnn else '--'}")
        print(f"  HRV - RMSSD        : {f'{rmd:.2f} ms'     if rmd  else '--'}")
        print(f"  Abnormal Beats     : {f'{abn*100:.1f}%'   if abn is not None else '--'}")
        print("=" * W)


# ============================================================
# ECGPreprocessor  –  shared pipeline (CSV + realtime)
# ============================================================
class ECGPreprocessor:
    """
    Core ECG processing pipeline shared by both modes.

    Exposes:
        PredictFromCSV(path)   – Mode 1: offline CSV testing
        Predict(signal)        – internal: process a numpy signal array
        PlotProcessing(...)    – static multi-panel diagnostic plot
    """

    def __init__(self):
        self.SamplingFreq   = SAMPLING_FREQ
        self.WindowB4Peak   = WINDOW_B4_PEAK
        self.WindowAfPeak   = WINDOW_AF_PEAK
        self.LowerBound     = LOW_CUTOFF_HZ
        self.UpperBound     = HIGH_CUTOFF_HZ
        self.Order          = FILTER_ORDER

        self._detector  = PanTompkinsDetector(fs=SAMPLING_FREQ)
        self._filt      = StreamingButterworthFilter()
        self._logger    = ECGLogger()

        print("[INFO] Loading XGBoost model …")
        self.Model = XGBClassifier()
        self.Model.load_model(MODEL_PATH)
        print(f"[INFO] Model loaded from '{MODEL_PATH}'")

        self.ClassNames = CLASS_NAMES

    # ----------------------------------------------------------
    # Butterworth (offline, for CSV mode)
    # ----------------------------------------------------------
    def ButterWorthFilter(self, signal: np.ndarray) -> np.ndarray:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [1] Applying Butterworth bandpass filter (offline)…")
        filtered = self._filt.filter_offline(signal)
        self._logger.log_filter(len(signal), len(filtered))
        return filtered

    # ----------------------------------------------------------
    # Pan-Tompkins
    # ----------------------------------------------------------
    def PanTompkinsDetector(self, signal: np.ndarray):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [3] Detecting R-peaks…")
        r_peaks, integral = self._detector.windowed_detect(signal)
        # Log summary (approximate thresholds for legacy log)
        self._logger.log_pt(0, 0, 0, 0, 0, len(r_peaks))
        print(f"    R-peaks detected : {len(r_peaks)}")
        return r_peaks, integral

    # ----------------------------------------------------------
    # Beat extraction + normalization
    # ----------------------------------------------------------
    def ExtractBeats(self, signal: np.ndarray,
                     r_peaks: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [4] Extracting and normalizing ECG beats…")

        beats       = []
        valid_peaks = []

        for i, rp in enumerate(r_peaks):
            start = rp - self.WindowB4Peak
            end   = rp + self.WindowAfPeak

            if start < 0 or end > len(signal):
                self._logger.log_beat(i + 1, rp, 0.0, 0.0, "Skipped_OutOfBounds")
                continue

            beat = signal[start:end]
            if len(beat) != BEAT_LENGTH:
                self._logger.log_beat(i + 1, rp, 0.0, 0.0, "Skipped_InvalidLength")
                continue

            mean = float(np.mean(beat))
            std  = float(np.std(beat))
            norm = (beat - mean) / std if std != 0 else beat - mean

            beats.append(norm)
            valid_peaks.append(rp)
            self._logger.log_beat(len(beats), rp, mean, std, "Valid")

        X = np.asarray(beats, dtype=np.float32)
        print(f"    Valid beats      : {len(X)}")
        return X, np.asarray(valid_peaks, dtype=int)

    # ----------------------------------------------------------
    # XGBoost inference with confidence
    # ----------------------------------------------------------
    def _classify_beats(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Run XGBoost on extracted beats.

        Returns
        -------
        class_ids    : int array (0–4)
        class_names  : str array
        confidences  : float array (0–100 %)
        """
        predictions  = self.Model.predict(X).astype(np.int64)
        probabilities = self.Model.predict_proba(X)           # shape (n, 5)
        confidences  = np.max(probabilities, axis=1) * 100.0  # → %

        names = np.array([CLASS_NAMES[int(p)] for p in predictions])
        return predictions, names, confidences

    # ----------------------------------------------------------
    # ComputeInsights (preserved from original)
    # ----------------------------------------------------------
    def ComputeInsights(self,
                        r_peaks: np.ndarray,
                        class_predictions: list[str]) -> dict:
        rr_samples = np.diff(r_peaks)
        rr_ms      = (rr_samples / self.SamplingFreq) * 1000.0

        if len(rr_ms) == 0:
            return {"error": "Not enough R-peaks to compute insights."}

        # --- Filter physiologically impossible RR ---
        valid_mask = (rr_samples >= RR_MIN_SAMPLES) & (rr_samples <= RR_MAX_SAMPLES)
        rr_ms_valid = rr_ms[valid_mask]
        if len(rr_ms_valid) == 0:
            rr_ms_valid = rr_ms   # fall back to all if none pass

        bpms    = 60_000.0 / rr_ms_valid
        avg_bpm = float(np.mean(bpms))
        min_bpm = float(np.min(bpms))
        max_bpm = float(np.max(bpms))

        sdnn  = float(np.std(rr_ms_valid, ddof=1)) if len(rr_ms_valid) > 1 else 0.0
        diffs = np.diff(rr_ms_valid)
        rmssd = float(np.sqrt(np.mean(diffs ** 2))) if len(diffs) > 0 else 0.0

        beat_counts   = {n: 0 for n in CLASS_NAMES.values()}
        for c in class_predictions:
            beat_counts[c] = beat_counts.get(c, 0) + 1

        total_beats    = len(class_predictions)
        abnormal_beats = total_beats - beat_counts.get("N", 0)
        abnormal_ratio = abnormal_beats / total_beats if total_beats > 0 else 0.0

        risk_score, risk_label = RiskAnalyzer.compute(avg_bpm, abnormal_ratio, sdnn)

        # Plain-English interpretation
        lines = []
        if   avg_bpm < 60:  lines.append(f"Bradycardia detected (avg {avg_bpm:.1f} BPM).")
        elif avg_bpm > 100: lines.append(f"Tachycardia detected (avg {avg_bpm:.1f} BPM).")
        else:               lines.append(f"Heart rate is normal (avg {avg_bpm:.1f} BPM).")
        if beat_counts.get("V", 0) > 0:
            lines.append(f"{beat_counts['V']} Ventricular beat(s) — may indicate PVC.")
        if beat_counts.get("S", 0) > 0:
            lines.append(f"{beat_counts['S']} Supraventricular beat(s) detected.")
        if beat_counts.get("F", 0) > 0:
            lines.append(f"{beat_counts['F']} Fusion beat(s) detected.")
        if beat_counts.get("Q", 0) > 0:
            lines.append(f"{beat_counts['Q']} Unclassifiable beat(s) detected.")
        if sdnn < 20:   lines.append("Very low HRV (SDNN < 20 ms).")
        elif sdnn < 50: lines.append("Reduced HRV (SDNN < 50 ms) — monitor closely.")
        else:           lines.append("HRV within acceptable range.")

        return {
            "heart_rate_bpm"  : round(avg_bpm, 1),
            "min_bpm"         : round(min_bpm, 1),
            "max_bpm"         : round(max_bpm, 1),
            "rr_intervals_ms" : [round(r, 2) for r in rr_ms.tolist()],
            "sdnn_ms"         : round(sdnn,   2),
            "rmssd_ms"        : round(rmssd,  2),
            "beat_counts"     : beat_counts,
            "total_beats"     : total_beats,
            "abnormal_ratio"  : round(abnormal_ratio, 4),
            "risk_score"      : risk_score,
            "risk_label"      : risk_label,
            "interpretation"  : " ".join(lines),
        }

    # ----------------------------------------------------------
    # Predict – main entry for a numpy signal array
    # ----------------------------------------------------------
    def Predict(self, signal: np.ndarray) -> dict:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print("=" * 60)
        print(f"[{ts}] STARTING ECG XGBOOST PREDICTION PIPELINE")
        print("=" * 60)

        filtered = self.ButterWorthFilter(signal)
        r_peaks, integral = self.PanTompkinsDetector(filtered)
        X, valid_peaks = self.ExtractBeats(filtered, r_peaks)

        if X.shape[0] == 0:
            print("[WARNING] No valid ECG beats detected.")
            return {
                "predictions": np.empty(0, dtype=np.int64),
                "risk_levels": [],
                "r_peaks"    : valid_peaks,
            }

        print(f"[{ts}] [5] Running XGBoost model inference with confidence…")
        class_ids, class_names_arr, confidences = self._classify_beats(X)

        print(f"[{ts}] [6] Logging predictions:")
        for i in range(len(class_ids)):
            self._logger.log_prediction(
                i + 1, int(valid_peaks[i]),
                int(class_ids[i]), class_names_arr[i],
                float(confidences[i])
            )
            print(
                f"    Beat {i+1:3d} | R-peak = {valid_peaks[i]:6d} | "
                f"Class = {class_names_arr[i]} | "
                f"Confidence = {confidences[i]:.2f}%"
            )

        insights = self.ComputeInsights(valid_peaks, class_names_arr.tolist())
        self._print_insights(insights)

        return {
            "predictions"      : class_ids,
            "confidences"      : confidences,
            "risk_levels"      : class_names_arr.tolist(),
            "r_peaks"          : valid_peaks,
            "filtered_signal"  : filtered,
            "integrated_signal": integral,
            "beats"            : X,
            "insights"         : insights,
        }

    # ----------------------------------------------------------
    # Print insights (preserved from original)
    # ----------------------------------------------------------
    def _print_insights(self, insights: dict):
        W = 60
        print("=" * W)
        print("  ECG CLINICAL INSIGHTS SUMMARY")
        print("=" * W)
        print(f"  Heart Rate      : {insights['heart_rate_bpm']} BPM  "
              f"(min {insights['min_bpm']} / max {insights['max_bpm']})")
        print(f"  HRV — SDNN      : {insights['sdnn_ms']} ms")
        print(f"  HRV — RMSSD     : {insights['rmssd_ms']} ms")
        print(f"  Total Beats     : {insights['total_beats']}")
        print("  Beat Breakdown  :")
        for cls, cnt in insights["beat_counts"].items():
            bar = "█" * min(cnt, 30) + (f"…+{cnt-30}" if cnt > 30 else "")
            print(f"      {cls}  : {cnt:4d}  {bar}")
        print(f"  Abnormal Beats  : {insights['abnormal_ratio']*100:.1f}%")
        print("-" * W)
        print(f"  Risk Score      : {insights['risk_score']} / 100  "
              f"[PROTOTYPE — not a clinical diagnosis]")
        print(f"  Risk Label      : {insights['risk_label']}")
        print("-" * W)
        print("  Interpretation  :")
        words = insights["interpretation"].split()
        line  = "    "
        for w in words:
            if len(line) + len(w) + 1 > 57:
                print(line)
                line = "    " + w + " "
            else:
                line += w + " "
        if line.strip():
            print(line)
        print("=" * W)

    # ----------------------------------------------------------
    # PlotProcessing (preserved from original)
    # ----------------------------------------------------------
    def PlotProcessing(self, signal, filtered, integral, r_peaks, beats=None):
        time_ax  = np.arange(len(signal)) / self.SamplingFreq
        has_beats = beats is not None and len(beats) > 0
        n_plots   = 4 if has_beats else 3

        fig, axes = plt.subplots(n_plots, 1, figsize=(14, 3 * n_plots))

        axes[0].plot(time_ax, signal, color="tab:blue")
        axes[0].set_title("Raw ECG Signal")
        axes[0].set_ylabel("Amplitude (mV)")
        axes[0].set_xlabel("Time (s)")
        axes[0].grid(True)

        axes[1].plot(time_ax, filtered, color="tab:orange")
        axes[1].scatter(r_peaks / self.SamplingFreq, filtered[r_peaks],
                        color="red", marker="o", label="R-Peaks")
        axes[1].set_title("Filtered ECG with Detected R-Peaks")
        axes[1].set_ylabel("Amplitude (mV)")
        axes[1].set_xlabel("Time (s)")
        axes[1].grid(True)
        axes[1].legend(loc="upper right")

        axes[2].plot(time_ax, integral, color="tab:green")
        axes[2].set_title("Pan-Tompkins Moving-Window Integration")
        axes[2].set_ylabel("Integrated Energy")
        axes[2].set_xlabel("Time (s)")
        axes[2].grid(True)

        if has_beats:
            for b in beats:
                axes[3].plot(b, alpha=0.3, color="tab:purple")
            axes[3].set_title("Extracted and Normalised 190-Sample Beats")
            axes[3].set_xlabel("Sample Index")
            axes[3].set_ylabel("Normalised Amplitude")
            axes[3].grid(True)

        plt.tight_layout()
        plt.show()

    # ----------------------------------------------------------
    # Mode 1 – CSV
    # ----------------------------------------------------------
    def PredictFromCSV(self,
                       csv_path: str,
                       target_column: str = "Voltage_mV") -> dict:
        """
        Mode 1: Offline CSV testing.

        Accepts a CSV with 'ECG_mV', 'Voltage_mV', or 'ADC_Value' column.
        ADC_Value is auto-converted using adc_to_mv().
        """
        print(f"\n[CSV MODE] Loading ECG data from '{csv_path}'…")
        data = pd.read_csv(csv_path)

        if target_column in data.columns:
            signal = data[target_column].values.astype(np.float64)
        elif "ECG_mV" in data.columns:
            signal = data["ECG_mV"].values.astype(np.float64)
        elif "ADC_Value" in data.columns:
            print("[INFO] ADC_Value column found — converting with adc_to_mv()…")
            signal = np.vectorize(adc_to_mv)(data["ADC_Value"].values)
        else:
            raise ValueError(
                f"None of '{target_column}', 'ECG_mV', or 'ADC_Value' "
                f"found in '{csv_path}'."
            )

        result = self.Predict(signal)

        if len(result.get("r_peaks", [])) > 0:
            self.PlotProcessing(
                signal,
                result["filtered_signal"],
                result["integrated_signal"],
                result["r_peaks"],
                result["beats"],
            )
        return result

    def __call__(self, signal: np.ndarray) -> dict:
        return self.Predict(signal)


# ============================================================
# RealtimeECGProcessor
# ============================================================
class RealtimeECGProcessor:
    """
    Consumes mV samples from a queue, runs the rolling-window
    pipeline, updates display and logs.

    Processing steps per window:
        1. Pop WINDOW_SAMPLES from rolling buffer
        2. StreamingButterworthFilter.filter_chunk()
        3. PanTompkinsDetector.windowed_detect()
        4. Map local peak indices → global stream indices
        5. Discard peaks already processed (dedup)
        6. BPMCalculator.add_rr()
        7. ExtractBeats (on global signal buffer)
        8. XGBoostClassifier (predict + predict_proba)
        9. RiskAnalyzer.compute()
        10. ECGLogger  (log_rpeak, log_prediction, log_insights)
        11. RealtimeDisplay.update_snapshot()
    """

    def __init__(self, sample_queue: asyncio.Queue, logger: ECGLogger,
                 display: RealtimeDisplay):
        self._queue    = sample_queue
        self._logger   = logger
        self._display  = display

        # Streaming components
        self._stream_filt  = StreamingButterworthFilter()
        self._detector     = PanTompkinsDetector(fs=SAMPLING_FREQ)
        self._bpm_calc     = BPMCalculator(fs=SAMPLING_FREQ)

        # XGBoost model
        print("[INFO] Loading XGBoost model for real-time processor…")
        self._model = XGBClassifier()
        self._model.load_model(MODEL_PATH)
        print("[INFO] Model ready.")

        # Global signal buffer (mV) — kept for beat extraction spanning windows
        self._global_buf: deque[float] = deque(maxlen=WINDOW_SAMPLES * 3)
        self._global_idx   = 0          # total samples received so far

        # Deduplication
        self._last_rpeak_global = -1
        self._beat_counter      = 0

        # Stats accumulators
        self._all_class_names: list[str] = []
        self._all_bpms:        list[float] = []

        # Latest ADC/mV for display
        self._latest_adc = 0
        self._latest_mv  = 0.0

    # ----------------------------------------------------------
    async def run(self):
        """Async loop: drain the queue and process windows."""
        chunk_buf: list[float] = []   # accumulates mV before each window

        while True:
            try:
                mv, adc = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            self._latest_adc = adc
            self._latest_mv  = mv
            self._global_buf.append(mv)
            self._global_idx += 1
            chunk_buf.append(mv)
            self._display.push_sample(mv)

            # Log every sample
            self._logger.log_sample(adc, mv)

            # Trigger analysis once a full window step has accumulated
            if len(chunk_buf) >= WINDOW_STEP:
                await asyncio.get_event_loop().run_in_executor(
                    None, self._process_window, list(chunk_buf)
                )
                chunk_buf.clear()

    # ----------------------------------------------------------
    def _process_window(self, new_chunk: list[float]):
        """
        Called in a thread-pool executor so it doesn't block the
        event loop (and thus WebSocket reception).
        """
        if len(self._global_buf) < WINDOW_SAMPLES:
            return   # not enough data yet

        # Take the most recent WINDOW_SAMPLES from global buffer
        window_mv = np.array(list(self._global_buf)[-WINDOW_SAMPLES:],
                             dtype=np.float64)
        window_offset = self._global_idx - WINDOW_SAMPLES  # global index of window[0]

        # --- 1. Streaming bandpass filter --------------------------
        try:
            filtered = self._stream_filt.filter_chunk(window_mv.copy())
        except Exception as exc:
            _pylog.error(f"Filter error: {exc}")
            return

        # --- 2. Pan-Tompkins R-peak detection ----------------------
        try:
            local_peaks, _ = self._detector.windowed_detect(filtered)
        except Exception as exc:
            _pylog.error(f"R-peak detection error: {exc}")
            return

        if len(local_peaks) == 0:
            return

        # Convert to global indices
        global_peaks = local_peaks + window_offset

        # --- 3. Deduplicate ----------------------------------------
        new_peaks = [gp for gp in global_peaks if gp > self._last_rpeak_global]
        if not new_peaks:
            return

        # --- 4. BPM from RR intervals ------------------------------
        all_peaks_sorted = sorted([self._last_rpeak_global] + new_peaks) \
                           if self._last_rpeak_global >= 0 else new_peaks

        for i in range(1 if self._last_rpeak_global >= 0 else 1,
                       len(all_peaks_sorted)):
            rr_s = int(all_peaks_sorted[i] - all_peaks_sorted[i - 1])
            bpm  = self._bpm_calc.add_rr(rr_s)
            rr_ms = (rr_s / SAMPLING_FREQ) * 1000.0
            self._logger.log_rpeak(
                all_peaks_sorted[i], rr_s, rr_ms, bpm
            )
            if bpm:
                self._all_bpms.append(bpm)

        rolling_bpm = self._bpm_calc.rolling_bpm
        latest_rr   = self._bpm_calc.rr_intervals_ms
        latest_rr_val = latest_rr[-1] if latest_rr else None

        # --- 5. Beat extraction + XGBoost --------------------------
        global_arr = np.array(list(self._global_buf), dtype=np.float64)
        buf_offset  = self._global_idx - len(self._global_buf)

        for gp in new_peaks:
            local_gp = gp - buf_offset
            start    = local_gp - WINDOW_B4_PEAK
            end      = local_gp + WINDOW_AF_PEAK

            if start < 0 or end > len(global_arr):
                continue

            beat = global_arr[start:end]
            if len(beat) != BEAT_LENGTH:
                continue

            mean = float(np.mean(beat))
            std  = float(np.std(beat))
            norm = (beat - mean) / std if std != 0 else beat - mean

            X = norm.astype(np.float32).reshape(1, -1)

            try:
                pred    = self._model.predict(X)
                proba   = self._model.predict_proba(X)
                cls_id  = int(pred[0])
                cls_nm  = CLASS_NAMES[cls_id]
                conf    = float(np.max(proba)) * 100.0
            except Exception as exc:
                _pylog.error(f"XGBoost inference error: {exc}")
                continue

            self._beat_counter += 1
            self._all_class_names.append(cls_nm)

            self._logger.log_prediction(
                self._beat_counter, gp, cls_id, cls_nm, conf
            )
            _pylog.info(
                f"Beat {self._beat_counter} | R-peak {gp} | "
                f"{cls_nm} | {conf:.2f}%"
            )

            # --- 6. Risk / insights snapshot -----------------------
            sdnn  = self._bpm_calc.sdnn_ms
            rmssd = self._bpm_calc.rmssd_ms
            abn   = self._abnormal_ratio()
            risk_score, risk_label = RiskAnalyzer.compute(
                rolling_bpm if rolling_bpm else 75.0, abn, sdnn
            )

            bpm_list = self._all_bpms
            min_bpm  = float(min(bpm_list)) if bpm_list else 0.0
            max_bpm  = float(max(bpm_list)) if bpm_list else 0.0

            if rolling_bpm:
                self._logger.log_insights(
                    rolling_bpm, min_bpm, max_bpm,
                    sdnn, rmssd, abn, risk_score, risk_label
                )

            # --- 7. Update display snapshot ------------------------
            snap = {
                "adc"          : self._latest_adc,
                "ecg_mv"       : f"{self._latest_mv:+.3f}",
                "bpm"          : rolling_bpm,
                "rr_ms"        : latest_rr_val,
                "beat_index"   : self._beat_counter,
                "class_name"   : cls_nm,
                "confidence"   : conf,
                "risk_score"   : risk_score,
                "risk_label"   : risk_label,
                "sdnn_ms"      : sdnn,
                "rmssd_ms"     : rmssd,
                "abnormal_ratio": abn,
            }
            self._display.update_snapshot(snap)
            self._display.print_status()

        self._last_rpeak_global = max(new_peaks)

    def _abnormal_ratio(self) -> float:
        total = len(self._all_class_names)
        if total == 0:
            return 0.0
        abnormal = sum(1 for c in self._all_class_names if c != "N")
        return abnormal / total


# ============================================================
# WebSocketReceiver
# ============================================================
class WebSocketReceiver:
    """
    Connects to the ESP32 WebSocket endpoint and feeds raw ADC
    integers into the asyncio.Queue.

    Reconnects automatically on disconnect or error.
    """

    def __init__(self, queue: asyncio.Queue):
        self._queue = queue
        self._uri   = f"ws://{WEBSOCKET_HOST}:{WEBSOCKET_PORT}{WEBSOCKET_PATH}"

    async def run(self):
        if not _HAS_WEBSOCKETS:
            print("[ERROR] 'websockets' package not installed. "
                  "Run: pip install websockets")
            return

        while True:   # outer reconnect loop
            try:
                print(f"[WS] Connecting to {self._uri} …")
                async with websockets.connect(
                    self._uri,
                    ping_interval=20,
                    ping_timeout=10,
                ) as ws:
                    print(f"[WS] Connected.")
                    async for message in ws:
                        await self._handle_message(message)

            except (websockets.exceptions.ConnectionClosedError,
                    websockets.exceptions.ConnectionClosedOK) as exc:
                _pylog.warning(f"WS closed: {exc}. Reconnecting in {WS_RECONNECT_DELAY_S}s…")
                print(f"[WS] Connection closed ({exc}). "
                      f"Reconnecting in {WS_RECONNECT_DELAY_S}s…")
            except OSError as exc:
                _pylog.error(f"WS OS error: {exc}. Retrying in {WS_RECONNECT_DELAY_S}s…")
                print(f"[WS] Cannot reach {self._uri}: {exc}. "
                      f"Retrying in {WS_RECONNECT_DELAY_S}s…")
            except Exception as exc:
                _pylog.error(f"WS unexpected error: {exc}")
                print(f"[WS] Unexpected error: {exc}. Retrying…")

            await asyncio.sleep(WS_RECONNECT_DELAY_S)

    async def _handle_message(self, message: str):
        """Parse one WebSocket message; put (mv, adc) onto the queue."""
        try:
            raw = message.strip()
            if not raw:
                return
            adc = int(float(raw))   # handles "340\n", "340.0", etc.

            if not (ADC_MIN <= adc <= ADC_MAX):
                _pylog.debug(f"ADC out of range: {adc} — discarded")
                return

            mv = adc_to_mv(adc)
            await self._queue.put((mv, adc))

        except (ValueError, TypeError) as exc:
            _pylog.debug(f"Malformed WS message '{message}': {exc}")


# ============================================================
# RunRealtime  –  Mode 2 entry point
# ============================================================
def RunRealtime():
    """
    Mode 2: Real-time ECG from ESP32 over WebSocket.

    Architecture:
        WebSocketReceiver   → asyncio.Queue
        RealtimeECGProcessor ← drains queue, runs pipeline in executor
        RealtimeDisplay     ← matplotlib animation in main thread
    """
    if not _HAS_WEBSOCKETS:
        print("[ERROR] Install websockets first:  pip install websockets")
        sys.exit(1)

    print("=" * 60)
    print("  REAL-TIME ECG MONITOR  (Mode 2 — ESP32 WebSocket)")
    print(f"  Endpoint  : ws://{WEBSOCKET_HOST}:{WEBSOCKET_PORT}{WEBSOCKET_PATH}")
    print(f"  Sampling  : {SAMPLING_FREQ} Hz")
    print(f"  Window    : {WINDOW_SECONDS} s  ({WINDOW_SAMPLES} samples)")
    print(f"  Step      : {WINDOW_STEP_S} s  ({WINDOW_STEP} samples)")
    print(f"  Model     : {MODEL_PATH}")
    print("=" * 60)

    sample_queue = asyncio.Queue(maxsize=SAMPLING_FREQ * 30)  # 30-s buffer cap
    logger       = ECGLogger()
    display      = RealtimeDisplay()

    processor    = RealtimeECGProcessor(sample_queue, logger, display)
    receiver     = WebSocketReceiver(sample_queue)

    async def _async_main():
        await asyncio.gather(
            receiver.run(),
            processor.run(),
        )

    # Start the async tasks in a background thread so the main thread
    # can run the matplotlib animation loop (required by most GUI backends).
    def _run_async():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_async_main())
        except KeyboardInterrupt:
            pass
        finally:
            loop.close()

    t = threading.Thread(target=_run_async, daemon=True)
    t.start()

    display.start_animation()

    try:
        while t.is_alive():
            plt.pause(0.05)
    except KeyboardInterrupt:
        print("\n[INFO] Shutting down…")


# ============================================================
# main()
# ============================================================
def main():
    """
    Entry point.

    Usage
    -----
    python PreprocessClassifyLog.py                     # Mode 1: CSV
    python PreprocessClassifyLog.py --realtime          # Mode 2: WebSocket
    python PreprocessClassifyLog.py --csv path/to.csv  # Mode 1: custom CSV
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="ECG Monitor — CSV mode or ESP32 real-time mode"
    )
    parser.add_argument(
        "--realtime", action="store_true",
        help="Run in real-time mode (ESP32 WebSocket)"
    )
    parser.add_argument(
        "--csv", type=str, default=None,
        help="Path to CSV file for offline testing (default: M2/data_converted.csv)"
    )
    parser.add_argument(
        "--column", type=str, default="ECG_mV",
        help="Target column name in CSV (default: ECG_mV)"
    )
    args = parser.parse_args()

    if args.realtime:
        RunRealtime()
    else:
        csv_path = args.csv or "M2/data_converted.csv"
        preprocessor = ECGPreprocessor()
        preprocessor.PredictFromCSV(csv_path, target_column=args.column)


if __name__ == "__main__":
    main()
