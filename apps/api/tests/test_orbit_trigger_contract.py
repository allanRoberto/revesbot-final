from datetime import datetime, timezone

from api.services.orbit_trigger_service import serialize_trigger_trial
from shared.python.roulette.orbit.triggers.catalog import STRATEGIES


def test_trigger_catalog_has_eight_strategies_with_five_attempts():
    assert len(STRATEGIES) == 8
    assert {strategy.slug for strategy in STRATEGIES} == {
        "green-primeira",
        "allan",
        "inception",
        "inception-primeiros-4",
        "interrompimento",
        "distancia",
        "ryan",
        "ryan-2",
    }
    assert {strategy.max_attempts for strategy in STRATEGIES} == {5}


def test_trigger_history_contract_marks_hit_and_preserves_frozen_entry():
    first = datetime(2026, 7, 20, 18, 1, tzinfo=timezone.utc)
    second = datetime(2026, 7, 20, 18, 2, tzinfo=timezone.utc)
    result = serialize_trigger_trial(
        {
            "event_id": "event-1",
            "engine_version": "orbit_triggers_v1",
            "strategy_slug": "ryan",
            "roulette_id": "roulette-1",
            "activation_history_id": "history-1",
            "activation_timestamp_utc": datetime(2026, 7, 20, 18, 0, tzinfo=timezone.utc),
            "activation_number": 13,
            "recent_pivots": [13, 32, 15],
            "base_numbers": [22, 20],
            "entry_numbers": [22, 20, 18],
            "target_size": 3,
            "attempt_numbers": [7, 20],
            "attempt_timestamps_utc": [first, second],
            "first_hit_attempt": 2,
            "status": "pending",
            "max_attempts": 5,
        }
    )

    assert result["entry_numbers"] == [22, 20, 18]
    assert result["base_numbers"] == [22, 20]
    assert result["display_status"] == "hit"
    assert result["attempts"][0]["match"] is False
    assert result["attempts"][1]["match"] is True
    assert result["outcome"]["first_hit_attempt"] == 2
    assert result["outcome"]["first_hit_timestamp_utc"] == second
