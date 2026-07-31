from api.services.number_live_signal import build_live_signal


def _training_days(value=24, days=3):
    return [
        {
            "day_offset": day_offset,
            "items": [{"value": value, "time": "11:40", "diff_seconds": 0}],
        }
        for day_offset in range(1, days + 1)
    ]


def _recent(value, seconds_ago):
    return {
        "value": value,
        "color": "black",
        "time": "11:40",
        "formatted": "30/07/2026 11:40",
        "diff_seconds": -seconds_ago,
        "diff_label": "0 min",
    }


def _build(recent_items):
    return build_live_signal(
        _training_days(),
        recent_items,
        training_days=3,
        analysis_neighbors=0,
        bet_neighbors=0,
        centers_count=1,
        blocking_minutes=5,
        stale_after_minutes=3,
    )


def test_live_signal_releases_entry_when_region_was_not_recently_paid():
    result = _build([_recent(7, 20)])

    assert result["status"] == "enter"
    assert result["selected_centers"][0]["value"] == 24
    assert [item["value"] for item in result["bet_numbers"]] == [24]
    assert result["paid_matches"] == []


def test_live_signal_cancels_entry_when_region_was_recently_paid():
    result = _build([_recent(24, 50), _recent(7, 10)])

    assert result["status"] == "cancel"
    assert result["paid_matches"][0]["value"] == 24
    assert "número 24" in result["reason"]


def test_live_signal_waits_when_current_feed_is_stale():
    result = _build([])

    assert result["status"] == "wait"
    assert result["feed_is_stale"] is True
