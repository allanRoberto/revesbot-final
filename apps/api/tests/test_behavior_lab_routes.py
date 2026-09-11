from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.minimal_main import app
from api.routes import behavior_lab as behavior_lab_routes
from api.routes.behavior_lab import (
    MAX_BACKTEST_RESULTS,
    ROULETTE_ID,
    get_behavior_lab_facade,
    get_history_collection,
)


class FakeFacade:
    def __init__(self) -> None:
        self.config = object()
        self.backtest_events: list[int] | None = None
        self.backtest_input_order: str | None = None
        self.backtest_include_decisions: bool | None = None
        self.backtest_include_signals: bool | None = None

    def load_config(self):
        return self.config

    async def read_live_state(self, **kwargs):
        assert kwargs["config"] is self.config
        return {
            "roulette_id": ROULETTE_ID,
            "last_result": {"value": 16, "timestamp": "2026-09-11T12:00:00Z"},
            "decision": "BET",
            "suggestion": [1, 20, 14],
            "active_signals": [{"signal_id": "s1", "attempts": 1}],
        }

    async def read_signals(self, **kwargs):
        assert kwargs["config"] is self.config
        return {
            "roulette_id": ROULETTE_ID,
            "count": 1,
            "signals": [{"signal_id": "s1", "status": kwargs["status"] or "active"}],
        }

    async def read_health(self, **kwargs):
        assert kwargs["config"] is self.config
        return {
            "status": "healthy",
            "roulette_id": ROULETTE_ID,
            "heartbeat_at": "2026-09-11T12:00:00Z",
        }

    def run_backtest(self, events, **kwargs):
        assert kwargs["config"] is self.config
        self.backtest_events = list(events)
        self.backtest_input_order = kwargs["input_order"]
        self.backtest_include_decisions = kwargs["include_decisions"]
        self.backtest_include_signals = kwargs["include_signals"]
        return {
            "metrics": {
                "resolved": 2,
                "hit_rate": 0.5,
                "spins": {"accepted": max(0, len(events) - 1)},
            }
        }


class FakeCursor:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents
        self.sort_spec = None
        self.limit_value = None

    def sort(self, spec):
        self.sort_spec = spec
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    async def to_list(self, *, length):
        assert length == self.limit_value
        return self.documents[:length]


class FakeCollection:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.cursor = FakeCursor(documents)
        self.query = None
        self.projection = None

    def find(self, query, projection):
        self.query = query
        self.projection = projection
        return self.cursor


@pytest.fixture
def behavior_client(monkeypatch, tmp_path):
    monkeypatch.setattr(
        behavior_lab_routes,
        "BACKTEST_LOCK_PATH",
        tmp_path / "behavior-lab-backtest.lock",
    )
    facade = FakeFacade()
    collection = FakeCollection(
        [
            {"_id": "id-3", "external_game_id": "game-3", "value": 3},
            {"_id": "id-2b", "external_game_id": "game-2b", "value": 2},
            {"_id": "id-2a", "external_game_id": "game-2a", "value": 2},
            {"_id": "id-1", "external_game_id": "game-1", "value": 1},
        ]
    )
    app.dependency_overrides[get_behavior_lab_facade] = lambda: facade
    app.dependency_overrides[get_history_collection] = lambda: collection
    try:
        yield TestClient(app), facade, collection
    finally:
        app.dependency_overrides.clear()


def test_behavior_lab_page_is_concrete_route_with_external_assets(behavior_client) -> None:
    client, _, _ = behavior_client

    response = client.get("/patterns/behavior-lab")

    assert response.status_code == 200
    assert "<title>Behavior Lab | Revesbot</title>" in response.text
    assert 'id="live-decision"' in response.text
    assert 'id="active-signals-list"' in response.text
    assert 'id="backtest-form"' in response.text
    assert 'data-max-attempts="10"' in response.text
    assert f'max="{MAX_BACKTEST_RESULTS}"' in response.text
    assert 'value="2000"' in response.text
    assert 'href="/static/css/pages/behavior-lab.css?v=' in response.text
    assert 'src="/static/js/pages/behavior-lab.js?v=' in response.text
    assert "<style" not in response.text
    assert "<script>" not in response.text


def test_behavior_lab_read_routes_delegate_to_facade(behavior_client) -> None:
    client, _, _ = behavior_client

    live = client.get("/api/patterns/behavior-lab/live")
    signals = client.get("/api/patterns/behavior-lab/signals?limit=12&status=active")
    health = client.get("/api/patterns/behavior-lab/health")

    assert live.status_code == 200
    assert live.json()["suggestion"] == [1, 20, 14]
    assert signals.status_code == 200
    assert signals.json()["count"] == 1
    assert health.status_code == 200
    assert health.json()["status"] == "healthy"


def test_backtest_reads_only_fixed_table_and_keeps_repeated_results(behavior_client) -> None:
    client, facade, collection = behavior_client

    response = client.post(
        "/api/patterns/behavior-lab/backtest",
        json={"limit": 4},
    )

    assert response.status_code == 200
    assert collection.query == {"roulette_id": ROULETTE_ID}
    assert collection.cursor.sort_spec == [("timestamp", -1), ("_id", -1)]
    assert [event["value"] for event in facade.backtest_events] == [1, 2, 2, 3]
    assert [event["external_game_id"] for event in facade.backtest_events] == [
        "game-1",
        "game-2a",
        "game-2b",
        "game-3",
    ]
    assert facade.backtest_input_order == "chronological"
    assert facade.backtest_include_decisions is False
    assert facade.backtest_include_signals is False
    assert response.json()["results_loaded"] == 4
    assert response.json()["results_used"] == 3
    assert response.json()["max_attempts"] == 10


def test_backtest_limit_is_capped_by_request_schema(behavior_client) -> None:
    client, facade, _ = behavior_client

    response = client.post(
        "/api/patterns/behavior-lab/backtest",
        json={"limit": MAX_BACKTEST_RESULTS + 1},
    )

    assert response.status_code == 422
    assert facade.backtest_events is None


def test_backtest_reports_empty_history(behavior_client) -> None:
    client, facade, _ = behavior_client
    empty_collection = FakeCollection([])
    app.dependency_overrides[get_history_collection] = lambda: empty_collection

    response = client.post(
        "/api/patterns/behavior-lab/backtest",
        json={"limit": 100},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Não há resultados disponíveis para o backtest"
    assert facade.backtest_events is None


def test_backtest_lock_rejects_a_second_execution(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        behavior_lab_routes,
        "BACKTEST_LOCK_PATH",
        tmp_path / "behavior-lab-backtest.lock",
    )

    with behavior_lab_routes._exclusive_backtest():
        with pytest.raises(HTTPException) as exc_info:
            with behavior_lab_routes._exclusive_backtest():
                pass

    assert exc_info.value.status_code == 429


def test_backtest_cooldown_rejects_sequential_abuse(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        behavior_lab_routes,
        "BACKTEST_LOCK_PATH",
        tmp_path / "behavior-lab-backtest.lock",
    )

    with behavior_lab_routes._exclusive_backtest():
        pass
    with pytest.raises(HTTPException, match="Aguarde") as exc_info:
        with behavior_lab_routes._exclusive_backtest():
            pass

    assert exc_info.value.status_code == 429
