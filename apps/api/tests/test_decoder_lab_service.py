from __future__ import annotations

from datetime import datetime, timedelta

from api.services.decoder_lab import build_decoder_lab_analysis


def _rows_from_values(values: list[int]) -> list[dict]:
    start = datetime(2026, 3, 1, 0, 0, 0)
    rows = []
    for offset, value in enumerate(values):
        rows.append(
            {
                "value": value,
                "timestamp": start + timedelta(minutes=offset),
            }
        )
    return rows


def test_decoder_lab_uses_nearest_episodes_even_without_exact_state_match() -> None:
    rows = _rows_from_values(
        [
            7, 2, 9, 1, 20, 14, 31, 30, 6, 24, 5, 7,
            11, 4, 9, 1, 20, 14, 31, 30, 6, 18, 22, 8,
            13, 2, 33, 1, 20, 14, 31, 30, 22, 6, 12, 24,
            17, 5, 19, 7, 28, 12, 35, 3, 26, 0, 32, 15,
        ]
    )

    result = build_decoder_lab_analysis(
        rows,
        roulette_id="pragmatic-brazilian-roulette",
        state_numbers=[7, 9, 1, 20, 14, 31],
        future_horizon=5,
        ignore_last_occurrence=False,
        validation_ratio=0.25,
        min_support=2,
        top_k=8,
        episode_limit=20,
        similarity_threshold=0.45,
    )

    assert result["current_state"]["source"] == "manual"
    assert result["summary"]["matched_episodes"] >= 3
    assert result["suggestion"]["available"] is True
    assert 30 in result["suggestion"]["primary_numbers"]
    assert any(candidate["number"] == 6 for candidate in result["top_candidates"][:4])


def test_decoder_lab_uses_latest_history_when_manual_state_is_not_informed() -> None:
    rows = _rows_from_values(
        [
            7, 2, 9, 1, 20, 14, 31, 30, 6, 24, 5, 7,
            11, 4, 9, 1, 20, 14, 31, 30, 6, 18, 22, 8,
            13, 2, 33, 1, 20, 14, 31, 30, 22, 6, 12, 24,
            41 % 37, 7, 9, 1, 20, 14, 31,
        ]
    )

    result = build_decoder_lab_analysis(
        rows,
        roulette_id="test-roulette",
        state_window=6,
        future_horizon=5,
        ignore_last_occurrence=False,
        validation_ratio=0.25,
        min_support=1,
        top_k=6,
        episode_limit=15,
        similarity_threshold=0.40,
    )

    assert result["current_state"]["source"] == "latest_history"
    assert result["current_state"]["numbers"] == [7, 9, 1, 20, 14, 31]
    assert result["suggestion"]["available"] is True
    assert result["summary"]["total_episodes"] > 0
    assert result["horizon_rankings"]["5"]["candidates"]


def test_decoder_lab_falls_back_to_topn_when_threshold_finds_no_episode() -> None:
    rows = _rows_from_values([0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30])

    result = build_decoder_lab_analysis(
        rows,
        roulette_id="test-roulette",
        state_numbers=[7, 29, 18, 22, 9, 14],
        future_horizon=5,
        ignore_last_occurrence=False,
        validation_ratio=0.25,
        min_support=2,
        top_k=6,
        episode_limit=10,
        similarity_threshold=0.95,
    )

    assert result["summary"]["selection_mode"] == "fallback_topn"
    assert result["summary"]["matched_episodes"] == 3
    assert result["suggestion"]["available"] is True
