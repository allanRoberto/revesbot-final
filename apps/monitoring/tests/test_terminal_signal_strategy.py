from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from shared.python.roulette.terminal_signals.strategy import (
    compare_strategy_matrix,
    known_outcome,
    simulate_table_strategy,
)


BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def trial(
    event_id: str,
    roulette_id: str,
    *,
    activation_second: float,
    first_attempt_second: float,
    hit_attempt: int | None,
) -> dict:
    attempts = [
        {
            "attempt": attempt,
            "number": attempt,
            "hit": hit_attempt == attempt,
            "timestamp_utc": BASE
            + timedelta(seconds=first_attempt_second + attempt - 1),
        }
        for attempt in range(1, 11)
    ]
    return {
        "event_id": event_id,
        "roulette_id": roulette_id,
        "activation_timestamp_utc": BASE + timedelta(seconds=activation_second),
        "attempts_observed": 10,
        "target_size": 5,
        "attempts": attempts,
    }


def strategy(rows, *, mode="top1", cutoff=10):
    return simulate_table_strategy(
        rows,
        selection_mode=mode,
        max_attempts=2,
        ranking_lookback=3,
        tie_break_lookback=5,
        minimum_samples=3,
        minimum_assertiveness=0,
        initial_bank=Decimal("100"),
        attempt_stakes=[Decimal("1")] * 10,
        payout_mode="source_html",
        common_cohort_horizon=10,
        activation_cutoff=BASE + timedelta(seconds=cutoff),
    )


def test_known_outcome_uses_hit_time_or_horizon_loss_time() -> None:
    win = trial(
        "win",
        "a",
        activation_second=0,
        first_attempt_second=1,
        hit_attempt=2,
    )
    loss = trial(
        "loss",
        "b",
        activation_second=0,
        first_attempt_second=1,
        hit_attempt=None,
    )

    assert known_outcome(win, max_attempts=4) == (
        BASE + timedelta(seconds=2),
        True,
    )
    assert known_outcome(loss, max_attempts=4) == (
        BASE + timedelta(seconds=4),
        False,
    )


def test_top1_ranking_never_uses_outcomes_known_after_activation() -> None:
    rows = [
        trial(f"a-win-{i}", "a", activation_second=0, first_attempt_second=i, hit_attempt=1)
        for i in (1, 2, 3)
    ]
    rows += [
        trial(f"b-loss-{i}", "b", activation_second=0, first_attempt_second=i, hit_attempt=None)
        for i in (1, 2, 3)
    ]
    # Esses acertos de B pertencem a formações anteriores, mas só ficam
    # conhecidos depois dos candidatos ativados no segundo 10.
    rows += [
        trial(
            f"b-future-{i}",
            "b",
            activation_second=9,
            first_attempt_second=11 + i,
            hit_attempt=1,
        )
        for i in range(3)
    ]
    rows += [
        trial(
            "candidate-a",
            "a",
            activation_second=10,
            first_attempt_second=20,
            hit_attempt=1,
        ),
        trial(
            "candidate-b",
            "b",
            activation_second=10,
            first_attempt_second=20,
            hit_attempt=1,
        ),
    ]

    result = strategy(rows)

    assert "candidate-a" in result["selected_event_ids"]
    assert "candidate-b" not in result["selected_event_ids"]


def test_top1_and_top3_select_only_the_ranked_tables() -> None:
    rows = []
    for table_index, roulette_id in enumerate(("a", "b", "c", "d")):
        wins = 3 - table_index
        for index in range(3):
            rows.append(
                trial(
                    f"history-{roulette_id}-{index}",
                    roulette_id,
                    activation_second=0,
                    first_attempt_second=1 + index,
                    hit_attempt=1 if index < wins else None,
                )
            )
        rows.append(
            trial(
                f"candidate-{roulette_id}",
                roulette_id,
                activation_second=10,
                first_attempt_second=20,
                hit_attempt=1,
            )
        )

    top1 = strategy(rows, mode="top1")
    top3 = strategy(rows, mode="top3")

    assert set(top1["selected_event_ids"]) == {"candidate-a"}
    assert set(top3["selected_event_ids"]) == {
        "candidate-a",
        "candidate-b",
        "candidate-c",
    }


def test_matrix_keeps_same_t10_entry_cohort_for_every_horizon() -> None:
    rows = [
        trial(
            f"row-{index}",
            "a",
            activation_second=index,
            first_attempt_second=20 + index,
            hit_attempt=4 if index % 2 else 1,
        )
        for index in range(6)
    ]

    matrix = compare_strategy_matrix(
        rows,
        max_attempts_values=(2, 3, 4),
        selection_modes=("all",),
        ranking_lookback=3,
        tie_break_lookback=5,
        minimum_samples=3,
        minimum_assertiveness=0,
        initial_bank=Decimal("100"),
        attempt_stakes=[Decimal("1")] * 10,
        payout_mode="source_html",
        common_cohort_horizon=10,
        activation_cutoff=None,
    )

    assert [row["entries_considered"] for row in matrix] == [6, 6, 6]
    assert [row["selected_signals"] for row in matrix] == [6, 6, 6]


def test_compact_matrix_matches_detailed_financial_simulation() -> None:
    rows = [
        trial(
            f"row-{index}",
            "a" if index % 2 else "b",
            activation_second=index,
            first_attempt_second=20 + index,
            hit_attempt=(index % 5) + 1 if index % 4 else None,
        )
        for index in range(12)
    ]
    common = {
        "ranking_lookback": 3,
        "tie_break_lookback": 5,
        "minimum_samples": 3,
        "minimum_assertiveness": 0,
        "initial_bank": Decimal("100"),
        "attempt_stakes": [Decimal("1"), Decimal("1.5")] * 5,
        "payout_mode": "source_html",
        "common_cohort_horizon": 10,
        "activation_cutoff": None,
    }
    detailed = simulate_table_strategy(
        rows,
        selection_mode="all",
        max_attempts=4,
        **common,
    )
    compact = compare_strategy_matrix(
        rows,
        max_attempts_values=(4,),
        selection_modes=("all",),
        **common,
    )[0]

    assert compact["summary"]["won"] == detailed["summary"]["won"]
    assert compact["summary"]["lost"] == detailed["summary"]["lost"]
    for field in ("net_profit", "roi_on_staked", "total_staked", "max_drawdown"):
        assert compact["profitability"][field] == detailed["profitability"][field]
