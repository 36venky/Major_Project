"""
tests/test_serial_mock.py
──────────────────────────
Tests for the WiFi device manager.

No hardware required. Validates that:
  - ADC input validation correctly accepts in-range values
  - ADC input validation correctly discards out-of-range / malformed values
  - WiFiManager starts cleanly without crashing (no mock mode — hardware only)
"""

from __future__ import annotations

import pytest

from app.serial.wifi_manager import WiFiManager, _ADC_MIN, _ADC_MAX


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

    def test_adc_min_boundary(self):
        """Value at exact minimum (0) should be accepted."""
        assert self._validate("0") == 0.0

    def test_adc_max_boundary(self):
        """Value at exact maximum (4095) should be accepted."""
        assert self._validate("4095") == 4095.0

    def test_lead_off_marker(self):
        """'!' is the lead-off marker — should be rejected as non-numeric."""
        assert self._validate("!") is None


# ── WiFiManager lifecycle ─────────────────────────────────

@pytest.mark.asyncio
async def test_wifi_manager_starts_and_stops():
    """WiFiManager should start and stop cleanly with no hardware connected."""
    received: list[float] = []

    def on_sample(val: float):
        received.append(val)

    manager = WiFiManager(on_sample=on_sample)
    await manager.start()
    assert manager.is_connected is False   # no hardware — never connected
    await manager.stop()
    assert manager.is_connected is False


@pytest.mark.asyncio
async def test_wifi_manager_not_connected_without_hardware():
    """is_connected must be False at start since no real ESP32 is present."""
    manager = WiFiManager(on_sample=lambda v: None)
    await manager.start()
    assert not manager.is_connected
    await manager.stop()
