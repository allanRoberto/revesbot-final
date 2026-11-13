from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError

from api.routes.contextual_ranking import asset_version, get_ranking_redis, router
from api.services.contextual_ranking_service import (
    HEARTBEAT_KEY, HISTORY_KEY, SUMMARY_KEY, VIEW_KEY, worker_status,
)


class FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.keys = []

    def get(self, key): self.keys.append(("get", key)); return self
    def lrange(self, key, start, end): self.keys.append(("lrange", key, start, end)); return self
    def hgetall(self, key): self.keys.append(("hgetall", key)); return self

    async def execute(self):
        if self.redis.broken:
            raise RedisConnectionError("redis fora do ar")
        self.redis.requests.append(self.keys)
        results = []
        for operation in self.keys:
            if operation[0] == "get":
                results.append(self.redis.values.get(operation[1]))
            elif operation[0] == "lrange":
                results.append(self.redis.lists.get(operation[1], [])[operation[2]:operation[3] + 1])
            else:
                results.append(self.redis.hashes.get(operation[1], {}))
        return results


class FakeRedis:
    def __init__(self, heartbeat_age=2, status="running"):
        now = datetime.now(timezone.utc)
        self.broken = False
        self.requests = []
        signal = {
            "id": "h2", "result": {"history_id": "h2", "number": 8, "timestamp": now.isoformat()},
            "top_numbers": [8, 30, 24, 16, 6, 11, 12], "hit": True, "hit_position": 1,
            "ranking_built_after": {"history_id": "h1", "number": 7, "timestamp": now.isoformat()},
            "created_at": now.isoformat(),
        }
        self.values = {
            VIEW_KEY: json.dumps({
                "version": 9, "updated_at": now.isoformat(),
                "ranking": {"top": [{"position": 1, "number": 8, "points": 44, "exact": 2, "neighbor": 3}],
                            "built_after": signal["result"], "analyzed_results": 100, "maximum": 1000},
                "last_numbers": [{"history_id": "h2", "number": 8, "timestamp": now.isoformat(), "hit": True}],
                "analysis": [{"trigger": signal["result"], "status": "ok", "occurrences": []}],
            }),
            HEARTBEAT_KEY: json.dumps({
                "at": (now - timedelta(seconds=heartbeat_age)).isoformat(), "status": status,
                "detail": None, "mongo": {"configured": True, "pending": 0},
            }),
        }
        self.lists = {HISTORY_KEY: [json.dumps(signal), json.dumps({**signal, "id": "h1", "hit": False})]}
        self.hashes = {SUMMARY_KEY: {"signals": "120", "hits": "31", "misses": "89"}}

    def pipeline(self, *, transaction):
        assert transaction is False
        return FakePipeline(self)


def client(redis_client):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_ranking_redis] = lambda: redis_client
    return TestClient(app)


def test_page_shell_uses_versioned_assets_without_touching_redis():
    redis_client = FakeRedis()
    response = client(redis_client).get("/ranking-similaridade-contextual")
    assert response.status_code == 200
    assert "Ranking por similaridade contextual" in response.text
    version = asset_version()
    assert f'/static/css/pages/contextual-ranking.css?v={version}' in response.text
    assert f'/static/js/pages/contextual-ranking.js?v={version}' in response.text
    assert 'id="panel-history"' in response.text and 'id="panel-analysis"' in response.text
    assert redis_client.requests == []


def test_data_combines_ranking_history_and_totals():
    response = client(FakeRedis()).get("/api/ranking-similaridade-contextual")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["worker"]["status"] == "online"
    assert data["version"] == 9
    assert data["ranking"]["top"][0]["number"] == 8
    assert [row["id"] for row in data["history"]] == ["h2", "h1"]
    assert data["summary"] == {"recent": {"hits": 1, "total": 2}, "all_time": {"hits": 31, "total": 120}}


def test_history_limit_is_capped_at_fifty():
    redis_client = FakeRedis()
    test_client = client(redis_client)
    assert test_client.get("/api/ranking-similaridade-contextual?limit=51").status_code == 422
    test_client.get("/api/ranking-similaridade-contextual?limit=10")
    assert ("lrange", HISTORY_KEY, 0, 9) in redis_client.requests[-1]


def test_worker_states_follow_the_heartbeat():
    assert worker_status({}, None) == "offline"
    assert worker_status({"status": "config_pending"}, 1) == "configuracao_pendente"
    assert worker_status({"status": "running"}, 5) == "online"
    assert worker_status({"status": "running"}, 45) == "atrasado"
    assert worker_status({"status": "error"}, 5) == "atrasado"
    assert worker_status({"status": "running"}, 600) == "offline"
    data = client(FakeRedis(heartbeat_age=600)).get("/api/ranking-similaridade-contextual").json()
    assert data["worker"]["status"] == "offline"


def test_empty_redis_still_answers_with_an_empty_ranking():
    redis_client = FakeRedis()
    redis_client.values, redis_client.lists, redis_client.hashes = {}, {}, {}
    data = client(redis_client).get("/api/ranking-similaridade-contextual").json()
    assert data["worker"]["status"] == "offline"
    assert data["ranking"]["top"] == []
    assert data["history"] == []
    assert data["summary"]["all_time"] == {"hits": 0, "total": 0}


def test_redis_failure_returns_service_unavailable():
    redis_client = FakeRedis()
    redis_client.broken = True
    response = client(redis_client).get("/api/ranking-similaridade-contextual")
    assert response.status_code == 503
