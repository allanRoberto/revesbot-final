from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from api.routes import ai_shadow


def _sample_rows() -> list[dict]:
    start = datetime(2026, 3, 1, 0, 0, 0)
    values = [
        7, 2, 9, 1, 20, 14, 31, 30, 6, 24, 5, 7,
        11, 4, 9, 1, 20, 14, 31, 30, 6, 18, 22, 8,
        13, 2, 33, 1, 20, 14, 31, 30, 22, 6, 12, 24,
    ]
    return [
        {"value": value, "timestamp": start + timedelta(minutes=index)}
        for index, value in enumerate(values)
    ]


def test_run_ai_shadow_analysis_with_history_entries() -> None:
    payload = ai_shadow.AIShadowAnalyzeRequest(
        roulette_id="pragmatic-brazilian-roulette",
        history_entries=_sample_rows(),
        future_horizon=5,
        shadow_top_k=8,
        decoder_top_k=12,
        min_confidence=1,
        min_matched_episodes=1,
    )

    result = asyncio.run(ai_shadow._run_ai_shadow_analysis(payload))

    assert result["summary"]["roulette_id"] == "pragmatic-brazilian-roulette"
    assert len(result["shadow_signal_candidate"]["numbers"]) == 8
    assert "profile" in result


def test_ai_shadow_feedback_endpoint_uses_service(monkeypatch) -> None:
    def fake_apply_ai_shadow_feedback(**kwargs):
        return {"roulette_id": kwargs["roulette_id"], "signals": 2, "wins": 1, "losses": 1, "hit_rate": 0.5, "weights": {}, "top_weights": [], "recent_outcomes": [], "updated_at": "2026-03-29T00:00:00+00:00"}

    monkeypatch.setattr(ai_shadow.ai_shadow, "apply_ai_shadow_feedback", fake_apply_ai_shadow_feedback)

    payload = ai_shadow.AIShadowFeedbackRequest(
        roulette_id="pragmatic-brazilian-roulette",
        signal_id="shadow-1",
        numbers=[30, 6],
        feature_map={"30": {"decoder_score": 1.0}},
        status="loss",
    )

    result = asyncio.run(ai_shadow.ai_shadow_feedback(payload))

    assert result["ok"] is True
    assert result["profile"]["signals"] == 2
