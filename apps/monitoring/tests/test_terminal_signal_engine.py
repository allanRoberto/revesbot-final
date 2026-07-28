from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from apps.monitoring.terminal_signals.runtime import (
    RouletteRuntimeState,
    TerminalSignalWorker,
)
from shared.python.roulette.terminal_signals.engine import (
    analyze_motor_a,
    analyze_motor_b,
    compute_cross_targets,
    compute_terminal_targets,
    detect_variant,
)
from shared.python.roulette.terminal_signals.performance import (
    compare_attempt_horizons,
    simulate_profitability,
    summarize_trials,
)
from shared.python.roulette.terminal_signals.state_machine import advance_trial


def test_motor_a_uses_unique_common_terminal_from_wheel_neighbors() -> None:
    analysis = analyze_motor_a([0, 3])

    assert analysis.valid is True
    assert analysis.terminal == 6
    assert analysis.metadata["neighbors0"] == [26, 32]
    assert analysis.metadata["neighbors1"] == [35, 26]


def test_motor_a_rejects_equal_last_numbers() -> None:
    analysis = analyze_motor_a([7, 7, 12])

    assert analysis.valid is False
    assert "iguais" in analysis.reason


def test_motor_a_rejects_two_common_terminals_but_motor_b_selects_first() -> None:
    analysis_a = analyze_motor_a([1, 8])
    analysis_b = analyze_motor_b([0, 3, 1, 0, 8, 3])

    assert analysis_a.valid is False
    assert analysis_a.metadata["common_terminals"] == [0, 3]
    assert analysis_b.valid is True
    assert analysis_b.metadata["common_terminals"] == [0, 3]
    assert analysis_b.terminal == 0


def test_motor_b_uses_equal_historical_followers_directly() -> None:
    analysis = analyze_motor_b([0, 3, 24, 0, 24, 3])

    assert analysis.valid is True
    assert analysis.terminal == 4
    assert analysis.metadata["pulled0"] == 24
    assert analysis.metadata["pulled1"] == 24


def test_target_builders_match_html_semantics() -> None:
    assert compute_terminal_targets(6, with_neighbors=False) == (0, 6, 16, 26, 36)
    assert compute_terminal_targets(6, with_neighbors=True) == (
        0, 3, 6, 11, 13, 16, 24, 26, 27, 33, 34, 36,
    )
    assert compute_cross_targets(6, 4) == (0, 4, 6, 19, 21, 27, 34)
    assert compute_cross_targets(6, 6) == (0, 6, 27, 34)


def test_cross_and_twins_are_mutually_exclusive() -> None:
    cross_history = [0, 3, 24, 0, 24, 3]
    twin_history = [0, 3, 26, 0, 26, 3]

    cross = detect_variant("cruzado", cross_history)
    assert cross is not None
    assert (cross.terminal_a, cross.terminal_b) == (6, 4)
    assert detect_variant("gemeos", cross_history) is None

    twins = detect_variant("gemeos", twin_history)
    assert twins is not None
    assert (twins.terminal_a, twins.terminal_b) == (6, 6)
    assert detect_variant("cruzado", twin_history) is None


def test_activation_spin_is_never_counted_as_attempt() -> None:
    now = datetime.now(timezone.utc)
    trial = {
        "status": "pending",
        "activation_history_id": "activation",
        "targets": [0, 6],
        "attempts": [],
        "attempt_history_ids": [],
        "collection_horizon": 10,
        "collection_status": "collecting",
    }

    assert advance_trial(
        trial,
        number=6,
        history_id="activation",
        timestamp=now,
    ) is None

    update = advance_trial(
        trial,
        number=6,
        history_id="next",
        timestamp=now,
    )
    assert update is not None
    assert update["first_hit_attempt"] == 1
    assert update["outcome"] == "won"
    assert update["collection_status"] == "collecting"
    assert update["status"] == "pending"


def test_hit_does_not_stop_collection_and_first_hit_is_preserved_until_t10() -> None:
    now = datetime.now(timezone.utc)
    trial = {
        "status": "pending",
        "collection_status": "collecting",
        "activation_history_id": "activation",
        "targets": [6],
        "attempts": [],
        "attempt_history_ids": [],
        "collection_horizon": 10,
        "first_hit_attempt": None,
    }

    for attempt in range(1, 11):
        update = advance_trial(
            trial,
            number=6 if attempt == 2 else 1,
            history_id=f"spin-{attempt}",
            timestamp=now,
        )
        assert update is not None
        trial.update(update)

    assert trial["attempts_observed"] == 10
    assert trial["first_hit_attempt"] == 2
    assert trial["outcome"] == "won"
    assert trial["collection_status"] == "complete"
    assert trial["status"] == "resolved"


def test_same_spin_advances_multiple_overlapping_trials_independently() -> None:
    now = datetime.now(timezone.utc)
    base = {
        "status": "pending",
        "collection_status": "collecting",
        "targets": [9],
        "attempt_history_ids": [],
        "collection_horizon": 10,
    }
    first = {**base, "activation_history_id": "a", "attempts": []}
    second = {
        **base,
        "activation_history_id": "b",
        "attempts": [{"attempt": 1, "number": 1, "history_id": "older", "hit": False}],
        "attempt_history_ids": ["older"],
    }

    update_first = advance_trial(first, number=9, history_id="shared", timestamp=now)
    update_second = advance_trial(second, number=9, history_id="shared", timestamp=now)

    assert update_first and update_first["first_hit_attempt"] == 1
    assert update_second and update_second["first_hit_attempt"] == 2
    first.update(update_first)
    assert advance_trial(first, number=9, history_id="shared", timestamp=now) is None


def test_worker_keeps_overlapping_trials_active_after_hits() -> None:
    class FakeCollection:
        def update_one(self, *_args, **_kwargs):
            return SimpleNamespace(modified_count=1)

        def find_one(self, *_args, **_kwargs):
            return None

    worker = TerminalSignalWorker.__new__(TerminalSignalWorker)
    worker.variant = SimpleNamespace(slug="motor-a-seco")
    worker.trials_coll = FakeCollection()
    base = {
        "status": "pending",
        "collection_status": "collecting",
        "targets": [9],
        "attempt_history_ids": [],
        "collection_horizon": 10,
        "first_hit_attempt": None,
    }
    state = RouletteRuntimeState(
        roulette_id="pragmatic-auto-roulette",
        active_trials={
            "first": {**base, "event_id": "first", "attempts": []},
            "second": {
                **base,
                "event_id": "second",
                "attempts": [
                    {"attempt": 1, "number": 1, "history_id": "old", "hit": False}
                ],
                "attempt_history_ids": ["old"],
            },
        },
    )

    worker._advance_collecting(
        state,
        number=9,
        history_id="shared",
        timestamp=datetime.now(timezone.utc),
    )

    assert set(state.active_trials) == {"first", "second"}
    assert state.active_trials["first"]["first_hit_attempt"] == 1
    assert state.active_trials["second"]["first_hit_attempt"] == 2


def test_summary_includes_target_size_random_baseline() -> None:
    rows = [
        {
            "event_id": "one",
            "attempts_observed": 10,
            "target_size": 7,
            "attempts": [{"attempt": 1, "hit": True}],
        },
        {
            "event_id": "two",
            "attempts_observed": 10,
            "target_size": 4,
            "attempts": [{"attempt": attempt, "hit": False} for attempt in range(1, 11)],
        },
    ]

    summary = summarize_trials(rows, max_attempts=2)

    assert summary["resolved"] == 2
    assert summary["won"] == 1
    assert summary["assertiveness"] == 0.5
    assert summary["attempts"][1]["random_baseline"] > 0


def test_profitability_uses_real_target_count_and_g1_g2_stakes() -> None:
    t1 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 1, 12, 1, tzinfo=timezone.utc)
    rows = [
        {
            "event_id": "one",
            "roulette_id": "pragmatic-auto-roulette",
            "attempts_observed": 10,
            "target_size": 7,
            "attempts": [
                {"attempt": 1, "hit": False, "timestamp_utc": t1},
                {"attempt": 2, "hit": True, "timestamp_utc": t2},
                {"attempt": 3, "hit": False, "timestamp_utc": t2},
            ],
        }
    ]

    result = simulate_profitability(
        rows,
        initial_bank=Decimal("100"),
        attempt_stakes=[Decimal("1"), Decimal("1.5"), Decimal("9")],
        max_attempts=3,
    )

    # -7 no G1; no G2: -10,50 + retorno 54 = +43,50; líquido total +36,50.
    assert result["net_profit"] == 36.5
    assert result["final_bank"] == 136.5
    assert result["cashflow_events"] == 2


def test_attempt_comparison_uses_same_completed_t10_cohort() -> None:
    now = datetime.now(timezone.utc)
    complete = {
        "event_id": "complete",
        "roulette_id": "pragmatic-auto-roulette",
        "attempts_observed": 10,
        "target_size": 5,
        "attempts": [
            {
                "attempt": attempt,
                "hit": attempt == 4,
                "timestamp_utc": now,
            }
            for attempt in range(1, 11)
        ],
    }
    incomplete = {
        **complete,
        "event_id": "incomplete",
        "attempts_observed": 9,
        "attempts": complete["attempts"][:9],
    }

    scenarios = compare_attempt_horizons(
        [complete, incomplete],
        minimum_attempts=2,
        maximum_attempts=10,
        common_cohort_horizon=10,
        initial_bank=Decimal("100"),
        attempt_stakes=[Decimal("1")] * 10,
    )

    assert len(scenarios) == 9
    assert {row["summary"]["resolved"] for row in scenarios} == {1}
    assert scenarios[0]["summary"]["won"] == 0
    assert scenarios[2]["summary"]["won"] == 1
