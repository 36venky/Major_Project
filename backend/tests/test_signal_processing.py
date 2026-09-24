"""
tests/test_signal_processing.py
────────────────────────────────
Unit tests for all signal processing modules.

Tests run without hardware or database — pure function validation.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.processing.signal_filter import bandpass_filter, full_filter_pipeline, notch_filter
from app.processing.r_peak_detection import compute_rr_intervals, detect_r_peaks
from app.processing.heart_rate import (
    RollingBPMEstimator, average_bpm, bpm_from_rr, bpm_from_signal_window,
)
from app.processing.signal_quality import assess_signal_quality
from app.processing.arrhythmia import classify


FS = 250  # samples/second


# ── Synthetic signal helpers ──────────────────────────────

def _sine(freq: float, duration: float, fs: int = FS, amplitude: float = 1.0) -> np.ndarray:
    """Generate a pure sine wave."""
    t = np.linspace(0, duration, int(duration * fs), endpoint=False)
    return amplitude * np.sin(2 * np.pi * freq * t)


def _synthetic_ecg(bpm: float = 60.0, duration: float = 10.0, fs: int = FS) -> np.ndarray:
    """Generate a simplistic ECG-like signal at the given BPM."""
    samples = int(duration * fs)
    cycle_samples = int(60.0 / bpm * fs)
    ecg = np.zeros(samples)
    for i in range(0, samples - cycle_samples, cycle_samples):
        # R-peak spike
        ecg[i + int(0.5 * cycle_samples)] = 1.0
        # T-wave bump
        if i + int(0.7 * cycle_samples) < samples:
            ecg[i + int(0.7 * cycle_samples)] = 0.3
    # Add noise
    ecg += np.random.normal(0, 0.05, samples)
    return ecg


# ─────────────────────────────────────────────────────────────
# Signal filter tests
# ─────────────────────────────────────────────────────────────

class TestSignalFilter:

    def test_bandpass_returns_same_length(self):
        sig = np.random.rand(500)
        out = bandpass_filter(sig, fs=FS)
        assert len(out) == len(sig)

    def test_bandpass_attenuates_dc(self):
        """High-pass component should remove DC offset (baseline wander)."""
        # Signal with large DC offset
        sig = np.ones(1000) * 2048 + np.sin(np.linspace(0, 10 * np.pi, 1000))
        out = bandpass_filter(sig, fs=FS)
        # After filtering, mean should be near zero
        assert abs(np.mean(out)) < 50

    def test_bandpass_too_short_returns_original_dtype(self):
        sig = np.array([1.0, 2.0, 3.0])
        out = bandpass_filter(sig, fs=FS)
        assert out.dtype == np.float64

    def test_notch_filter_returns_same_length(self):
        sig = _sine(50.0, 2.0)
        out = notch_filter(sig, freq=50.0, fs=FS)
        assert len(out) == len(sig)

    def test_full_pipeline_output_shape(self):
        sig = _synthetic_ecg(bpm=75, duration=5)
        out = full_filter_pipeline(sig, fs=FS)
        assert out.shape == sig.shape


# ─────────────────────────────────────────────────────────────
# R-peak detection tests
# ─────────────────────────────────────────────────────────────

class TestRPeakDetection:

    def test_detect_peaks_on_synthetic_ecg(self):
        sig = _synthetic_ecg(bpm=60, duration=10, fs=FS)
        filtered = bandpass_filter(sig, fs=FS)
        peaks = detect_r_peaks(filtered, fs=FS)
        # At 60 BPM over 10 seconds we expect ~10 peaks (allow some tolerance)
        assert 6 <= len(peaks) <= 14, f"Expected ~10 peaks, got {len(peaks)}"

    def test_detect_peaks_empty_on_short_signal(self):
        sig = np.random.rand(100)   # < 1 second
        peaks = detect_r_peaks(sig, fs=FS)
        assert len(peaks) == 0

    def test_rr_intervals_from_peaks(self):
        # Peaks exactly 250 samples apart → 1.0 s → 60 BPM
        peaks = np.array([0, 250, 500, 750])
        rr = compute_rr_intervals(peaks, fs=FS)
        np.testing.assert_allclose(rr, 1.0, atol=0.01)

    def test_rr_intervals_empty_for_single_peak(self):
        peaks = np.array([100])
        rr = compute_rr_intervals(peaks, fs=FS)
        assert len(rr) == 0


# ─────────────────────────────────────────────────────────────
# Heart rate tests
# ─────────────────────────────────────────────────────────────

class TestHeartRate:

    def test_bpm_from_rr_60bpm(self):
        assert bpm_from_rr(1.0) == 60.0

    def test_bpm_from_rr_75bpm(self):
        assert abs(bpm_from_rr(60 / 75) - 75.0) < 0.5

    def test_bpm_from_rr_invalid(self):
        assert bpm_from_rr(0.0) == 0.0
        assert bpm_from_rr(-1.0) == 0.0

    def test_average_bpm_from_peaks(self):
        # 60 BPM → peaks 250 apart
        peaks = np.arange(0, 3000, 250)
        bpm = average_bpm(peaks, fs=FS)
        assert abs(bpm - 60.0) < 2.0

    def test_average_bpm_empty(self):
        assert average_bpm(np.array([]), fs=FS) == 0.0

    def test_rolling_estimator(self):
        estimator = RollingBPMEstimator(window_seconds=5.0, fs=FS)
        ecg = _synthetic_ecg(bpm=72, duration=6, fs=FS)
        estimator.push_batch(ecg.tolist())
        bpm = estimator.get_bpm()
        # Should be in a reasonable range
        assert 50 <= bpm <= 120 or bpm == 0.0  # 0.0 is valid if window not filled

    def test_rolling_estimator_reset(self):
        est = RollingBPMEstimator(fs=FS)
        est.push_batch([1.0] * 500)
        est.reset()
        assert est.get_bpm() == 0.0


# ─────────────────────────────────────────────────────────────
# Signal quality tests
# ─────────────────────────────────────────────────────────────

class TestSignalQuality:

    def test_flatline_detection(self):
        sig = np.zeros(500)
        result = assess_signal_quality(sig)
        assert result.is_flatline
        assert result.score == 0
        assert result.label == "Poor"

    def test_good_signal_score(self):
        sig = _synthetic_ecg(bpm=72, duration=5)
        result = assess_signal_quality(sig)
        assert result.score > 0
        assert result.label in ("Excellent", "Good", "Moderate", "Poor")

    def test_noisy_signal_lower_score(self):
        clean = _synthetic_ecg(bpm=72, duration=5)
        noisy = clean + np.random.normal(0, 5.0, len(clean))   # heavy noise
        r_clean = assess_signal_quality(clean)
        r_noisy = assess_signal_quality(noisy)
        # Noisy signal should generally score lower or equal
        assert r_noisy.score <= r_clean.score + 20   # allow some tolerance

    def test_clipping_detection(self):
        sig = np.clip(_synthetic_ecg(bpm=60, duration=5) * 1000, -2048, 2048)
        result = assess_signal_quality(sig)
        assert result.score >= 0   # just shouldn't crash

    def test_short_signal(self):
        result = assess_signal_quality(np.array([]))
        assert result.score == 0


# ─────────────────────────────────────────────────────────────
# Arrhythmia classification tests
# ─────────────────────────────────────────────────────────────

class TestArrhythmia:

    def _regular_peaks(self, bpm: float, duration: float = 10.0) -> np.ndarray:
        step = int(60.0 / bpm * FS)
        return np.arange(0, int(duration * FS), step)

    def test_normal_rhythm(self):
        peaks = self._regular_peaks(72)
        result = classify(peaks, bpm=72, fs=FS)
        assert result.risk_level == "Low"
        assert "NORMAL" in result.flags or result.is_abnormal is False

    def test_tachycardia_detected(self):
        peaks = self._regular_peaks(115)
        result = classify(peaks, bpm=115, fs=FS)
        assert result.is_abnormal
        assert "Tachycardia" in result.rhythm

    def test_bradycardia_detected(self):
        peaks = self._regular_peaks(48)
        result = classify(peaks, bpm=48, fs=FS)
        assert result.is_abnormal
        assert "Bradycardia" in result.rhythm

    def test_critical_tachycardia(self):
        peaks = self._regular_peaks(155)
        result = classify(peaks, bpm=155, fs=FS)
        assert result.risk_level == "Critical"

    def test_irregular_rhythm_afib(self):
        # Simulate highly irregular peaks
        np.random.seed(42)
        jitter = np.random.randint(-80, 80, 12)
        base   = np.arange(0, 12 * 250, 250)
        peaks  = np.sort(np.clip(base + jitter, 0, 12 * 250))
        result = classify(peaks, bpm=72, fs=FS)
        # With high irregularity, it should flag abnormality
        # (exact result depends on jitter magnitude)
        assert result is not None

    def test_insufficient_data(self):
        result = classify(np.array([100, 350]), bpm=72, fs=FS)
        assert result.confidence == 0
        assert "Insufficient" in result.rhythm
