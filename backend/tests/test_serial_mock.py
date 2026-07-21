"""
tests/test_serial_mock.py
──────────────────────────
Tests for serial communication using the mock ECG generator.

No hardware required. Validates that:
  - Mock generator produces values in the valid ADC range [0, 4095]
  - SerialReader validates and discards out-of-range samples
  - SerialManager starts and provides samples via callback
"""

from __future__ import annotations

import asyncio
import pytest

from app.serial.serial_reader import SerialReader, _mock_ecg_sample, _ADC_MIN, _ADC_MAX


# ── Mock ECG generator ────────────────────────────────────

class TestMockECGGenerator:

    def test_generates_values_in_adc_range(self):
        for t in range(0, 1000):
            val = _mock_ecg_sample(t * 0.004, 250)
            assert _ADC_MIN <= val <= _ADC_MAX, f"Value {val} out of range at t={t}"

    def test_not_constant(self):
        """Signal should vary over time (not flat)."""
        values = [_mock_ecg_sample(t * 0.004, 250) for t in range(250)]
        assert max(values) - min(values) > 10, "Mock ECG appears to be flat"


# ── SerialReader validation ───────────────────────────────

class TestSerialReaderValidation:

    def test_valid_sample(self):
        assert SerialReader._validate("512") == 512.0

    def test_valid_decimal(self):
        assert SerialReader._validate("2048.5") == 2048.5

    def test_out_of_range_low(self):
        assert SerialReader._validate("-1") is None

    def test_out_of_range_high(self):
        assert SerialReader._validate("9999") is None

    def test_non_numeric(self):
        assert SerialReader._validate("ERROR") is None

    def test_empty_string(self):
        assert SerialReader._validate("") is None

    def test_csv_first_column(self):
        """Devices that send comma-separated data — only first value used."""
        assert SerialReader._validate("512,extra,data") == 512.0


# ── Mock stream integration ───────────────────────────────

@pytest.mark.asyncio
async def test_mock_stream_produces_samples():
    """Verify that mock mode yields valid ECG samples without real hardware."""
    reader = SerialReader()
    reader._mock_mode = True
    reader._running   = True

    samples = []
    async for val in reader.stream():
        samples.append(val)
        if len(samples) >= 25:   # collect 25 samples (100 ms @ 250 Hz)
            reader._running = False
            break

    assert len(samples) >= 20
    for s in samples:
        assert _ADC_MIN <= s <= _ADC_MAX


@pytest.mark.asyncio
async def test_serial_manager_mock_mode():
    """SerialManager should fire the callback in mock mode."""
    from app.serial.serial_manager import SerialManager

    received = []

    def on_sample(val: float):
        received.append(val)

    manager = SerialManager(on_sample=on_sample)
    await manager.start()
    await asyncio.sleep(0.3)   # allow ~75 mock samples at 250 Hz
    await manager.stop()

    assert len(received) > 0
    for v in received:
        assert _ADC_MIN <= v <= _ADC_MAX
