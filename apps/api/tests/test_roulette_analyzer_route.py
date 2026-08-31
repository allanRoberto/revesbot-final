from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from api.routes import roulette_analyzer as roulette_analyzer_route
from api.services import roulette_analyzer_service


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
