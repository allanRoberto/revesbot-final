from __future__ import annotations

from api.services.occurrence_ranking import (
    build_occurrence_snapshot,
    build_occurrence_ranking,
    run_occurrence_replay,
)


def test_build_occurrence_ranking_matches_tooltip_top_pulled_order() -> None:
    result = build_occurrence_ranking(
        [5, 8, 7, 5, 9, 8, 5, 7],
        focus_number=5,
        from_index=0,
        history_limit=50,
        window_before=1,
        window_after=1,
        ranking_size=5,
    )

    assert result["available"] is True
    assert result["occurrences"] == [0, 3, 6]
    assert result["occurrence_count"] == 3
    assert result["pulled_total"] == 5
    assert result["ranking"] == [7, 8, 9]
    assert result["ranking_details"] == [
        {"number": 7, "count": 2},
        {"number": 8, "count": 2},
        {"number": 9, "count": 1},
    ]


def test_occurrence_snapshot_counts_all_hits_within_attempt_window() -> None:
    snapshot = build_occurrence_snapshot(
        [7, 4, 8, 3, 4, 3, 7, 3, 4],
        focus_number=3,
        from_index=3,
        history_limit=50,
        window_before=1,
        window_after=1,
        ranking_size=2,
        attempts_window=3,
    )

    evaluation = snapshot["evaluation"]
    assert snapshot["ranking"] == [4, 7]
    assert evaluation["status"] == "resolved"
    assert evaluation["future_numbers"] == [8, 4, 7]
    assert evaluation["hit_count"] == 2
    assert evaluation["hit_attempts"] == [2, 3]
    assert evaluation["first_hit_attempt"] == 2
    assert evaluation["summary"] == "2/3 acertos"


def test_occurrence_snapshot_cancels_when_ranking_hits_before_trigger() -> None:
    snapshot = build_occurrence_snapshot(
        [7, 4, 8, 3, 4, 7, 3, 4],
        focus_number=3,
        from_index=3,
        history_limit=50,
        window_before=1,
        window_after=1,
        ranking_size=2,
        attempts_window=3,
        invert_check_window=2,
    )

    assert snapshot["ranking"] == [4, 7]
    assert snapshot["counted"] is False
    assert snapshot["cancelled_reason"] == "inverted_hit"
    assert snapshot["evaluation"]["status"] == "cancelled_inverted"
    assert snapshot["evaluation"]["hit_count"] == 0
    assert snapshot["evaluation"]["future_numbers"] == []
    assert snapshot["inverted_evaluation"]["cancelled"] is True
    assert snapshot["inverted_evaluation"]["hit_offsets"] == [1, 2]
    assert snapshot["inverted_evaluation"]["hit_numbers"] == [4, 7]


def test_replay_limits_to_latest_eligible_entries_and_aggregates_hits() -> None:
    result = run_occurrence_replay(
        roulette_id="test-roulette",
        history_desc=[8, 1, 8, 1, 8, 1, 8, 1],
        history_limit=50,
        entries_limit=2,
        window_before=1,
        window_after=1,
        ranking_size=1,
        attempts_window=2,
    )

    assert result["available"] is True
    assert result["entries_analyzed"] == 2
    assert result["eligible_entries"] == 6
    assert [event["from_index"] for event in result["events"]] == [2, 3]
    assert [event["anchor_number"] for event in result["events"]] == [8, 1]
    assert result["events"][0]["ranking"] == [1]
    assert result["events"][1]["ranking"] == [8]
    assert result["total_hits"] == 2
    assert result["total_attempts"] == 4
    assert result["events_with_hits"] == 2
    assert result["aggregate_hit_rate"] == 0.5


def test_replay_excludes_cancelled_inverted_events_from_metrics() -> None:
    result = run_occurrence_replay(
        roulette_id="test-roulette",
        history_desc=[8, 1, 8, 1, 8, 1, 8, 1],
        history_limit=50,
        entries_limit=2,
        window_before=1,
        window_after=1,
        ranking_size=1,
        attempts_window=2,
        invert_check_window=1,
    )

    assert result["available"] is True
    assert result["entries_processed"] == 2
    assert result["entries_analyzed"] == 0
    assert result["cancelled_inverted_events"] == 2
    assert result["total_hits"] == 0
    assert result["total_attempts"] == 0
    assert result["events_with_hits"] == 0
    assert [event["status"] for event in result["events"]] == ["cancelled_inverted", "cancelled_inverted"]
    assert all(event["counted"] is False for event in result["events"])
