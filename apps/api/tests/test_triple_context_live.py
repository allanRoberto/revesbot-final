from __future__ import annotations

from datetime import datetime, timezone

from bson import json_util
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.triple_context_live import get_live_redis, router


class FakePipeline:
    def __init__(self, result):
        self.result = result

    def get(self, *_): return self
    def lrange(self, *_): return self
    def hgetall(self, *_): return self

    async def execute(self):
        return self.result


class FakeRedis:
    def __init__(self):
        now = datetime.now(timezone.utc)
        pending = {
            "id": "signal-1", "status": "pending", "trio": [7, 5, 23],
            "ranking": [
                {"position": position, "number": number, "score": 10 - position, "direct_hits": position}
                for position, number in enumerate([1, 2, 3, 4, 5, 6], 1)
            ],
            "occurrences": 11, "context_events": 55, "skip_reason": None,
            "result": None, "created_at": now, "resolved_at": None,
        }
        state = {
            "phase": "awaiting_result",
            "buffer": [{"number": 7}, {"number": 5}, {"number": 23}],
            "pending_signal": pending,
            "worker_heartbeat_at": now,
            "last_processed": {"timestamp": now},
        }
        self.result = [json_util.dumps(state), [], {"won": "8", "lost": "2", "skipped": "3"}]

    def pipeline(self, *, transaction):
        assert transaction is False
        return FakePipeline(self.result)


def client(redis_client):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_live_redis] = lambda: redis_client
    return TestClient(app)


def test_page_is_public_shell_but_data_requires_token(monkeypatch):
    monkeypatch.setenv("TRIPLE_CONTEXT_LIVE_DASHBOARD_TOKEN", "private-token")
    test_client = client(FakeRedis())
    page = test_client.get("/patterns/triple-context-live")
    assert page.status_code == 200
    assert "ACESSO PRIVADO" in page.text
    assert "triple-context-live.js?v=" in page.text
    assert test_client.get("/api/patterns/triple-context-live").status_code == 401


def test_live_projection_with_valid_token(monkeypatch):
    monkeypatch.setenv("TRIPLE_CONTEXT_LIVE_DASHBOARD_TOKEN", "private-token")
    response = client(FakeRedis()).get(
        "/api/patterns/triple-context-live",
        headers={"X-Live-Dashboard-Token": "private-token"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["worker"]["status"] == "online"
    assert body["configuration"] == {
        "ordered": True, "direction": "forward", "top_n": 6,
        "attempts": 1, "overlap": False, "block_size": 3,
    }
    assert body["summary"]["hit_rate"] == 80.0
    assert body["current"]["trio"] == [7, 5, 23]
    assert body["current"]["top_numbers"] == [1, 2, 3, 4, 5, 6]


def test_live_data_fails_closed_without_server_token(monkeypatch):
    monkeypatch.delenv("TRIPLE_CONTEXT_LIVE_DASHBOARD_TOKEN", raising=False)
    response = client(FakeRedis()).get(
        "/api/patterns/triple-context-live",
        headers={"X-Live-Dashboard-Token": "anything"},
    )
    assert response.status_code == 503
