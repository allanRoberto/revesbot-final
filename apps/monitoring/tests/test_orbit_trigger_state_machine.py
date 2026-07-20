from datetime import datetime, timezone

import pytest

from apps.monitoring.orbit_triggers.worker import main
from shared.python.roulette.orbit.triggers.performance import (
    build_trigger_performance_summary,
)
from shared.python.roulette.orbit.triggers.state_machine import (
    advance_candidate,
    advance_trigger_trial_document,
    build_ryan_entry,
)


def _prediction(top9=(8, 9, 10), pivots=(5, 6, 7)):
    return {
        "top9": list(top9),
        "recent_pivots": list(pivots),
    }


def _candidate(strategy: str, *, top9=(7, 8, 9), **extra):
    return {
        "strategy_slug": strategy,
        "source_trial_id": "source-1",
        "source_top9": list(top9),
        "observed_spins": 0,
        **extra,
    }


def test_trigger_worker_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ORBIT_TRIGGER_ENABLED", raising=False)
    assert main() == 0


def test_ryan_example_produces_22_and_20_as_base_numbers():
    result = build_ryan_entry(
        [32, 13, 15],
        [24, 16, 11, 6, 13, 27, 36, 22, 20],
    )

    assert result is not None
    assert result["confluence"] == (13,)
    assert result["remaining_pivots"] == (32, 15)
    assert result["base_numbers"] == (22, 20)
    assert {22, 20}.issubset(result["entry_numbers"])
    assert len(result["entry_numbers"]) <= 10


def test_ryan_requires_exactly_one_confluence():
    assert build_ryan_entry([32, 13, 15], [13, 15, 20]) is None
    assert build_ryan_entry([32, 13, 15], [1, 2, 3]) is None


def test_green_waits_one_spin_then_uses_current_top9():
    transition = advance_candidate(
        _candidate("green-primeira", wait_remaining=1),
        number=12,
        current_prediction=_prediction(top9=(2, 4, 6)),
    )

    assert transition.update["status"] == "activated"
    assert transition.activation is not None
    assert transition.activation.entry_numbers == (2, 4, 6)


def test_inception_activates_only_after_six_absent_spins():
    candidate = _candidate("inception", top9=(7, 8, 9))
    transition = None
    for number in [1, 2, 3, 4, 5, 6]:
        transition = advance_candidate(
            candidate,
            number=number,
            current_prediction=_prediction(),
        )
        candidate = {**candidate, **transition.update}

    assert transition is not None
    assert transition.activation is not None
    assert transition.activation.entry_numbers == (7, 8, 9)
    assert transition.update["status"] == "activated"


def test_inception_is_cancelled_when_a_target_appears():
    transition = advance_candidate(
        _candidate("inception", top9=(7, 8, 9)),
        number=8,
        current_prediction=_prediction(),
    )

    assert transition.activation is None
    assert transition.update["status"] == "cancelled_hit"


def test_interruption_requires_three_rhythm_hits_then_five_misses():
    candidate = _candidate(
        "interrompimento",
        top9=(7,),
        phase="learning",
        gap=0,
        rhythm_hits=0,
    )
    sequence = [7, 1, 7, 2, 3, 7, 1, 2, 3, 4, 5]
    transition = None
    for number in sequence:
        transition = advance_candidate(
            candidate,
            number=number,
            current_prediction=_prediction(top9=(11, 12, 13)),
        )
        candidate = {**candidate, **transition.update}

    assert transition is not None
    assert transition.activation is not None
    assert transition.activation.entry_numbers == (11, 12, 13)
    assert transition.activation.metadata["rhythm_hits"] == 3
    assert transition.activation.metadata["interruption_gap"] == 5


def test_distance_waits_d_minus_one_spins_before_reusing_source():
    candidate = _candidate("distancia", top9=(7,), phase="observing", wait_remaining=0)
    transitions = []
    for number in [1, 2, 7, 3, 4]:
        transition = advance_candidate(
            candidate,
            number=number,
            current_prediction=_prediction(),
        )
        transitions.append(transition)
        candidate = {**candidate, **transition.update}

    assert transitions[2].update["hit_distance"] == 3
    assert transitions[2].activation is None
    assert transitions[4].activation is not None
    assert transitions[4].activation.entry_numbers == (7,)


def test_trigger_trial_resolves_only_after_five_complete_attempts():
    trial = {
        "entry_numbers": [7, 8],
        "attempt_numbers": [],
        "attempt_history_ids": [],
        "attempt_timestamps_utc": [],
        "first_hit_attempt": None,
    }
    for index, number in enumerate([1, 7, 8, 2, 3], start=1):
        payload = advance_trigger_trial_document(
            trial,
            number=number,
            history_id=f"spin-{index}",
            timestamp=datetime.now(timezone.utc),
            max_attempts=5,
        )
        assert payload is not None
        trial = {**trial, **payload}

    assert trial["first_hit_attempt"] == 2
    assert trial["attempts_observed"] == 5
    assert trial["status"] == "resolved"


def test_trigger_performance_uses_variable_target_coverage():
    now = datetime.now(timezone.utc)
    summary = build_trigger_performance_summary(
        [
            {
                "status": "resolved",
                "attempts_observed": 5,
                "activation_timestamp_utc": now,
                "target_size": 9,
                "first_hit_attempt": 1,
            },
            {
                "status": "resolved",
                "attempts_observed": 5,
                "activation_timestamp_utc": now,
                "target_size": 19,
                "first_hit_attempt": None,
            },
        ],
        now=now,
    )

    curve = summary["windows"]["all"]["entry"]
    assert curve["average_target_size"] == pytest.approx(14)
    assert curve["attempts"][0]["exact_hits"] == 1
    assert curve["attempts"][0]["exact_hit_rate"] == pytest.approx(0.5)
    assert curve["misses_after_max_attempts"] == 1
    assert curve["attempts"][0]["hit_rate"] == pytest.approx(0.5)
    assert curve["attempts"][0]["random_baseline"] == pytest.approx(14 / 37, abs=1e-6)
