from datetime import datetime, timedelta, timezone

import pytest

from shared.python.roulette.orbit.performance import build_performance_summary


def _trial(
    anchor: datetime,
    *,
    top9: int | None,
    top12: int | None,
) -> dict:
    return {
        "status": "resolved",
        "attempts_observed": 10,
        "anchor_timestamp_utc": anchor,
        "top9_first_hit_attempt": top9,
        "top12_first_hit_attempt": top12,
    }


def test_performance_curves_are_cumulative_and_filtered_by_time():
    now = datetime(2026, 7, 20, 18, 0, tzinfo=timezone.utc)
    trials = [
        _trial(now - timedelta(minutes=20), top9=1, top12=1),
        _trial(now - timedelta(hours=2), top9=2, top12=1),
        _trial(now - timedelta(hours=5), top9=None, top12=3),
        _trial(now - timedelta(hours=26), top9=5, top12=None),
    ]

    summary = build_performance_summary(trials, now=now)

    assert summary["windows"]["1h"]["sample_size"] == 1
    assert summary["windows"]["3h"]["sample_size"] == 2
    assert summary["windows"]["24h"]["sample_size"] == 3
    assert summary["windows"]["all"]["sample_size"] == 4
    top9 = summary["windows"]["all"]["top9"]["attempts"]
    assert top9[0]["hit_rate"] == pytest.approx(0.25)
    assert top9[1]["hit_rate"] == pytest.approx(0.50)
    assert top9[4]["hit_rate"] == pytest.approx(0.75)
    assert [row["hit_rate"] for row in top9] == sorted(
        row["hit_rate"] for row in top9
    )


def test_best_hour_uses_brasilia_hour_and_marks_small_sample_provisional():
    anchors = [
        datetime(2026, 7, 20, 15, minute, tzinfo=timezone.utc)
        for minute in range(4)
    ]
    trials = [_trial(anchor, top9=1, top12=1) for anchor in anchors]

    summary = build_performance_summary(trials, now=anchors[-1])

    best = summary["best_hour"]
    assert best is not None
    assert best["hour"] == 12
    assert best["label"] == "12:00–12:59"
    assert best["hit_rate"] == 1.0
    assert best["provisional"] is True


def test_incomplete_trials_do_not_enter_any_denominator():
    now = datetime.now(timezone.utc)
    summary = build_performance_summary(
        [
            {
                "status": "pending",
                "attempts_observed": 9,
                "anchor_timestamp_utc": now,
                "top9_first_hit_attempt": 1,
            }
        ],
        now=now,
    )

    assert summary["resolved_trials"] == 0
    assert summary["windows"]["all"]["top9"]["attempts"][0]["hit_rate"] == 0.0
