from datetime import datetime, timezone

import pytest

from api.services.orbit_performance_service import serialize_trial_history
from api.services.orbit_service import OrbitService


def test_orbit_service_returns_rankings_and_identified_occurrences():
    history = [index % 37 for index in range(400)]
    history.extend([32, 27, 13, 5, 31, 19])
    result = OrbitService().analyze_history(
        history,
        pivot=19,
        memory_occurrences=8,
        horizon=3,
    )
    assert result["available"] is True
    assert result["context"]["pivot"] == 19
    assert len(result["prediction"]["top9"]) == 9
    assert len(result["prediction"]["top12"]) == 12
    assert len(result["prediction"]["ranking"]) == 37
    probability = sum(row["probability"] for row in result["prediction"]["ranking"])
    assert probability == pytest.approx(1.0)
    current = result["context"]["occurrences"][0]
    assert all(row["relative_offset"] < 0 for row in current["observations"])
    assert all(row["identifier"].startswith("IOR:orbit-relations-v1") for row in current["observations"])


def test_orbit_service_exposes_consolidated_three_pivot_contract():
    history = [index % 37 for index in range(500)] + [35, 19, 7]

    result = OrbitService().analyze_multi_pivot_history(history)

    prediction = result["prediction"]
    assert result["available"] is True
    assert result["engine_version"] == "orbital_multi_pivot_v1"
    assert prediction["recent_pivots"] == [7, 19, 35]
    assert len(prediction["pivots"]) == 3
    assert [row["weight"] for row in prediction["pivots"]] == [1.0, 0.85, 0.70]
    assert len(prediction["top9"]) == 9
    assert prediction["top9"] == prediction["top12"][:9]
    assert len(prediction["ranking"]) == 37
    assert prediction["metadata"]["memory_occurrences_per_pivot"] == 6
    assert sum(row["probability"] for row in prediction["ranking"]) == pytest.approx(1.0)


def test_history_contract_marks_matches_and_first_hit_timestamps():
    first = datetime(2026, 7, 20, 18, 1, tzinfo=timezone.utc)
    second = datetime(2026, 7, 20, 18, 2, tzinfo=timezone.utc)
    result = serialize_trial_history(
        {
            "trial_id": "trial-1",
            "roulette_id": "roulette-1",
            "anchor_history_id": "anchor-1",
            "anchor_timestamp_utc": datetime(2026, 7, 20, 18, 0, tzinfo=timezone.utc),
            "recent_pivots": [19, 7, 35],
            "top9": [7, 8, 9],
            "top12": [7, 8, 9, 20],
            "attempt_numbers": [20, 7],
            "attempt_timestamps_utc": [first, second],
            "top9_first_hit_attempt": 2,
            "top12_first_hit_attempt": 1,
            "status": "pending",
            "max_attempts": 10,
        }
    )

    assert result["anchor_number"] == 19
    assert result["display_status"] == "top9_hit"
    assert result["attempts"][0]["top12_only_match"] is True
    assert result["attempts"][1]["top9_match"] is True
    assert result["top9_outcome"]["first_hit_attempt"] == 2
    assert result["top9_outcome"]["first_hit_timestamp_utc"] == second
    assert result["top12_outcome"]["first_hit_attempt"] == 1
