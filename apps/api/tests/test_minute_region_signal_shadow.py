from datetime import datetime, timedelta, timezone

from api.services.minute_region_signal_shadow import analyze_g5_shadow_signals


BASE_TIME = datetime(2026, 8, 2, 20, 0, tzinfo=timezone.utc)


def _attempt(value, number):
    timestamp = BASE_TIME + timedelta(minutes=number)
    return {
        "attempt_number": number,
        "value": value,
        "timestamp_utc": timestamp,
        "formatted": timestamp.strftime("%d/%m/%Y %H:%M:%S"),
    }


def _signal(minute, candidate_values=None, attempts=()):
    timestamp = BASE_TIME + timedelta(minutes=minute)
    signal = {
        "signal_key": f"signal-{minute}",
        "signal_minute_utc": timestamp,
        "signal_minute_br": timestamp,
        "bet_values": [1],
        "alternative_analysis": {"alternative_bet_values": [2]},
        "selected_centers": [{"value": 1}, {"value": 5}],
        "attempt_count": len(attempts),
        "attempts": list(attempts),
    }
    if candidate_values is not None:
        signal["shadow_scenarios"] = {
            "g5_n4_v1": {
                "attempt_horizon": 5,
                "selected_centers": [{"value": 1}, {"value": 5}],
                "effective_bet_values": list(candidate_values),
                "effective_coverage": len(set(candidate_values)),
                "coverage": len(set(candidate_values)),
                "alternative_analysis": {"alternative_center": {"value": 20}},
            }
        }
    return signal


def test_shadow_compares_g5_exact_and_cumulative_attempt_accuracy():
    signals = [
        _signal(
            0,
            candidate_values=[3, 4],
            attempts=[
                _attempt(3, 1),
                _attempt(8, 2),
                _attempt(9, 3),
                _attempt(10, 4),
                _attempt(11, 5),
            ],
        ),
        _signal(
            1,
            candidate_values=[3, 4],
            attempts=[
                _attempt(8, 1),
                _attempt(9, 2),
                _attempt(10, 3),
                _attempt(11, 4),
                _attempt(4, 5),
            ],
        ),
    ]

    result = analyze_g5_shadow_signals(signals)

    assert result["scenario_signals"] == 2
    assert result["retention"] == 100.0
    assert result["candidate"]["evaluated"] == 2
    assert result["candidate"]["accuracy"] == 100.0
    assert result["candidate"]["attempt_accuracy"][0] == {
        "attempt": 1,
        "hits": 1,
        "accuracy": 50.0,
        "cumulative_hits": 1,
        "cumulative_accuracy": 50.0,
    }
    assert result["candidate"]["attempt_accuracy"][4] == {
        "attempt": 5,
        "hits": 1,
        "accuracy": 50.0,
        "cumulative_hits": 2,
        "cumulative_accuracy": 100.0,
    }
    assert result["baseline"]["accuracy"] == 0.0


def test_shadow_retention_counts_missing_scenarios_after_collection_started():
    signals = [
        _signal(-1),
        _signal(0, candidate_values=[3], attempts=[_attempt(8, index) for index in range(1, 6)]),
        _signal(1),
        _signal(2, candidate_values=[3], attempts=[_attempt(3, index) for index in range(1, 6)]),
    ]

    result = analyze_g5_shadow_signals(signals)

    assert result["cohort_signals"] == 3
    assert result["scenario_signals"] == 2
    assert result["retention"] == 66.67


def test_pending_shadow_signal_is_excluded_from_accuracy_denominator():
    result = analyze_g5_shadow_signals(
        [
            _signal(
                0,
                candidate_values=[3],
                attempts=[_attempt(3, 1), _attempt(8, 2), _attempt(9, 3)],
            )
        ]
    )

    assert result["candidate"]["signals"] == 1
    assert result["candidate"]["evaluated"] == 0
    assert result["candidate"]["pending"] == 1
    assert result["candidate"]["accuracy"] == 0.0
    assert result["recent_signals"][0]["candidate"]["observed_first_hit_attempt"] == 1
    assert result["gate"]["status"] == "collecting"
