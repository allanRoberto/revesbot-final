from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.triple_context_live import get_live_db, router


class AsyncRows:
    def __init__(self, rows):
        self.rows = list(rows)
        self._limit = len(self.rows)

    def sort(self, *_):
        return self

    def limit(self, limit):
        self._limit = limit
        return self

    async def to_list(self, *, length):
        return self.rows[: min(length, self._limit)]

    def __aiter__(self):
        self._iterator = iter(self.rows)
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration as error:
            raise StopAsyncIteration from error


class FakeCollection:
    def __init__(self, *, one=None, rows=None, aggregate_rows=None):
        self.one = one
        self.rows = rows or []
        self.aggregate_rows = aggregate_rows or []

    async def find_one(self, *_):
        return self.one

    def find(self, *_):
        return AsyncRows(self.rows)

    def aggregate(self, *_):
        return AsyncRows(self.aggregate_rows)


class FakeDB:
    def __init__(self):
        now = datetime.now(timezone.utc)
        self.collections = {
            "triple_context_live_state_v1": FakeCollection(one={
                "phase": "awaiting_result",
                "buffer": [{"number": 7}, {"number": 5}, {"number": 23}],
                "worker_heartbeat_at": now,
                "last_processed": {"timestamp": now},
            }),
            "triple_context_live_signals_v1": FakeCollection(
                rows=[{
                    "_id": "signal-1", "status": "pending", "trio": [7, 5, 23],
                    "ranking": [
                        {"position": position, "number": number, "score": 10 - position, "direct_hits": position}
                        for position, number in enumerate([1, 2, 3, 4, 5, 6], 1)
                    ],
                    "occurrences": 11, "context_events": 55, "skip_reason": None,
                    "result": None, "created_at": now, "resolved_at": None,
                }],
                aggregate_rows=[
                    {"_id": "won", "count": 8}, {"_id": "lost", "count": 2},
                    {"_id": "pending", "count": 1}, {"_id": "skipped", "count": 3},
                ],
            ),
        }

    def __getitem__(self, name):
        return self.collections[name]


def client(database):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_live_db] = lambda: database
    return TestClient(app)


def test_page_is_public_shell_but_data_requires_token(monkeypatch):
    monkeypatch.setenv("TRIPLE_CONTEXT_LIVE_DASHBOARD_TOKEN", "private-token")
    test_client = client(FakeDB())
    page = test_client.get("/patterns/triple-context-live")
    assert page.status_code == 200
    assert "ACESSO PRIVADO" in page.text
    assert "triple-context-live.js?v=" in page.text
    assert test_client.get("/api/patterns/triple-context-live").status_code == 401


def test_live_projection_with_valid_token(monkeypatch):
    monkeypatch.setenv("TRIPLE_CONTEXT_LIVE_DASHBOARD_TOKEN", "private-token")
    response = client(FakeDB()).get(
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
    response = client(FakeDB()).get(
        "/api/patterns/triple-context-live",
        headers={"X-Live-Dashboard-Token": "anything"},
    )
    assert response.status_code == 503
