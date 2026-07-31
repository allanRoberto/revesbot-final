from datetime import datetime, timedelta, timezone

from apps.monitoring.src.minute_region_signal_runtime import (
    apply_result_to_signal,
    build_signal_document,
    region_numbers,
)


def _history_result(index: int, value: int):
    timestamp = datetime(2026, 7, 30, 15, 0, tzinfo=timezone.utc) + timedelta(seconds=40 * index)
    return {
        "history_id": f"result-{index}",
        "value": value,
        "timestamp_utc": timestamp,
        "timestamp_br": timestamp,
        "formatted": timestamp.strftime("%d/%m/%Y %H:%M:%S"),
    }


def _signal(previous_values=(16, 8, 9, 10, 11)):
    now = datetime(2026, 7, 30, 15, 0, tzinfo=timezone.utc)
    training = [
        {"day_offset": day, "items": [{"value": 16}, {"value": 24}]}
        for day in range(1, 11)
    ]
    previous = [_history_result(-index, value) for index, value in enumerate(previous_values, 1)]
    return build_signal_document(
        roulette_id="pragmatic-auto-roulette",
        signal_key="test-signal",
        signal_minute_utc=now,
        signal_minute_br=now,
        generated_at_utc=now,
        training_days_source=training,
        previous_results=previous,
        training_days=10,
        window_minutes=3,
        analysis_neighbors=3,
        centers_count=2,
        bet_neighbors=3,
        max_attempts=10,
        previous_results_count=5,
    )


def test_previous_region_hit_is_recorded_without_cancelling_signal():
    signal = _signal()

    assert signal["previous_region_hit"] is True
    assert signal["previous_region_hit_count"] >= 1
    assert signal["status"] == "active"
    assert signal["attempt_count"] == 0


def test_signal_continues_after_payment_and_counts_all_ten_attempts():
    signal = _signal()
    paid_value = signal["bet_values"][0]
    missed_values = [value for value in range(37) if value not in set(signal["bet_values"])]

    values = [paid_value, missed_values[0], paid_value, *missed_values[1:8]]
    assert len(values) == 10
    for index, value in enumerate(values, 1):
        signal = apply_result_to_signal(signal, _history_result(index, value))
        if index < 10:
            assert signal["status"] == "active"

    assert signal["status"] == "completed"
    assert signal["attempt_count"] == 10
    assert signal["payment_count"] == 2
    assert [item["attempt_number"] for item in signal["attempts"]] == list(range(1, 11))


def test_duplicate_result_is_idempotent():
    signal = _signal()
    result = _history_result(1, signal["bet_values"][0])

    first = apply_result_to_signal(signal, result)
    second = apply_result_to_signal(first, result)

    assert second["attempt_count"] == 1
    assert second["payment_count"] == 1


def test_overlapping_signals_receive_same_result_independently():
    first = _signal()
    second = {**_signal(), "signal_key": "test-signal-2"}
    result = _history_result(1, first["bet_values"][0])

    first = apply_result_to_signal(first, result)
    second = apply_result_to_signal(second, result)

    assert first["attempt_count"] == 1
    assert second["attempt_count"] == 1
    assert first["attempts"][0]["result_history_id"] == second["attempts"][0]["result_history_id"]


def test_region_uses_real_roulette_wheel_order():
    assert region_numbers(0, 3) == [35, 3, 26, 0, 32, 15, 19]
