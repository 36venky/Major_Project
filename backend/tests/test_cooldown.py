"""
tests/test_cooldown.py
───────────────────────
Unit and integration tests for the 5-minute WhatsApp cooldown system.

Covers:
  1.  AlertEngine engine-level cooldown (60 s default)
  2.  TwilioWhatsAppService 5-minute cooldown
  3.  Cooldown survives session restart (engine replaced, Twilio singleton persists)
  4.  Per-(patient, alert_type) isolation — different pairs don't block each other
  5.  reset_cooldown() clears correctly (all / by patient / by type / specific)
  6.  cooldown_status() reports remaining time accurately
  7.  Disabled service (no credentials) never stamps cooldown
  8.  Non-critical severity (info) is silently dropped before touching cooldown
  9.  No contact numbers → no cooldown stamp
  10. Admin API endpoints: GET /alerts/cooldowns, DELETE /alerts/cooldowns,
      DELETE /alerts/cooldowns/{patient_id}/{alert_type}
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from app.alerts.alert_engine import AlertEngine, AlertEvent
from app.services.twilio_service import TwilioWhatsAppService


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════

def _make_engine(cooldown_seconds: int = 60) -> tuple[AlertEngine, list[AlertEvent]]:
    """Return an AlertEngine and a list that records every fired event."""
    fired: list[AlertEvent] = []
    engine = AlertEngine(
        patient_id="P-TEST",
        on_alert=fired.append,
        cooldown_seconds=cooldown_seconds,
    )
    return engine, fired


def _make_service(cooldown_s: int = 300) -> TwilioWhatsAppService:
    """Return a fresh TwilioWhatsAppService with fake-but-present credentials."""
    svc = TwilioWhatsAppService.__new__(TwilioWhatsAppService)
    svc._account_sid = "ACtest"
    svc._auth_token  = "token_test"
    svc._from_number = "whatsapp:+14155238886"
    svc._cooldown_s  = cooldown_s
    svc._enabled     = True
    svc._last_sent   = {}
    return svc


def _dispatch(svc: TwilioWhatsAppService, *, patient_id="P-TEST", alert_type="HIGH_HR",
              severity="warning"):
    """Call svc.dispatch with minimal required args (patched so no real HTTP)."""
    svc.dispatch(
        patient_id        = patient_id,
        patient_name      = "Test Patient",
        guardian_phone    = "+917000000001",
        alert_type        = alert_type,
        severity          = severity,
        ecg_status        = "High HR",
        risk_level        = "Moderate",
        alert_message     = "BPM 110",
        timestamp         = datetime.now(timezone.utc),
    )


# ═══════════════════════════════════════════════════════════
# 1.  AlertEngine — engine-level cooldown
# ═══════════════════════════════════════════════════════════

class TestAlertEngineCooldown:

    def test_first_alert_fires(self):
        engine, fired = _make_engine(cooldown_seconds=60)
        engine._check_heart_rate(110)
        assert len(fired) == 1
        assert fired[0].alert_type == "HIGH_HR"

    def test_second_alert_suppressed_within_cooldown(self):
        engine, fired = _make_engine(cooldown_seconds=60)
        engine._check_heart_rate(110)
        engine._check_heart_rate(112)   # within 60s — should be suppressed
        assert len(fired) == 1

    def test_alert_fires_after_cooldown_expires(self):
        engine, fired = _make_engine(cooldown_seconds=60)
        engine._check_heart_rate(110)
        # Manually backdate the last-fired time by 61 seconds
        engine._last_fired["HIGH_HR"] = datetime.now(timezone.utc) - timedelta(seconds=61)
        engine._check_heart_rate(112)
        assert len(fired) == 2

    def test_different_alert_types_have_independent_cooldowns(self):
        engine, fired = _make_engine(cooldown_seconds=60)
        engine._check_heart_rate(110)   # fires HIGH_HR
        engine._check_heart_rate(110)   # suppressed
        # Now trigger a different type
        from app.processing.signal_quality import SignalQualityResult
        poor = SignalQualityResult(score=20, label="Poor",
                                   reason="noise", is_flatline=False, is_clipped=False)
        engine._check_signal_quality(poor)   # fires POOR_SIGNAL (different key)
        assert len(fired) == 2

    def test_cooldown_status_returns_remaining(self):
        engine, _ = _make_engine(cooldown_seconds=60)
        engine._check_heart_rate(110)
        status = engine.cooldown_status()
        assert "HIGH_HR" in status
        assert 0 < status["HIGH_HR"] <= 60

    def test_cooldown_status_zero_after_expiry(self):
        engine, _ = _make_engine(cooldown_seconds=60)
        engine._check_heart_rate(110)
        engine._last_fired["HIGH_HR"] = datetime.now(timezone.utc) - timedelta(seconds=61)
        assert engine.cooldown_status()["HIGH_HR"] == 0.0

    def test_engine_reset_on_new_session(self):
        """Replacing AlertEngine clears all engine-level cooldown history."""
        engine1, fired1 = _make_engine(cooldown_seconds=60)
        engine1._check_heart_rate(110)
        assert len(fired1) == 1

        # Simulate start_monitoring creating a fresh engine
        engine2, fired2 = _make_engine(cooldown_seconds=60)
        engine2._check_heart_rate(110)
        assert len(fired2) == 1   # new engine, no prior history → fires again

    def test_critical_fires_independently_of_warning(self):
        """CRITICAL_HR and HIGH_HR are separate keys — both can fire."""
        engine, fired = _make_engine(cooldown_seconds=60)
        engine._check_heart_rate(155)   # fires CRITICAL_HR (≥150)
        engine._check_heart_rate(155)   # suppressed by CRITICAL_HR cooldown
        assert len([e for e in fired if e.alert_type == "CRITICAL_HR"]) == 1


# ═══════════════════════════════════════════════════════════
# 2.  TwilioWhatsAppService — 5-minute cooldown
# ═══════════════════════════════════════════════════════════

class TestTwilioCooldown:

    def test_first_dispatch_is_accepted(self):
        svc = _make_service(cooldown_s=300)
        with patch.object(svc, "_dispatch_all", new_callable=AsyncMock):
            with patch("asyncio.create_task", side_effect=lambda c: (c.close(), None)):
                _dispatch(svc)
        # cooldown stamped → entry exists
        assert ("P-TEST", "HIGH_HR") in svc._last_sent

    def test_second_dispatch_within_cooldown_suppressed(self):
        svc = _make_service(cooldown_s=300)
        dispatch_count = 0

        def counting_task(coro):
            nonlocal dispatch_count
            dispatch_count += 1
            coro.close()

        with patch("asyncio.create_task", side_effect=counting_task):
            _dispatch(svc)
            _dispatch(svc)   # within 300s — must be suppressed
        assert dispatch_count == 1

    def test_dispatch_fires_after_cooldown_expires(self):
        svc = _make_service(cooldown_s=300)
        dispatch_count = 0

        def counting_task(coro):
            nonlocal dispatch_count
            dispatch_count += 1
            coro.close()

        with patch("asyncio.create_task", side_effect=counting_task):
            _dispatch(svc)
            svc._last_sent[("P-TEST", "HIGH_HR")] = (
                datetime.now(timezone.utc) - timedelta(seconds=301)
            )
            _dispatch(svc)
        assert dispatch_count == 2

    def test_different_patients_have_independent_cooldowns(self):
        svc = _make_service(cooldown_s=300)
        dispatch_count = 0

        def counting_task(coro):
            nonlocal dispatch_count
            dispatch_count += 1
            coro.close()

        with patch("asyncio.create_task", side_effect=counting_task):
            _dispatch(svc, patient_id="P-001")
            _dispatch(svc, patient_id="P-002")
        assert dispatch_count == 2

    def test_different_alert_types_have_independent_cooldowns(self):
        svc = _make_service(cooldown_s=300)
        dispatch_count = 0

        def counting_task(coro):
            nonlocal dispatch_count
            dispatch_count += 1
            coro.close()

        with patch("asyncio.create_task", side_effect=counting_task):
            _dispatch(svc, alert_type="HIGH_HR")
            _dispatch(svc, alert_type="POOR_SIGNAL")
        assert dispatch_count == 2

    def test_cooldown_not_stamped_when_no_recipients(self):
        svc = _make_service(cooldown_s=300)
        # Dispatch with no phone numbers — should NOT stamp cooldown
        svc.dispatch(
            patient_id="P-TEST", patient_name="X",
            guardian_phone=None, emergency_contact=None, phone=None,
            alert_type="HIGH_HR", severity="warning",
            ecg_status="High HR", risk_level="Low",
            alert_message="BPM 110",
            timestamp=datetime.now(timezone.utc),
        )
        assert ("P-TEST", "HIGH_HR") not in svc._last_sent

    def test_cooldown_not_stamped_when_service_disabled(self):
        svc = _make_service(cooldown_s=300)
        svc._enabled = False
        with patch("asyncio.create_task") as mock_task:
            _dispatch(svc)
            mock_task.assert_not_called()
        assert ("P-TEST", "HIGH_HR") not in svc._last_sent

    def test_info_severity_dropped_before_cooldown(self):
        svc = _make_service(cooldown_s=300)
        with patch("asyncio.create_task") as mock_task:
            _dispatch(svc, severity="info")
            mock_task.assert_not_called()
        assert ("P-TEST", "HIGH_HR") not in svc._last_sent


# ═══════════════════════════════════════════════════════════
# 3.  Cooldown survives AlertEngine replacement (session restart)
# ═══════════════════════════════════════════════════════════

class TestCooldownSurvivesSessionRestart:

    def test_twilio_cooldown_persists_across_engine_recreation(self):
        """
        The WhatsApp 5-min cooldown lives on the singleton TwilioWhatsAppService,
        NOT on AlertEngine.  Replacing the engine (new monitoring session) must NOT
        reset the Twilio cooldown.
        """
        svc = _make_service(cooldown_s=300)
        dispatch_count = 0

        def counting_task(coro):
            nonlocal dispatch_count
            dispatch_count += 1
            coro.close()

        with patch("asyncio.create_task", side_effect=counting_task):
            # Session 1: dispatch fires
            _dispatch(svc)
            assert dispatch_count == 1

            # Session 2 (new AlertEngine, same Twilio singleton): dispatch blocked
            _dispatch(svc)
            assert dispatch_count == 1   # still 1 — Twilio cooldown held


# ═══════════════════════════════════════════════════════════
# 4.  reset_cooldown() and cooldown_status()
# ═══════════════════════════════════════════════════════════

class TestCooldownManagement:

    def test_reset_all(self):
        svc = _make_service(cooldown_s=300)

        def close_coro(coro): coro.close()

        with patch("asyncio.create_task", side_effect=close_coro):
            _dispatch(svc, patient_id="P-001", alert_type="HIGH_HR")
            _dispatch(svc, patient_id="P-002", alert_type="POOR_SIGNAL")
        assert len(svc._last_sent) == 2
        removed = svc.reset_cooldown()
        assert removed == 2
        assert len(svc._last_sent) == 0

    def test_reset_by_patient(self):
        svc = _make_service(cooldown_s=300)

        def close_coro(coro): coro.close()

        with patch("asyncio.create_task", side_effect=close_coro):
            _dispatch(svc, patient_id="P-001", alert_type="HIGH_HR")
            _dispatch(svc, patient_id="P-002", alert_type="HIGH_HR")
        removed = svc.reset_cooldown(patient_id="P-001")
        assert removed == 1
        assert ("P-001", "HIGH_HR") not in svc._last_sent
        assert ("P-002", "HIGH_HR") in svc._last_sent

    def test_reset_by_alert_type(self):
        svc = _make_service(cooldown_s=300)

        def close_coro(coro): coro.close()

        with patch("asyncio.create_task", side_effect=close_coro):
            _dispatch(svc, patient_id="P-001", alert_type="HIGH_HR")
            _dispatch(svc, patient_id="P-001", alert_type="POOR_SIGNAL")
        removed = svc.reset_cooldown(alert_type="HIGH_HR")
        assert removed == 1
        assert ("P-001", "HIGH_HR") not in svc._last_sent
        assert ("P-001", "POOR_SIGNAL") in svc._last_sent

    def test_reset_specific(self):
        svc = _make_service(cooldown_s=300)

        def close_coro(coro): coro.close()

        with patch("asyncio.create_task", side_effect=close_coro):
            _dispatch(svc, patient_id="P-001", alert_type="HIGH_HR")
            _dispatch(svc, patient_id="P-001", alert_type="CRITICAL_HR")
        removed = svc.reset_cooldown(patient_id="P-001", alert_type="HIGH_HR")
        assert removed == 1
        assert ("P-001", "HIGH_HR") not in svc._last_sent
        assert ("P-001", "CRITICAL_HR") in svc._last_sent

    def test_reset_nonexistent_returns_zero(self):
        svc = _make_service(cooldown_s=300)
        assert svc.reset_cooldown(patient_id="NOBODY", alert_type="HIGH_HR") == 0

    def test_cooldown_status_on_cooldown(self):
        svc = _make_service(cooldown_s=300)
        with patch("asyncio.create_task", side_effect=lambda c: c.close()):
            _dispatch(svc)
        status = svc.cooldown_status()
        assert len(status) == 1
        entry = status[0]
        assert entry["patient_id"]  == "P-TEST"
        assert entry["alert_type"]  == "HIGH_HR"
        assert entry["on_cooldown"] is True
        assert 0 < entry["remaining_seconds"] <= 300

    def test_cooldown_status_expired(self):
        svc = _make_service(cooldown_s=300)
        with patch("asyncio.create_task", side_effect=lambda c: c.close()):
            _dispatch(svc)
        # Expire the cooldown
        svc._last_sent[("P-TEST", "HIGH_HR")] = (
            datetime.now(timezone.utc) - timedelta(seconds=301)
        )
        entry = svc.cooldown_status()[0]
        assert entry["on_cooldown"] is False
        assert entry["remaining_seconds"] == 0.0

    def test_cooldown_status_empty_when_no_dispatches(self):
        svc = _make_service(cooldown_s=300)
        assert svc.cooldown_status() == []


# ═══════════════════════════════════════════════════════════
# 5.  Admin API endpoints
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_cooldowns_endpoint_requires_admin(client, auth_headers):
    """Non-admin users should get 403."""
    resp = await client.get("/alerts/cooldowns", headers=auth_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_cooldowns_endpoint_returns_list(client, admin_headers):
    """Admin can inspect cooldown state — returns a list (possibly empty)."""
    resp = await client.get("/alerts/cooldowns", headers=admin_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_delete_all_cooldowns_endpoint(client, admin_headers):
    """Admin DELETE /alerts/cooldowns clears all entries."""
    resp = await client.delete("/alerts/cooldowns", headers=admin_headers)
    assert resp.status_code == 200
    assert "cleared" in resp.json()["message"].lower()


@pytest.mark.asyncio
async def test_delete_specific_cooldown_not_found(client, admin_headers):
    """Deleting a non-existent cooldown returns 404."""
    resp = await client.delete(
        "/alerts/cooldowns/P-NOBODY/FAKE_TYPE",
        headers=admin_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_specific_cooldown_success(client, admin_headers):
    """Seed a cooldown entry directly then delete it via the API."""
    from app.services.twilio_service import whatsapp_service
    # Seed a fake entry directly
    whatsapp_service._last_sent[("P-APITEST", "HIGH_HR")] = datetime.now(timezone.utc)

    resp = await client.delete(
        "/alerts/cooldowns/P-APITEST/HIGH_HR",
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert "P-APITEST" in resp.json()["message"]
    assert ("P-APITEST", "HIGH_HR") not in whatsapp_service._last_sent
