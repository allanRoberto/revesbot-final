from __future__ import annotations

from datetime import datetime, timedelta

from api.services import ai_shadow


def _rows_from_values(values: list[int]) -> list[dict]:
    start = datetime(2026, 3, 1, 0, 0, 0)
    return [
        {"value": value, "timestamp": start + timedelta(minutes=index)}
        for index, value in enumerate(values)
    ]


def test_ai_shadow_analysis_returns_ranked_candidates(monkeypatch, tmp_path) -> None:
    store = ai_shadow.AIShadowProfileStore(
        storage_path=tmp_path / "profiles.json",
        feedback_log_path=tmp_path / "feedback.jsonl",
    )
    monkeypatch.setattr(ai_shadow, "_PROFILE_STORE", store)

    rows = _rows_from_values(
        [
            7, 2, 9, 1, 20, 14, 31, 30, 6, 24, 5, 7,
            11, 4, 9, 1, 20, 14, 31, 30, 6, 18, 22, 8,
            13, 2, 33, 1, 20, 14, 31, 30, 22, 6, 12, 24,
        ]
    )

    result = ai_shadow.build_ai_shadow_analysis(
        rows,
        roulette_id="pragmatic-brazilian-roulette",
        future_horizon=5,
        top_k=6,
        decoder_top_k=12,
        min_confidence=1,
        min_matched_episodes=1,
    )

    assert result["available"] is True
    assert result["summary"]["roulette_id"] == "pragmatic-brazilian-roulette"
    assert len(result["shadow_candidates"]) >= 6
    assert len(result["shadow_signal_candidate"]["numbers"]) == 6
    assert "profile" in result


def test_ai_shadow_feedback_updates_profile(monkeypatch, tmp_path) -> None:
    store = ai_shadow.AIShadowProfileStore(
        storage_path=tmp_path / "profiles.json",
        feedback_log_path=tmp_path / "feedback.jsonl",
    )
    monkeypatch.setattr(ai_shadow, "_PROFILE_STORE", store)

    profile = ai_shadow.apply_ai_shadow_feedback(
        roulette_id="pragmatic-brazilian-roulette",
        signal_id="shadow-1",
        feature_map={
            "30": {"decoder_score": 1.0, "decoder_rank": 1.0, "transition_rate": 0.5, "pending_pressure": 0.2, "wheel_neighbor": 1.0, "hotspot_proximity": 0.7, "recent_frequency": 0.1, "sleep_score": 0.9, "freshness": 1.0, "terminal_bias": 0.3},
            "6": {"decoder_score": 0.8, "decoder_rank": 0.9, "transition_rate": 0.2, "pending_pressure": 0.4, "wheel_neighbor": 0.0, "hotspot_proximity": 0.4, "recent_frequency": 0.2, "sleep_score": 0.6, "freshness": 1.0, "terminal_bias": 0.1},
        },
        candidate_numbers=[30, 6],
        status="win",
        hit_number=30,
        confidence_score=64,
        matched_episodes=14,
        avg_similarity=0.71,
        attempts=2,
        max_attempts=5,
    )

    assert profile["signals"] == 1
    assert profile["wins"] == 1
    assert profile["hit_rate"] == 1.0
    assert "decoder_score" in profile["weights"]
