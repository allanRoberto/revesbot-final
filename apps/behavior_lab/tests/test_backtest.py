from __future__ import annotations

from behavior_lab.config import BehaviorLabConfig
from behavior_lab.facade import run_backtest


def _events(values):
    return [
        {
            "roulette_id": "pragmatic-auto-roulette",
            "value": value,
            "external_game_id": f"game-{index}",
        }
        for index, value in enumerate(values)
    ]


def test_backtest_is_causal_when_future_changes() -> None:
    prefix = [26, 36, 2, 34, 5, *([8] * 9), 26, 36, 10]
    first = run_backtest(_events(prefix + [20]), config=BehaviorLabConfig(exhaustion_window=5))
    second = run_backtest(_events(prefix + [35]), config=BehaviorLabConfig(exhaustion_window=5))
    assert first["decisions"][:-1] == second["decisions"][:-1]
    activation = next(signal for signal in first["signals"] if signal["rule"] == "exact_pair_continuation")
    assert activation["activated_at_index"] == 15
    assert first["decisions"][15]["suggestion"] == []
    assert first["decisions"][16]["suggestion"]


def test_newest_first_input_is_reversed_and_duplicates_use_identity_not_value() -> None:
    chronological = _events([1, 1, 2])
    report = run_backtest(list(reversed(chronological)), input_order="newest-first")
    assert [row["result"] for row in report["decisions"]] == [1, 1, 2]
    assert report["metrics"]["spins"]["accepted"] == 3
    assert report["metrics"]["spins"]["duplicate_events_ignored"] == 0


def test_same_event_retransmission_is_excluded_from_backtest() -> None:
    event = _events([14])[0]
    report = run_backtest([event, event])
    assert report["metrics"]["spins"]["accepted"] == 1
    assert report["metrics"]["spins"]["duplicate_events_ignored"] == 1


def test_report_exposes_coverage_baseline_and_flat_stake_metrics() -> None:
    values = [26, 36, 2, 34, 5, *([8] * 9), 26, 36, 2, 9, 10]
    report = run_backtest(_events(values), config=BehaviorLabConfig(exhaustion_window=5))
    decision_metrics = report["metrics"]["decisions"]
    signal_metrics = report["metrics"]["signals"]
    assert decision_metrics["bets"] >= 1
    assert decision_metrics["random_expected_hits_same_coverage"] > 0
    assert signal_metrics["random_expected_wins_same_coverage_horizon"] > 0
    assert 0 < signal_metrics["random_expected_win_rate_same_coverage_horizon"] <= 1
    assert "max_loss_streak" in report["metrics"]["flat_stake"]
    assert report["causal"] is True


def test_final_snapshot_uses_the_same_full_sample_metrics() -> None:
    report = run_backtest(_events([index % 37 for index in range(800)]))
    assert report["metrics"]["decisions"]["total"] == 800
    assert report["final_snapshot"]["metrics"] == report["metrics"]
