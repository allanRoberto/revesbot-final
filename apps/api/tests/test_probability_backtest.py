from __future__ import annotations

import pytest

from api.services import probability_backtest_service


def _fake_prediction(selected: list[int]) -> dict:
    probability = 1.0 / 37.0
    return {
        "selected": selected,
        "selected_probability_mass": probability * len(selected),
        "ranking": [
            {"number": number, "probability": probability}
            for number in range(37)
        ],
    }


def test_backtest_recalculates_after_each_miss_without_future_leakage(
    monkeypatch,
) -> None:
    chronological = [1] * 50 + [2, 3, 4]
    calls: list[list[int]] = []

    def fake_calculate(history, *, order, number_count):
        calls.append(list(history))
        selected = [9] if history[-1] == 1 else [3]
        return _fake_prediction(selected)

    monkeypatch.setattr(
        probability_backtest_service,
        "calculate_number_probabilities",
        fake_calculate,
    )

    result = probability_backtest_service.run_probability_backtest_from_history(
        list(reversed(chronological)),
        roulette_id="test-roulette",
        number_count=1,
        attempts=3,
        entries_limit=1,
        minimum_history=50,
    )

    assert calls == [chronological[:50], chronological[:51]]
    detail = result["details"][0]
    assert detail["first_hit_attempt"] == 2
    assert [row["actual_number"] for row in detail["attempt_details"]] == [2, 3]
    assert detail["attempt_details"][0]["selected"] == [9]
    assert detail["attempt_details"][1]["selected"] == [3]
    assert detail["invested"] == 2.0
    assert detail["profit"] == 34.0
    assert result["recalculates_after_each_miss"] is True
    assert result["causal"] is True
    assert result["source_order"] == "newest_first"
    assert result["profit"]["initial_bankroll"] == 1000.0
    assert result["profit"]["ending_bankroll"] == 1034.0
    assert result["profit"]["curve"][-1]["balance"] == 1034.0


def test_backtest_reports_attempt_baseline_and_non_overlapping_sample(
    monkeypatch,
) -> None:
    chronological = [1] * 50 + [0, 1, 0, 1, 0, 1]

    monkeypatch.setattr(
        probability_backtest_service,
        "calculate_number_probabilities",
        lambda history, *, order, number_count: _fake_prediction([0]),
    )

    result = probability_backtest_service.run_probability_backtest_from_history(
        list(reversed(chronological)),
        roulette_id="test-roulette",
        number_count=1,
        attempts=2,
        entries_limit=4,
        minimum_history=50,
    )

    assert result["evaluated_entries"] == 4
    assert result["summary"]["hits"] == 4
    assert result["attempts"][0]["first_hits"] == 2
    assert result["attempts"][1]["first_hits"] == 2
    assert result["attempts"][1]["cumulative_hit_rate"] == pytest.approx(1.0)
    assert result["attempts"][1]["random_baseline"] == pytest.approx(
        1.0 - (36.0 / 37.0) ** 2,
        abs=1e-6,
    )
    assert result["non_overlapping"]["step"] == 2
    assert result["non_overlapping"]["entries"] == 2


def test_profit_summary_calculates_balance_drawdown_and_required_bankroll() -> None:
    rows = [
        {"profit": -20.0, "invested": 20.0},
        {"profit": -20.0, "invested": 20.0},
        {"profit": 26.0, "invested": 10.0},
    ]

    summary = probability_backtest_service._profit_summary(
        rows,
        initial_bankroll=100.0,
        maximum_entry_exposure=20.0,
    )

    assert summary["initial_bankroll"] == 100.0
    assert summary["ending_bankroll"] == 86.0
    assert summary["minimum_balance"] == 60.0
    assert summary["maximum_balance"] == 100.0
    assert summary["max_drawdown"] == 40.0
    assert summary["max_drawdown_percentage"] == pytest.approx(0.4)
    assert summary["max_drawdown_peak_entry"] == 0
    assert summary["max_drawdown_trough_entry"] == 2
    assert summary["required_bankroll"] == 60.0
    assert summary["bankroll_sufficient"] is True
    assert summary["bankroll_shortfall"] == 0.0
    assert [point["balance"] for point in summary["curve"]] == [
        100.0,
        80.0,
        60.0,
        86.0,
    ]

    insufficient = probability_backtest_service._profit_summary(
        rows,
        initial_bankroll=50.0,
        maximum_entry_exposure=20.0,
    )
    assert insufficient["required_bankroll"] == 60.0
    assert insufficient["bankroll_sufficient"] is False
    assert insufficient["bankroll_shortfall"] == 10.0


def test_backtest_rejects_invalid_or_insufficient_history() -> None:
    with pytest.raises(LookupError, match="Historico insuficiente"):
        probability_backtest_service.run_probability_backtest_from_history(
            [1] * 20,
            roulette_id="test-roulette",
            minimum_history=50,
        )

    with pytest.raises(ValueError, match="inteiros entre 0 e 36"):
        probability_backtest_service.run_probability_backtest_from_history(
            [1] * 100 + [99],
            roulette_id="test-roulette",
            minimum_history=50,
        )

    with pytest.raises(ValueError, match="initial_bankroll"):
        probability_backtest_service.run_probability_backtest_from_history(
            [1] * 100,
            roulette_id="test-roulette",
            minimum_history=50,
            initial_bankroll=0,
        )
