from __future__ import annotations

from api.routes import websocket_signals


def test_resolve_result_channel_supports_simulation_aliases() -> None:
    assert websocket_signals._resolve_result_channel("simulation") == websocket_signals.RESULT_CHANNEL_SIMULATION
    assert websocket_signals._resolve_result_channel("simulate") == websocket_signals.RESULT_CHANNEL_SIMULATION
    assert websocket_signals._resolve_result_channel("new_result_simulate") == websocket_signals.RESULT_CHANNEL_SIMULATION


def test_resolve_result_channel_falls_back_to_real_channel() -> None:
    assert websocket_signals._resolve_result_channel(None) == websocket_signals.RESULT_CHANNEL_REAL
    assert websocket_signals._resolve_result_channel("") == websocket_signals.RESULT_CHANNEL_REAL
    assert websocket_signals._resolve_result_channel("unknown") == websocket_signals.RESULT_CHANNEL_REAL

