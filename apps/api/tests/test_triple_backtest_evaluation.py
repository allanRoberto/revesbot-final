from copy import deepcopy

import pytest

from api.services.triple_backtest_evaluation import evaluate_signals


def _rows(values):
    return [{"value": value, "timestamp": f"2026-09-22T00:00:{i % 60:02d}+00:00",
             "source_id": "table"} for i, value in enumerate(values)]


def test_edge_win_incomplete_and_loss_with_later_recovery():
    win = evaluate_signals(_rows([0, 7, 9]),
                           [{"end_index": 0, "selected_numbers": [4, 9]}], 3)
    assert win["signals"][0] == {
        "end_index": 0, "selected_numbers": [4, 9], "status": "win",
        "available_attempts": 2, "checked_numbers": [7, 9],
        "first_hit_attempt": 2, "hit_number": 9, "hit_rank": 2,
        "recovery_extra_attempts": None, "followup_observed": None,
        "blocked_by_signal_id": None, "blocked_until_position": None}
    assert win["summary"]["evaluated"] == 1

    incomplete = evaluate_signals(_rows([0, 7, 3]),
        [{"end_index": 0, "selected_numbers": [4, 9]}], 3)
    assert incomplete["signals"][0]["status"] == "incomplete"
    assert incomplete["summary"]["accuracy_pct"] is None

    loss = evaluate_signals(_rows([0, 7, 3, 12, 8, 9]),
        [{"end_index": 0, "selected_numbers": [4, 9]}], 3)
    row = loss["signals"][0]
    assert (row["status"], row["first_hit_attempt"], row["recovery_extra_attempts"],
            row["followup_observed"]) == ("loss", 5, 2, 2)
    assert loss["summary"]["recovery_attempts"] == [
        {"attempt": 5, "extra_attempts": 2, "count": 1}]


def test_attempt_one_T_and_T_plus_one_and_frozen_selections():
    rows = _rows([0, 7, 8, 9, 4, 1])
    selections = [[7, 4], [9, 20], [4, 20]]
    signals = [{"end_index": 0, "selected_numbers": selected,
                "metadata": {"name": str(i)}} for i, selected in enumerate(selections)]
    original = deepcopy(signals)
    result = evaluate_signals(rows, signals, 3)
    assert signals == original
    assert [(row["status"], row["first_hit_attempt"], row["hit_rank"])
            for row in result["signals"]] == [
        ("win", 1, 1), ("win", 3, 1), ("loss", 4, 1)]
    assert [row["selected_numbers"] for row in result["signals"]] == selections
    assert result["summary"]["win_attempts"] == [
        {"attempt": 1, "count": 1}, {"attempt": 2, "count": 0},
        {"attempt": 3, "count": 1}]
    assert result["summary"]["accuracy_pct"] == pytest.approx(200 / 3)


def test_top37_no_hit_multiple_signals_and_denominator():
    result = evaluate_signals(_rows([0, 1, 2, 3, 4, 5, 6, 7]), [
        {"end_index": 0, "selected_numbers": list(reversed(range(37)))},
        {"end_index": 1, "selected_numbers": [36]},
        {"end_index": 6, "selected_numbers": [35]},
    ], 3)
    first = result["signals"][0]
    assert (first["status"], first["first_hit_attempt"], first["hit_number"],
            first["hit_rank"]) == ("win", 1, 1, 36)
    assert result["signals"][1]["status"] == "loss"
    assert result["signals"][1]["first_hit_attempt"] is None
    assert result["signals"][1]["followup_observed"] == 3
    assert result["signals"][2]["status"] == "incomplete"
    assert result["summary"]["unresolved_losses"] == 1
    assert result["summary"]["max_recovery_attempt"] is None
    assert result["summary"]["evaluated"] == 2


def test_skips_preserve_metadata_and_stay_out_of_denominator():
    result = evaluate_signals(_rows([0, 1, 2, 3]), [
        {"end_index": 0, "selected_numbers": [], "status": "repeated_trio", "trio": [3, 2, 1]},
        {"end_index": 1, "selected_numbers": [], "status": "no_evidence", "why": "zero"},
    ], 2)
    assert [row["status"] for row in result["signals"]] == ["repeated_trio", "no_evidence"]
    assert result["signals"][0]["trio"] == [3, 2, 1]
    assert result["signals"][1]["why"] == "zero"
    assert result["summary"]["repeated_trio"] == result["summary"]["no_evidence"] == 1
    assert result["summary"]["evaluated"] == 0


def test_recovery_histogram_does_not_reclassify_losses():
    result = evaluate_signals(_rows([0, 8, 8, 8, 7, 9, 7, 1]), [
        {"end_index": 0, "selected_numbers": [7]},
        {"end_index": 1, "selected_numbers": [7]},
        {"end_index": 0, "selected_numbers": [1]},
    ], 3)
    assert [row["status"] for row in result["signals"]] == ["loss", "win", "loss"]
    assert result["summary"]["recovered_losses"] == 2
    assert result["summary"]["recovery_attempts"] == [
        {"attempt": 4, "extra_attempts": 1, "count": 1},
        {"attempt": 7, "extra_attempts": 4, "count": 1}]
    assert result["summary"]["max_recovery_attempt"] == 7


def test_non_overlapping_mode_skips_signals_until_the_active_win_finishes():
    result = evaluate_signals(_rows([0, 1, 2, 3, 9, 8, 7]), [
        {"signal_id": 1, "end_index": 0, "selected_numbers": [9]},
        {"signal_id": 2, "end_index": 3, "selected_numbers": [8]},
        {"signal_id": 3, "end_index": 4, "selected_numbers": [8]},
    ], 5, True)

    assert [signal["status"] for signal in result["signals"]] == [
        "win", "overlap_skipped", "win"]
    blocked = result["signals"][1]
    assert blocked["checked_numbers"] == []
    assert blocked["available_attempts"] == 0
    assert blocked["blocked_by_signal_id"] == 1
    assert blocked["blocked_until_position"] == 5
    assert result["summary"]["overlap_skipped"] == 1
    assert result["summary"]["wins"] == result["summary"]["evaluated"] == 2


def test_non_overlapping_mode_allows_signal_formed_on_the_last_loss_attempt():
    result = evaluate_signals(_rows([0, 1, 2, 3, 8]), [
        {"signal_id": 1, "end_index": 0, "selected_numbers": [36]},
        {"signal_id": 2, "end_index": 3, "selected_numbers": [8]},
    ], 3, True)

    assert [signal["status"] for signal in result["signals"]] == ["loss", "win"]
    assert result["summary"]["overlap_skipped"] == 0


@pytest.mark.parametrize("rows,signals,attempts,error", [
    (_rows([0]), [], 0, "attempts"),
    (_rows([0]), [{"end_index": True, "selected_numbers": [1]}], 1, "end_index"),
    (_rows([0]), [{"end_index": 1, "selected_numbers": [1]}], 1, "end_index"),
    (_rows([0]), [{"end_index": 0, "selected_numbers": []}], 1, "selected_numbers"),
    (_rows([0]), [{"end_index": 0, "selected_numbers": [1, 1]}], 1, "selected_numbers"),
    (_rows([0]), [{"end_index": 0, "selected_numbers": [37]}], 1, "selected_numbers"),
    (_rows([0]), [{"end_index": 0, "selected_numbers": [1], "status": "win"}], 1, "status"),
    ([{"value": True, "timestamp": "t", "source_id": "s"}], [], 1, "value"),
])
def test_invalid_internal_inputs_fail_clearly(rows, signals, attempts, error):
    with pytest.raises((TypeError, ValueError), match=error):
        evaluate_signals(rows, signals, attempts)


def test_non_overlapping_flag_is_strict_boolean():
    with pytest.raises(TypeError, match="prevent_overlapping_bets"):
        evaluate_signals(_rows([0, 1]), [], 1, 1)


def test_many_signals_use_compact_checked_windows():
    rows = _rows([index % 37 for index in range(10_000)])
    signals = [{"end_index": index, "selected_numbers": [36, 17, 4, 29, 0]}
               for index in range(0, 8_000, 4)]
    result = evaluate_signals(rows, signals, 3)
    assert result["summary"]["total_signals"] == len(result["signals"]) == 2_000
    assert all(len(row["checked_numbers"]) <= 3 for row in result["signals"])
