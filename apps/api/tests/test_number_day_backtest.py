from api.services.number_day_backtest import build_walk_forward_backtest


def _day(offset, training_values, outcome_values):
    return {
        "target": {
            "timestamp": f"2026-07-{31 - offset:02d}T19:56:00-03:00",
            "formatted": f"{31 - offset:02d}/07/2026 19:56",
            "time": "19:56",
        },
        "training_items": [
            {"value": value, "time": "19:56", "diff_label": "0 min"}
            for value in training_values
        ],
        "outcome_items": [
            {
                "value": value,
                "color": "black",
                "formatted": f"{31 - offset:02d}/07/2026 19:{56 + index:02d}",
                "time": f"19:{56 + index:02d}",
                "diff_label": f"+{index} min",
            }
            for index, value in enumerate(outcome_values)
        ],
    }


def test_walk_forward_uses_previous_days_and_hits_on_second_attempt():
    days = {
        1: _day(1, [36], [2, 16, 7]),
        2: _day(2, [24], [8, 9]),
        3: _day(3, [24], []),
        4: _day(4, [24], []),
        5: _day(5, [24], []),
    }

    result = build_walk_forward_backtest(
        days,
        training_days=3,
        test_days=2,
        analysis_neighbors=0,
        bet_neighbors=1,
        centers_count=1,
        attempts_limit=5,
    )

    newest_day = result["days"][0]
    assert newest_day["day_offset"] == 1
    assert newest_day["selected_centers"][0]["value"] == 24
    assert [item["value"] for item in newest_day["bet_numbers"]] == [5, 24, 16]
    assert newest_day["status"] == "hit"
    assert newest_day["hit_attempt"] == 2
    assert newest_day["attempts_used"] == 2
    assert newest_day["profit_units"] == 30.0


def test_walk_forward_combines_regions_from_multiple_centers():
    days = {
        1: _day(1, [], [16]),
        2: _day(2, [24, 16], []),
        3: _day(3, [24, 16], []),
    }

    result = build_walk_forward_backtest(
        days,
        training_days=2,
        test_days=1,
        analysis_neighbors=0,
        bet_neighbors=1,
        centers_count=2,
        attempts_limit=1,
    )

    day = result["days"][0]
    assert [center["value"] for center in day["selected_centers"]] == [16, 24]
    assert day["coverage"] == 4
    assert day["status"] == "hit"
