from datetime import datetime, timezone

import pytest

from apps.monitoring.orbit_triggers.worker import OrbitTriggerWorker, main
from shared.python.roulette.orbit.triggers.performance import (
    build_trigger_performance_summary,
)
from shared.python.roulette.orbit.triggers.state_machine import (
    advance_candidate,
    advance_trigger_trial_document,
    build_ryan_entry,
    build_ryan2_entry,
    build_sum_last3_entry,
    expand_with_neighbors,
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


def test_ryan2_red_black_red_selects_every_red_target_from_top9():
    result = build_ryan2_entry([1, 2, 3, 4, 5, 8, 9, 10, 12])

    assert result is not None
    assert result["first_three"] == (1, 2, 3)
    assert result["first_colors"] == ("red", "black", "red")
    assert result["target_color"] == "red"
    assert result["base_numbers"] == (1, 3, 5, 9, 12)
    assert result["entry_numbers"] == expand_with_neighbors(
        (1, 3, 5, 9, 12), span=1
    )


def test_ryan2_black_red_black_selects_every_black_target_from_top9():
    result = build_ryan2_entry([2, 1, 4, 3, 6, 5, 8, 7, 10])

    assert result is not None
    assert result["first_colors"] == ("black", "red", "black")
    assert result["target_color"] == "black"
    assert result["base_numbers"] == (2, 4, 6, 8, 10)
    assert result["entry_numbers"] == expand_with_neighbors((2, 4, 6, 8, 10), span=1)


@pytest.mark.parametrize(
    "suggestion",
    [
        [1, 3, 2, 4, 5],
        [2, 4, 1, 3, 5],
        [1, 0, 3, 2, 4],
        [0, 1, 2, 3, 4],
        [1, 2],
    ],
)
def test_ryan2_rejects_non_alternating_or_green_top3(suggestion):
    assert build_ryan2_entry(suggestion) is None


def test_sum_last3_uses_digit_sums_without_reducing_the_total():
    result = build_sum_last3_entry(
        [25, 30, 14],
        [15, 7, 22, 4, 1, 2, 3, 5, 6],
    )

    assert result is not None
    assert result["digit_sums"] == (7, 3, 5)
    assert result["sum_total"] == 15
    assert result["gate_numbers"] == (32, 15, 19)
    assert result["matched_first_four"] == (15,)
    assert result["entry_numbers"] == (15, 7, 22, 4, 1, 2, 3, 5, 6)


@pytest.mark.parametrize(
    "pivots",
    [
        [21, 24, 24],
        [12, 24, 21],
        [9, 3, 5],
    ],
)
def test_sum_last3_rejects_repeats_mirrors_and_all_single_digit_trios(pivots):
    assert build_sum_last3_entry(
        pivots,
        [15, 32, 19, 7, 1, 2, 3, 4, 5],
    ) is None


def test_sum_last3_requires_total_or_physical_neighbor_in_first_four():
    assert build_sum_last3_entry(
        [25, 30, 14],
        [1, 2, 3, 4, 15, 32, 19, 7, 8],
    ) is None


def test_trigger_worker_registers_ryan2_as_an_immediate_entry(monkeypatch):
    worker = OrbitTriggerWorker.__new__(OrbitTriggerWorker)
    activations = []

    def capture(*, activation, current_prediction):
        del current_prediction
        activations.append(activation)
        return True

    monkeypatch.setattr(worker, "_create_trigger_trial", capture)
    worker._create_direct_entries(
        {
            "trial_id": "prediction-1",
            "top9": [1, 2, 3, 4, 5, 8, 9, 10, 12],
            "recent_pivots": [20, 21, 22],
        }
    )

    ryan2 = next(row for row in activations if row.strategy_slug == "ryan-2")
    assert ryan2.base_numbers == (1, 3, 5, 9, 12)
    assert ryan2.metadata["target_color"] == "red"
    assert ryan2.metadata["neighbor_span"] == 1


def test_trigger_worker_registers_sum_last3_with_top9_without_expansion(monkeypatch):
    worker = OrbitTriggerWorker.__new__(OrbitTriggerWorker)
    activations = []

    def capture(*, activation, current_prediction):
        del current_prediction
        activations.append(activation)
        return True

    monkeypatch.setattr(worker, "_create_trigger_trial", capture)
    monkeypatch.setattr(worker, "_sum_last3_entry_available", lambda prediction: True)
    top9 = [15, 7, 22, 4, 1, 2, 3, 5, 6]
    worker._create_direct_entries(
        {
            "trial_id": "prediction-sum-1",
            "top9": top9,
            "recent_pivots": [25, 30, 14],
        }
    )

    activation = next(row for row in activations if row.strategy_slug == "soma-ultimos-3")
    assert activation.entry_numbers == tuple(top9)
    assert activation.base_numbers == (15,)
    assert activation.metadata["sum_total"] == 15
    assert activation.metadata["gate_numbers"] == [32, 15, 19]


class _LatestTrialCollection:
    def __init__(self, latest):
        self.latest = latest

    def find_one(self, *args, **kwargs):
        del args, kwargs
        return self.latest


def test_sum_last3_blocks_overlap_and_the_spin_that_resolves_the_previous_signal():
    worker = OrbitTriggerWorker.__new__(OrbitTriggerWorker)
    prediction = {
        "roulette_id": "roulette-1",
        "anchor_history_id": "spin-4",
    }

    worker.trigger_trials = _LatestTrialCollection({"status": "pending"})
    assert worker._sum_last3_entry_available(prediction) is False

    worker.trigger_trials = _LatestTrialCollection(
        {
            "status": "resolved",
            "attempt_history_ids": ["spin-2", "spin-3", "spin-4"],
        }
    )
    assert worker._sum_last3_entry_available(prediction) is False

    prediction["anchor_history_id"] = "spin-5"
    assert worker._sum_last3_entry_available(prediction) is True


def test_sum_last3_uses_three_attempts_while_existing_strategies_keep_five():
    worker = OrbitTriggerWorker.__new__(OrbitTriggerWorker)
    worker.max_attempts = 5

    assert worker._strategy_max_attempts("soma-ultimos-3") == 3
    assert worker._strategy_max_attempts("allan") == 5


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


def test_three_attempt_trial_keeps_observing_after_first_hit_without_recounting_it():
    trial = {
        "entry_numbers": [15],
        "attempt_numbers": [],
        "attempt_history_ids": [],
        "attempt_timestamps_utc": [],
        "first_hit_attempt": None,
    }
    for index, number in enumerate([15, 15, 2], start=1):
        payload = advance_trigger_trial_document(
            trial,
            number=number,
            history_id=f"spin-{index}",
            timestamp=datetime.now(timezone.utc),
            max_attempts=3,
        )
        assert payload is not None
        trial = {**trial, **payload}

    assert trial["attempt_numbers"] == [15, 15, 2]
    assert trial["first_hit_attempt"] == 1
    assert trial["attempts_observed"] == 3
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
