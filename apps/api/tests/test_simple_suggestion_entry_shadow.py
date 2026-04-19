from __future__ import annotations

from api.services.simple_suggestion_entry_shadow import simple_suggestion_entry_shadow


def _build_simple_payload() -> dict:
    suggestion = list(range(24))
    selected_details = []
    for index, number in enumerate(suggestion):
        support_score = 6 if index < 8 else (4 if index < 16 else 3)
        weighted_support_score = float(support_score) + (0.5 if index < 10 else 0.0)
        selected_details.append(
            {
                "number": number,
                "support_score": support_score,
                "weighted_support_score": weighted_support_score,
            }
        )
    return {
        "available": True,
        "list": suggestion,
        "selected_number_details": selected_details,
        "pattern_count": 18,
        "top_support_count": 6,
        "min_support_count": 3,
        "avg_support_count": 4.33,
        "top_weighted_support_score": 6.5,
        "min_weighted_support_score": 3.0,
        "avg_weighted_support_score": 4.54,
    }


def test_simple_suggestion_entry_shadow_exposes_economics_for_24_numbers() -> None:
    result = simple_suggestion_entry_shadow.evaluate(
        simple_payload=_build_simple_payload(),
        history=[36, 35, 34, 33, 32, 31, 30, 29],
        from_index=0,
        max_attempts=4,
    )

    assert result["available"] is True
    assert result["mode"] == "shadow"
    assert result["economics"]["profits_by_attempt"]["hit_1"] == 12
    assert result["economics"]["profits_by_attempt"]["hit_2"] == -12
    assert result["economics"]["profits_by_attempt"]["hit_3"] == -36
    assert result["economics"]["profits_by_attempt"]["hit_4"] == -60
    assert result["economics"]["miss_loss"] == -96
    probability_sum = sum(result["probabilities"].values())
    assert 0.999 <= probability_sum <= 1.001


def test_simple_suggestion_entry_shadow_penalizes_recent_pressure() -> None:
    payload = _build_simple_payload()
    low_pressure = simple_suggestion_entry_shadow.evaluate(
        simple_payload=payload,
        history=[36, 35, 34, 33, 32, 31, 30, 29],
        from_index=0,
        max_attempts=4,
    )
    high_pressure = simple_suggestion_entry_shadow.evaluate(
        simple_payload=payload,
        history=[5, 7, 9, 11, 13, 15, 17, 19],
        from_index=0,
        max_attempts=4,
    )

    assert high_pressure["features"]["pressure_index"] > low_pressure["features"]["pressure_index"]
    assert high_pressure["late_hit_risk"] > low_pressure["late_hit_risk"]
    assert high_pressure["expected_value"]["net_units"] < low_pressure["expected_value"]["net_units"]
    assert high_pressure["recommendation"]["action"] in {"wait", "skip"}


def test_simple_suggestion_entry_shadow_allows_enter_for_strong_24_number_context() -> None:
    payload = {
        "available": True,
        "list": list(range(24)),
        "selected_number_details": [
            {
                "number": index,
                "support_score": 8 if index < 6 else (6 if index < 12 else 4),
                "weighted_support_score": 8.5 if index < 6 else (6.5 if index < 12 else 4.5),
            }
            for index in range(24)
        ],
        "pattern_count": 18,
        "top_support_count": 8,
        "min_support_count": 4,
        "avg_support_count": 6,
        "top_weighted_support_score": 8.5,
        "min_weighted_support_score": 4.5,
        "avg_weighted_support_score": 6.5,
    }
    result = simple_suggestion_entry_shadow.evaluate(
        simple_payload=payload,
        history=[36, 35, 34, 33, 32, 31, 30, 29],
        from_index=0,
        max_attempts=4,
    )

    assert result["entry_confidence"]["score"] >= 75
    assert result["probabilities"]["hit_1"] >= 0.72
    assert result["late_hit_risk"] <= 0.28
    assert result["expected_value"]["net_units"] > 0
    assert result["recommendation"]["action"] == "enter"
