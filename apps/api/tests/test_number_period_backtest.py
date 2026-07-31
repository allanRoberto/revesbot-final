from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from api.services.number_period_backtest import build_intraday_backtest


TZ = ZoneInfo("America/Sao_Paulo")


def _item(timestamp, value):
    return {
        "value": value,
        "color": "black",
        "timestamp": timestamp.isoformat(),
        "formatted": timestamp.strftime("%d/%m/%Y %H:%M"),
        "time": timestamp.strftime("%H:%M"),
        "diff_label": "0 min",
    }


def _training_items(start, days):
    source = {}
    for day_offset in range(1, days + 1):
        day_start = start - timedelta(days=day_offset)
        source[day_offset] = [
            _item(day_start + timedelta(minutes=minute), 24)
            for minute in range(10)
        ]
    return source


def test_period_reserves_five_attempts_and_skips_overlapping_minutes():
    start = datetime(2026, 7, 30, 11, 40, tzinfo=TZ)
    days = _training_items(start, 2)
    days[0] = [
        _item(start + timedelta(seconds=0), 2),
        _item(start + timedelta(seconds=40), 3),
        _item(start + timedelta(seconds=80), 4),
        _item(start + timedelta(seconds=120), 5),
        _item(start + timedelta(seconds=160), 24),
        _item(start + timedelta(minutes=4), 24),
    ]

    result = build_intraday_backtest(
        days,
        start_timestamp=start,
        period_minutes=5,
        training_days=2,
        window_minutes=0,
        analysis_neighbors=0,
        bet_neighbors=0,
        centers_count=1,
        attempts_limit=5,
    )

    assert [item["status"] for item in result["timeline"]] == [
        "hit",
        "skipped_overlap",
        "skipped_overlap",
        "skipped_overlap",
        "hit",
    ]
    assert result["timeline"][0]["hit_attempt"] == 5
    assert result["timeline"][4]["hit_attempt"] == 1
    assert result["metrics"]["minimum_spacing_minutes"] == 4
    assert result["metrics"]["skipped_overlap"] == 3


def test_period_extends_block_when_real_fifth_spin_is_slower():
    start = datetime(2026, 7, 30, 11, 40, tzinfo=TZ)
    days = _training_items(start, 2)
    days[0] = [
        _item(start + timedelta(minutes=0), 2),
        _item(start + timedelta(minutes=1), 3),
        _item(start + timedelta(minutes=2), 4),
        _item(start + timedelta(minutes=3), 5),
        _item(start + timedelta(minutes=4, seconds=10), 6),
        _item(start + timedelta(minutes=5), 24),
    ]

    result = build_intraday_backtest(
        days,
        start_timestamp=start,
        period_minutes=6,
        training_days=2,
        window_minutes=0,
        analysis_neighbors=0,
        bet_neighbors=0,
        centers_count=1,
        attempts_limit=5,
    )

    assert result["timeline"][4]["status"] == "skipped_overlap"
    assert result["timeline"][4]["blocked_until"]["time"] == "11:44:10"
    assert result["timeline"][5]["status"] == "hit"
    assert result["metrics"]["skipped_overlap"] == 4
