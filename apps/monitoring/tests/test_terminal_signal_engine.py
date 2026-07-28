from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from shared.python.roulette.terminal_signals.engine import (
    analyze_motor_a,
    analyze_motor_b,
    compute_cross_targets,
    compute_terminal_targets,
    detect_variant,
)
from shared.python.roulette.terminal_signals.performance import (
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
        "max_attempts": 2,
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


def test_summary_includes_target_size_random_baseline() -> None:
    rows = [
        {"status": "resolved", "first_hit_attempt": 1, "target_size": 7},
        {"status": "resolved", "first_hit_attempt": None, "target_size": 4},
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
            "status": "resolved",
            "target_size": 7,
            "attempts": [
                {"attempt": 1, "hit": False, "timestamp_utc": t1},
                {"attempt": 2, "hit": True, "timestamp_utc": t2},
            ],
        }
    ]

    result = simulate_profitability(
        rows,
        initial_bank=Decimal("100"),
        attempt_stakes=[Decimal("1"), Decimal("1.5")],
    )

    # -7 no G1; no G2: -10,50 + retorno 54 = +43,50; líquido total +36,50.
    assert result["net_profit"] == 36.5
    assert result["final_bank"] == 136.5
