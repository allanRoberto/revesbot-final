from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from api.routes import decoder_lab


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


def test_run_decoder_lab_analysis_returns_new_decoder_payload(monkeypatch) -> None:
    async def fake_load_decoder_lab_rows(**kwargs):
        return _sample_rows()

    monkeypatch.setattr(decoder_lab.decoder_lab, "load_decoder_lab_rows", fake_load_decoder_lab_rows)

    payload = decoder_lab.DecoderLabRequest(
        roulette_id="pragmatic-brazilian-roulette",
        state_numbers=[7, 9, 1, 20, 14, 31],
        future_horizon=5,
        ignore_last_occurrence=False,
        days_back=30,
        max_records=5000,
        validation_ratio=0.25,
        min_support=1,
        top_k=8,
        episode_limit=20,
        similarity_threshold=0.45,
    )

    result = asyncio.run(decoder_lab._run_decoder_lab_analysis(payload))

    assert result["summary"]["roulette_id"] == "pragmatic-brazilian-roulette"
    assert result["current_state"]["source"] == "manual"
    assert result["summary"]["matched_episodes"] > 0
    assert result["suggestion"]["available"] is True
    assert result["similar_episodes"]
    assert result["horizon_rankings"]["5"]["candidates"]


def test_run_decoder_lab_analysis_handles_empty_history(monkeypatch) -> None:
    async def fake_load_decoder_lab_rows(**kwargs):
        return []

    monkeypatch.setattr(decoder_lab.decoder_lab, "load_decoder_lab_rows", fake_load_decoder_lab_rows)

    payload = decoder_lab.DecoderLabRequest(
        roulette_id="pragmatic-brazilian-roulette",
        state_numbers=[19, 36, 15, 4],
    )

    result = asyncio.run(decoder_lab._run_decoder_lab_analysis(payload))

    assert result["summary"]["total_spins_analyzed"] == 0
    assert result["current_state"]["source"] == "manual"
    assert result["suggestion"]["available"] is False


def test_run_decoder_lab_analysis_uses_history_entries_and_returns_live_candidate(monkeypatch) -> None:
    async def fail_load_decoder_lab_rows(**kwargs):
        raise AssertionError("load_decoder_lab_rows não deveria ser chamado quando history_entries for informado")

    monkeypatch.setattr(decoder_lab.decoder_lab, "load_decoder_lab_rows", fail_load_decoder_lab_rows)

    payload = decoder_lab.DecoderLabRequest(
        roulette_id="pragmatic-brazilian-roulette",
        history_entries=_sample_rows(),
        state_window=6,
        future_horizon=5,
        ignore_last_occurrence=False,
        validation_ratio=0.25,
        min_support=1,
        top_k=8,
        episode_limit=20,
        similarity_threshold=0.45,
        live_min_confidence=1,
        live_min_matched_episodes=1,
        live_number_count=9,
    )

    result = asyncio.run(decoder_lab._run_decoder_lab_analysis(payload))

    assert result["summary"]["roulette_id"] == "pragmatic-brazilian-roulette"
    assert "live_signal_candidate" in result
    assert set(result["live_signal_candidate"]).issuperset(
        {"emit", "numbers", "confidence_score", "matched_episodes", "future_horizon", "number_count_requested"}
    )
    assert result["live_signal_candidate"]["number_count_requested"] == 9
