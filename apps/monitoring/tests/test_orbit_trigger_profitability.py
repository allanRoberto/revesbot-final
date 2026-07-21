from datetime import datetime, timedelta, timezone

import pytest

from shared.python.roulette.orbit.triggers.profitability import (
    simulate_trigger_profitability,
)


def _trial(*, first_hit, target_size=10, minute=0):
    return {
        "activation_timestamp_utc": datetime(2026, 7, 20, 18, minute, tzinfo=timezone.utc),
        "first_hit_attempt": first_hit,
        "target_size": target_size,
    }


def test_profitability_uses_integer_chip_per_number_and_stops_after_first_hit():
    result = simulate_trigger_profitability(
        [_trial(first_hit=2, target_size=10)],
        initial_bank=1000,
        attempt_stakes=[1, 2, 4, 8, 16],
    )

    assert result["total_staked"] == 30.0
    assert result["total_returned"] == 72.0
    assert result["final_bank"] == 1042.0
    assert result["net_profit"] == 42.0
    assert result["winning_signals"] == 1
    assert result["exact_hits_by_attempt"][1]["hits"] == 1


def test_profitability_charges_all_attempts_when_signal_misses():
    result = simulate_trigger_profitability(
        [_trial(first_hit=None, target_size=9)],
        initial_bank=1000,
        attempt_stakes=[1, 2, 4, 8, 16],
    )

    assert result["total_staked"] == 279.0
    assert result["total_returned"] == 0.0
    assert result["final_bank"] == 721.0
    assert result["losing_signals"] == 1
    assert result["signals_completed"] == 1


def test_profitability_stops_at_the_attempt_the_bank_cannot_cover():
    result = simulate_trigger_profitability(
        [_trial(first_hit=2), _trial(first_hit=1, minute=1)],
        initial_bank=15,
        attempt_stakes=[1, 2, 4, 8, 16],
    )

    assert result["final_bank"] == 5.0
    assert result["bankroll_insufficient"] is True
    assert result["bankroll_stop"] == {"signal": 1, "attempt": 2}
    assert result["signals_started"] == 1
    assert result["signals_completed"] == 0
    assert result["unplayed_signals"] == 1


def test_profitability_orders_trials_chronologically_and_downsamples_chart():
    start = datetime(2026, 7, 20, 18, tzinfo=timezone.utc)
    trials = [
        {
            "activation_timestamp_utc": start + timedelta(minutes=index),
            "first_hit_attempt": 1,
            "target_size": 9,
        }
        for index in reversed(range(20))
    ]
    result = simulate_trigger_profitability(
        trials,
        initial_bank=1000,
        attempt_stakes=[1, 0, 0, 0, 0],
        maximum_chart_points=8,
    )

    assert result["final_bank"] == 1540.0
    assert len(result["chart"]["points"]) <= 8
    assert result["chart"]["points"][0]["signal"] == 0
    assert result["chart"]["points"][-1]["signal"] == 20
    assert result["chart"]["points_capped"] is True


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"initial_bank": 0}, "banca inicial"),
        ({"attempt_stakes": [1, 2]}, "exatamente 5"),
        ({"attempt_stakes": [1, 2, 3, 4, -1]}, "nao podem ser negativos"),
        ({"attempt_stakes": [1, 2, 3, 4, 5.5]}, "valores inteiros"),
    ],
)
def test_profitability_validates_inputs(kwargs, message):
    parameters = {
        "trials": [_trial(first_hit=1)],
        "initial_bank": 100,
        "attempt_stakes": [1, 2, 3, 4, 5],
    }
    parameters.update(kwargs)
    with pytest.raises(ValueError, match=message):
        simulate_trigger_profitability(**parameters)
