from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from api.routes import roulette_analyzer as roulette_analyzer_route
from api.services import roulette_analyzer_backtest_service, roulette_analyzer_service


class _FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *args, **kwargs):
        return self

    def limit(self, amount):
        self.rows = self.rows[:amount]
        return self

    async def to_list(self, length=None):
        return self.rows[:length]


class _FakeCollection:
    def __init__(self, rows):
        self.rows = rows
        self.query = None

    def find(self, query, projection):
        self.query = query
        return _FakeCursor(list(self.rows))


def test_service_sends_newest_first_history_to_source_of_truth(monkeypatch) -> None:
    collection = _FakeCollection([{"value": 9}, {"value": 10}, {"value": 19}])
    captured = {}

    def fake_analyze(history):
        captured["history"] = history
        return {
            "numeros_fortes": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 0],
            "gatilhos": [1, 2, 3, 4, 0, 5],
        }

    monkeypatch.setattr(roulette_analyzer_service, "history_coll", collection)
    monkeypatch.setattr(roulette_analyzer_service, "analyze", fake_analyze)

    result = asyncio.run(roulette_analyzer_service.analyze_roulette(" roulette-a ", 3))

    assert collection.query == {"roulette_id": "roulette-a"}
    assert captured["history"] == [9, 10, 19]
    assert result["gatilhos"] == [1, 2, 3, 4, 0, 5]
    assert result["numeros_fortes"] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 0]
    assert result["numeros_puxando"] == result["numeros_fortes"]
    assert result["quantidade_analisada"] == 3


def test_route_returns_analyzer_result_without_other_engines(monkeypatch) -> None:
    expected = {
        "roulette_id": "roulette-a",
        "quantidade_solicitada": 100,
        "quantidade_analisada": 80,
        "numeros_fortes": [1, 2, 3],
        "numeros_puxando": [1, 2, 3],
        "gatilhos": [1, 2],
    }

    async def fake_service(roulette_id, quantidade):
        assert (roulette_id, quantidade) == ("roulette-a", 100)
        return expected

    monkeypatch.setattr(roulette_analyzer_route, "analyze_roulette", fake_service)

    result = asyncio.run(roulette_analyzer_route.run_roulette_analyzer("roulette-a", 100))

    assert result is expected


def test_route_maps_missing_history_to_404(monkeypatch) -> None:
    async def fake_service(roulette_id, quantidade):
        raise roulette_analyzer_service.RouletteHistoryNotFoundError

    monkeypatch.setattr(roulette_analyzer_route, "analyze_roulette", fake_service)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(roulette_analyzer_route.run_roulette_analyzer("unknown", 100))

    assert exc_info.value.status_code == 404


def _backtest_rows(values):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    chronological = [
        {
            "value": value,
            "timestamp": base + timedelta(minutes=index),
            "roulette_name": "Mesa A",
        }
        for index, value in enumerate(values)
    ]
    return list(reversed(chronological))


def test_walk_forward_measures_first_hit_per_renewal_without_future_leakage(
    monkeypatch,
) -> None:
    calls = []

    def fake_analyze(history, *, regression_compatibility):
        calls.append((list(history), regression_compatibility))
        return {"numeros_fortes": [1, 2], "gatilhos": [1]}

    monkeypatch.setattr(
        roulette_analyzer_backtest_service,
        "analyze",
        fake_analyze,
    )

    result = roulette_analyzer_backtest_service.backtest_rows(
        _backtest_rows([9, 8, 4, 1, 2, 5, 2, 1]),
        roulette_id="roulette-a",
        analysis_window=2,
        backtest_limit=6,
        max_attempts=3,
        renewal_mode="spins",
        renewal_value=3,
        target_hit_rate=0.90,
    )

    assert calls == [([8, 9], False), ([2, 1], False)]
    assert result["analysis_count"] == 2
    assert result["gatilhos"]["attempts"][1]["hits_at_attempt"] == 1
    assert result["gatilhos"]["attempts"][2]["hits_at_attempt"] == 1
    assert result["numeros_puxando"]["attempts"][1]["hits_at_attempt"] == 2
    assert result["gatilhos"]["hit_rate"] == 1.0
    assert result["numeros_puxando"]["median_first_hit_attempt"] == 2


def test_incomplete_last_cycle_is_censored_instead_of_counted_as_loss(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        roulette_analyzer_backtest_service,
        "analyze",
        lambda history, *, regression_compatibility: {
            "numeros_fortes": [1, 2],
            "gatilhos": [1],
        },
    )

    result = roulette_analyzer_backtest_service.backtest_rows(
        _backtest_rows([9, 8, 4, 5]),
        roulette_id="roulette-a",
        analysis_window=2,
        backtest_limit=2,
        max_attempts=5,
        renewal_mode="spins",
        renewal_value=5,
        target_hit_rate=0.90,
    )

    assert result["gatilhos"]["evaluated_cycles"] == 0
    assert result["gatilhos"]["no_hit_cycles"] == 0
    assert result["gatilhos"]["censored_cycles"] == 1


def test_minute_renewal_uses_timestamps_and_keeps_tables_independent(
    monkeypatch,
) -> None:
    calls = []

    def fake_analyze(history, *, regression_compatibility):
        calls.append(list(history))
        return {"numeros_fortes": [1, 2], "gatilhos": [1]}

    monkeypatch.setattr(
        roulette_analyzer_backtest_service,
        "analyze",
        fake_analyze,
    )
    result = roulette_analyzer_backtest_service.backtest_rows(
        _backtest_rows([9, 8, 4, 4, 1]),
        roulette_id="roulette-a",
        analysis_window=2,
        backtest_limit=3,
        max_attempts=3,
        renewal_mode="minutes",
        renewal_value=2,
        target_hit_rate=0.90,
    )

    assert calls == [[8, 9], [4, 8]]
    assert result["analysis_count"] == 2
    assert result["average_actual_renewal_seconds"] == 120
    assert result["gatilhos"]["attempts"][1]["hits_at_attempt"] == 1


def test_backtest_rejects_workload_before_querying_database() -> None:
    with pytest.raises(
        roulette_analyzer_backtest_service.RouletteBacktestValidationError
    ):
        asyncio.run(
            roulette_analyzer_backtest_service.run_roulette_analyzer_backtest(
                roulette_ids=[f"roulette-{index}" for index in range(10)],
                analysis_window=5_000,
                backtest_limit=50_000,
                max_attempts=100,
                renewal_mode="minutes",
                renewal_value=1,
                target_hit_rate=0.90,
            )
        )


def test_backtest_route_forwards_each_control(monkeypatch) -> None:
    captured = {}

    async def fake_backtest(**kwargs):
        captured.update(kwargs)
        return {"config": kwargs, "tables": []}

    monkeypatch.setattr(
        roulette_analyzer_route,
        "run_roulette_analyzer_backtest",
        fake_backtest,
    )
    payload = roulette_analyzer_route.RouletteAnalyzerBacktestRequest(
        roulette_ids=["roulette-a", "roulette-b"],
        analysis_window=200,
        backtest_limit=2_000,
        max_attempts=12,
        renewal_mode="minutes",
        renewal_value=10,
        target_hit_rate=0.85,
    )

    result = asyncio.run(
        roulette_analyzer_route.run_roulette_analyzer_backtest_route(payload)
    )

    assert result["tables"] == []
    assert captured == {
        "roulette_ids": ["roulette-a", "roulette-b"],
        "analysis_window": 200,
        "backtest_limit": 2_000,
        "max_attempts": 12,
        "renewal_mode": "minutes",
        "renewal_value": 10,
        "target_hit_rate": 0.85,
    }
