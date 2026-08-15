"""
tests/test_serial_mock.py
──────────────────────────
Tests for the WiFi device manager mock ECG generator.

No hardware required. Validates that:
  - Mock generator produces values in the valid ADC range [0, 4095]
  - Input validation discards out-of-range / malformed values
  - WiFiManager starts and provides samples via callback in mock mode
"""

from __future__ import annotations

import asyncio
import pytest

from app.serial.wifi_manager import WiFiManager, _mock_ecg_sample, _ADC_MIN, _ADC_MAX


# ── Mock ECG generator ────────────────────────────────────

class TestMockECGGenerator:

    def test_generates_values_in_adc_range(self):
        for i in range(1000):
            val = _mock_ecg_sample(i * 0.004)
            assert _ADC_MIN <= val <= _ADC_MAX, f"Value {val} out of range at i={i}"

    def test_not_constant(self):
        """Signal should vary over time (not flat)."""
        values = [_mock_ecg_sample(i * 0.004) for i in range(250)]
        assert max(values) - min(values) > 10, "Mock ECG appears to be flat"


# ── ADC input validation (mirrors WiFiManager._device_endpoint logic) ────────

class TestADCValidation:

    @staticmethod
    def _validate(raw: str):
        """Replicate the inline validation from _device_endpoint."""
        try:
            value = float(raw.split(",")[0].strip())
        except ValueError:
            return None
        return value if _ADC_MIN <= value <= _ADC_MAX else None

    def test_valid_integer(self):
        assert self._validate("512") == 512.0

    def test_valid_decimal(self):
        assert self._validate("2048.5") == 2048.5

    def test_out_of_range_low(self):
        assert self._validate("-1") is None

    def test_out_of_range_high(self):
        assert self._validate("9999") is None

    def test_non_numeric(self):
        assert self._validate("ERROR") is None

    def test_empty_string(self):
        assert self._validate("") is None

    def test_csv_first_column(self):
        """ESP32 may send comma-separated frames — only first value used."""
        assert self._validate("512,extra,data") == 512.0


# ── WiFiManager mock integration ─────────────────────────

@pytest.mark.asyncio
async def test_wifi_manager_mock_mode():
    """WiFiManager should fire the callback via mock when no ESP32 connects."""
    received: list[float] = []

    def on_sample(val: float):
        received.append(val)

    manager = WiFiManager(on_sample=on_sample)
    # Shorten timeout so mock kicks in immediately during tests
    manager._CONNECT_TIMEOUT = 0.05

    await manager.start()
    await asyncio.sleep(0.4)   # allow ~100 mock samples at 250 Hz
    await manager.stop()

    assert len(received) > 0, "No samples received in mock mode"
    for v in received:
        assert _ADC_MIN <= v <= _ADC_MAX, f"Sample {v} out of ADC range"
