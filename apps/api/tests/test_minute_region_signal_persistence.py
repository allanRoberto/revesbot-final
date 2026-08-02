from datetime import datetime, timedelta, timezone

from api.services.minute_region_signal_persistence import (
    analyze_center_persistence,
    center_region,
    suggested_centers,
)


BASE_TIME = datetime(2026, 8, 2, 15, 3, tzinfo=timezone.utc)


def _attempt(number, *, minute, attempt=1, history_id=None):
    timestamp = BASE_TIME + timedelta(minutes=minute, seconds=20 + attempt)
    return {
        "attempt_number": attempt,
        "result_history_id": history_id or f"result-{minute}-{attempt}-{number}",
        "value": number,
        "timestamp_utc": timestamp,
        "formatted": timestamp.strftime("%d/%m/%Y %H:%M:%S"),
    }


def _signal(
    minute,
    *,
    centers=(3,),
    alternative_center=None,
    attempts=(),
):
    signal_time = BASE_TIME + timedelta(minutes=minute)
    alternative_analysis = {}
    if alternative_center is not None:
        alternative_analysis["alternative_center"] = {"value": alternative_center}
    return {
        "signal_minute_utc": signal_time,
        "generated_at_utc": signal_time,
        "alternative_analysis": alternative_analysis,
        "selected_centers": [{"value": center} for center in centers],
        "attempts": list(attempts),
    }


def test_center_region_uses_real_wheel_neighbors_on_each_side():
    assert center_region(3, neighbors=2) == [3, 12, 35, 26, 0]
    assert center_region(3, neighbors=0) == [3]


def test_third_center_suggestion_measures_hit_inside_center_region():
    signals = [
        _signal(0, attempts=[_attempt(5, minute=0)]),
        _signal(1, attempts=[_attempt(7, minute=1)]),
        _signal(
            2,
            attempts=[
                _attempt(11, minute=2, attempt=1),
                _attempt(26, minute=2, attempt=2),
                _attempt(8, minute=2, attempt=3),
            ],
        ),
    ]

    result = analyze_center_persistence(
        signals,
        min_repetitions=3,
        max_repetitions=3,
        attempt_horizon=3,
        center_neighbors=2,
    )

    threshold = result["thresholds"][2]
    trigger = result["recent_triggers"][0]
    assert threshold["triggers"] == 1
    assert threshold["accuracy"] == 100.0
    assert threshold["average_hit_attempt"] == 2.0
    assert trigger["center"] == 3
    assert trigger["region_values"] == [3, 12, 35, 26, 0]
    assert trigger["first_hit_attempt"] == 2


def test_exact_center_does_not_hit_neighbor_when_neighbors_are_zero():
    result = analyze_center_persistence(
        [_signal(0, attempts=[_attempt(26, minute=0)])],
        min_repetitions=1,
        max_repetitions=1,
        attempt_horizon=1,
        center_neighbors=0,
    )

    assert result["thresholds"][0]["accuracy"] == 0.0
    assert result["recent_triggers"][0]["outcome"] == "miss"


def test_region_payment_before_threshold_resets_center_sequence():
    signals = [
        _signal(0, attempts=[_attempt(35, minute=0)]),
        _signal(1, attempts=[_attempt(5, minute=1)]),
        _signal(2, attempts=[_attempt(7, minute=2)]),
    ]

    result = analyze_center_persistence(
        signals,
        min_repetitions=3,
        max_repetitions=3,
        attempt_horizon=1,
        center_neighbors=2,
    )

    assert result["thresholds"][2]["triggers"] == 0
    assert result["recent_triggers"] == []


def test_alternative_center_is_optional_and_counted_once_per_minute():
    signal = _signal(0, centers=(3, 16), alternative_center=3)
    official, official_centers, alternative_centers = suggested_centers(
        signal,
        include_alternative=False,
    )
    combined, combined_official, combined_alternative = suggested_centers(
        signal,
        include_alternative=True,
    )

    assert official == {3, 16}
    assert official_centers == {3, 16}
    assert alternative_centers == set()
    assert combined == {3, 16}
    assert combined_official == {3, 16}
    assert combined_alternative == {3}

    result = analyze_center_persistence(
        [
            _signal(0, centers=(16,), alternative_center=3),
            _signal(1, centers=(16,), alternative_center=3),
        ],
        min_repetitions=2,
        max_repetitions=2,
        attempt_horizon=1,
        center_neighbors=1,
        include_alternative=True,
    )
    center_triggers = [
        item for item in result["recent_triggers"] if item["center"] == 3
    ]
    assert len(center_triggers) == 1
    assert center_triggers[0]["source"] == "alternative"


def test_pending_center_triggers_do_not_enter_accuracy_denominator():
    signals = [
        _signal(0, attempts=[_attempt(5, minute=0)]),
        _signal(
            3,
            attempts=[
                _attempt(5, minute=3, attempt=1),
                _attempt(7, minute=3, attempt=2),
            ],
        ),
    ]

    result = analyze_center_persistence(
        signals,
        min_repetitions=1,
        max_repetitions=1,
        max_gap_minutes=1,
        attempt_horizon=2,
        center_neighbors=0,
    )

    row = result["thresholds"][0]
    assert row["triggers"] == 2
    assert row["evaluated"] == 1
    assert row["pending"] == 1
    assert row["misses"] == 1


def test_attempt_accuracy_shows_exact_and_cumulative_center_hits():
    signals = [
        _signal(0, attempts=[_attempt(3, minute=0, attempt=1)]),
        _signal(
            3,
            attempts=[
                _attempt(5, minute=3, attempt=1),
                _attempt(3, minute=3, attempt=2),
            ],
        ),
    ]

    result = analyze_center_persistence(
        signals,
        min_repetitions=1,
        max_repetitions=1,
        max_gap_minutes=1,
        attempt_horizon=2,
        center_neighbors=0,
    )

    row = result["thresholds"][0]
    assert row["evaluated"] == 2
    assert row["hits"] == 2
    assert row["attempt_accuracy"] == [
        {
            "attempt": 1,
            "hits": 1,
            "accuracy": 50.0,
            "cumulative_hits": 1,
            "cumulative_accuracy": 50.0,
        },
        {
            "attempt": 2,
            "hits": 1,
            "accuracy": 50.0,
            "cumulative_hits": 2,
            "cumulative_accuracy": 100.0,
        },
    ]


def test_maximum_gap_controls_center_suggestion_run():
    signals = [_signal(0), _signal(2)]

    consecutive = analyze_center_persistence(
        signals,
        min_repetitions=2,
        max_repetitions=2,
        max_gap_minutes=1,
        attempt_horizon=1,
    )
    allowing_gap = analyze_center_persistence(
        signals,
        min_repetitions=2,
        max_repetitions=2,
        max_gap_minutes=2,
        attempt_horizon=1,
    )

    assert consecutive["thresholds"][1]["triggers"] == 0
    assert allowing_gap["thresholds"][1]["triggers"] == 1


def test_continuing_center_run_does_not_create_overlapping_entries():
    result = analyze_center_persistence(
        [_signal(minute) for minute in range(5)],
        min_repetitions=3,
        max_repetitions=3,
        max_gap_minutes=1,
        attempt_horizon=1,
    )

    assert result["thresholds"][2]["triggers"] == 1
    assert len(result["recent_triggers"]) == 1
    assert result["active_centers"][0]["center"] == 3
    assert result["active_centers"][0]["repetitions"] == 5


def test_lift_compares_center_threshold_with_first_suggestion():
    signals = [
        _signal(0, attempts=[_attempt(5, minute=0)]),
        _signal(1, attempts=[_attempt(3, minute=1)]),
    ]

    result = analyze_center_persistence(
        signals,
        min_repetitions=2,
        max_repetitions=2,
        attempt_horizon=1,
        center_neighbors=0,
    )

    first, second = result["thresholds"]
    assert first["accuracy"] == 0.0
    assert second["accuracy"] == 100.0
    assert second["lift_vs_first"] == 100.0
