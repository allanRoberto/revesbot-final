from datetime import datetime, timedelta, timezone

from api.services.minute_region_signal_persistence import (
    analyze_number_persistence,
    suggestion_values,
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
    official=(0,),
    alternative=(),
    attempts=(),
):
    signal_time = BASE_TIME + timedelta(minutes=minute)
    return {
        "signal_minute_utc": signal_time,
        "generated_at_utc": signal_time,
        "bet_values": list(official),
        "alternative_analysis": {
            "alternative_bet_values": list(alternative),
        },
        "selected_centers": [{"value": 16}, {"value": 23}],
        "attempts": list(attempts),
    }


def test_third_consecutive_suggestion_creates_entry_and_measures_number_hit():
    signals = [
        _signal(0, attempts=[_attempt(5, minute=0)]),
        _signal(1, attempts=[_attempt(7, minute=1)]),
        _signal(
            2,
            attempts=[
                _attempt(11, minute=2, attempt=1),
                _attempt(0, minute=2, attempt=2),
                _attempt(8, minute=2, attempt=3),
            ],
        ),
    ]

    result = analyze_number_persistence(
        signals,
        min_repetitions=3,
        max_repetitions=3,
        attempt_horizon=3,
    )

    threshold = result["thresholds"][2]
    trigger = result["recent_triggers"][0]
    assert threshold["triggers"] == 1
    assert threshold["evaluated"] == 1
    assert threshold["accuracy"] == 100.0
    assert threshold["average_hit_attempt"] == 2.0
    assert trigger["number"] == 0
    assert trigger["first_hit_attempt"] == 2
    assert len(trigger["suggestions"]) == 3


def test_payment_before_threshold_resets_the_repetition_sequence():
    signals = [
        _signal(0, attempts=[_attempt(0, minute=0)]),
        _signal(1, attempts=[_attempt(5, minute=1)]),
        _signal(2, attempts=[_attempt(7, minute=2)]),
    ]

    result = analyze_number_persistence(
        signals,
        min_repetitions=3,
        max_repetitions=3,
        attempt_horizon=1,
    )

    assert result["thresholds"][2]["triggers"] == 0
    assert result["recent_triggers"] == []


def test_alternative_numbers_are_optional_and_count_only_once_per_minute():
    signal = _signal(0, official=(0, 1), alternative=(0, 2))
    official, official_values, alternative_values = suggestion_values(
        signal,
        include_alternative=False,
    )
    combined, _, _ = suggestion_values(signal, include_alternative=True)

    assert official == {0, 1}
    assert official_values == {0, 1}
    assert alternative_values == set()
    assert combined == {0, 1, 2}

    result = analyze_number_persistence(
        [_signal(0, official=(1,), alternative=(0,)), _signal(1, official=(1,), alternative=(0,))],
        min_repetitions=2,
        max_repetitions=2,
        attempt_horizon=1,
        include_alternative=True,
    )
    zero_triggers = [item for item in result["recent_triggers"] if item["number"] == 0]
    assert len(zero_triggers) == 1
    assert zero_triggers[0]["source"] == "alternative"


def test_pending_triggers_do_not_enter_accuracy_denominator():
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

    result = analyze_number_persistence(
        signals,
        min_repetitions=1,
        max_repetitions=1,
        max_gap_minutes=1,
        attempt_horizon=2,
    )

    row = result["thresholds"][0]
    assert row["triggers"] == 2
    assert row["evaluated"] == 1
    assert row["pending"] == 1
    assert row["misses"] == 1
    assert row["accuracy"] == 0.0


def test_maximum_gap_controls_whether_suggestions_belong_to_same_run():
    signals = [_signal(0), _signal(2)]

    consecutive = analyze_number_persistence(
        signals,
        min_repetitions=2,
        max_repetitions=2,
        max_gap_minutes=1,
        attempt_horizon=1,
    )
    allowing_gap = analyze_number_persistence(
        signals,
        min_repetitions=2,
        max_repetitions=2,
        max_gap_minutes=2,
        attempt_horizon=1,
    )

    assert consecutive["thresholds"][1]["triggers"] == 0
    assert allowing_gap["thresholds"][1]["triggers"] == 1


def test_continuing_same_run_does_not_create_overlapping_entries():
    result = analyze_number_persistence(
        [_signal(minute) for minute in range(5)],
        min_repetitions=3,
        max_repetitions=3,
        max_gap_minutes=1,
        attempt_horizon=1,
    )

    assert result["thresholds"][2]["triggers"] == 1
    assert len(result["recent_triggers"]) == 1
    assert result["active_numbers"][0]["repetitions"] == 5


def test_lift_compares_each_threshold_with_first_suggestion_baseline():
    signals = [
        _signal(0, attempts=[_attempt(5, minute=0)]),
        _signal(1, attempts=[_attempt(0, minute=1)]),
    ]

    result = analyze_number_persistence(
        signals,
        min_repetitions=2,
        max_repetitions=2,
        attempt_horizon=1,
    )

    first, second = result["thresholds"]
    assert first["accuracy"] == 0.0
    assert second["accuracy"] == 100.0
    assert second["lift_vs_first"] == 100.0
