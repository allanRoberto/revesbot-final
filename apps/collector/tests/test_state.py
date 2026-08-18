from __future__ import annotations

from apps.collector.collector.state import CollectorState


def test_readiness_requires_dependencies_and_fresh_activity():
    state = CollectorState()
    state.mongo_ok = True
    state.redis_ok = True
    state.set_connection(True)
    state.record_message()
    state.record_persisted("pragmatic-auto-roulette")
    ready, reasons = state.readiness(90, 180, 120)
    assert ready is True
    assert reasons == []


def test_readiness_reports_disconnected_websocket():
    state = CollectorState()
    state.mongo_ok = True
    state.redis_ok = True
    ready, reasons = state.readiness(90, 180, 120)
    assert ready is False
    assert "websocket_disconnected" in reasons


def test_recovery_counters_are_exposed_in_snapshot():
    state = CollectorState()
    state.record_persisted("pragmatic-auto-roulette", recovered=True)
    state.record_recovery_failure("recovery_window_exhausted")
    snapshot = state.snapshot(90, 180, 120)
    assert snapshot["recovered_results_total"] == 1
    assert snapshot["recovery_failures_total"] == 1
    assert snapshot["last_error"] == "recovery_window_exhausted"
