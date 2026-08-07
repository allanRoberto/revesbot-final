from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api.routes import probability_backtest


def test_probability_requests_are_strict_and_normalize_roulette_id() -> None:
    payload = probability_backtest.ProbabilityBacktestRequest(
        roulette_id="  pragmatic-auto-roulette ",
        number_count=12,
        attempts=3,
    )
    assert payload.roulette_id == "pragmatic-auto-roulette"
    assert payload.number_count == 12
    assert payload.attempts == 3

    with pytest.raises(ValidationError):
        probability_backtest.ProbabilityBacktestRequest(
            roulette_id="pragmatic-auto-roulette",
            number_count="12",
        )

    with pytest.raises(ValidationError):
        probability_backtest.ProbabilityBacktestRequest(
            roulette_id="invalid slug",
        )


def test_backtest_route_forwards_all_configuration(monkeypatch) -> None:
    captured = {}

    async def fake_run(**kwargs):
        captured.update(kwargs)
        return {"available": True}

    monkeypatch.setattr(probability_backtest, "run_probability_backtest", fake_run)
    payload = probability_backtest.ProbabilityBacktestRequest(
        roulette_id="pragmatic-auto-roulette",
        history_limit=1500,
        number_count=9,
        attempts=5,
        entries_limit=200,
        minimum_history=150,
    )
    result = asyncio.run(probability_backtest.probability_model_backtest(payload))

    assert result == {"available": True}
    assert captured == {
        "roulette_id": "pragmatic-auto-roulette",
        "history_limit": 1500,
        "number_count": 9,
        "attempts": 5,
        "entries_limit": 200,
        "minimum_history": 150,
    }


def test_analysis_route_maps_missing_history_to_404(monkeypatch) -> None:
    async def missing(**kwargs):
        raise LookupError("sem historico")

    monkeypatch.setattr(probability_backtest, "analyze_current_probability", missing)
    payload = probability_backtest.CurrentProbabilityRequest(
        roulette_id="pragmatic-auto-roulette"
    )

    with pytest.raises(HTTPException) as captured:
        asyncio.run(probability_backtest.probability_model_analyze(payload))

    assert captured.value.status_code == 404


def test_probability_page_is_available() -> None:
    response = asyncio.run(probability_backtest.probability_backtest_page())
    assert response.status_code == 200
    assert b"Executar backtest" in response.body
