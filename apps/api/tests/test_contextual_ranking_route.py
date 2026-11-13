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
        spin = {"history_id": "h3", "number": 8, "timestamp": now.isoformat()}

        def signal(identifier, status, checks, hit_attempt=None):
            return {
                "id": identifier, "status": status, "built_after": spin,
                "top_numbers": [8, 30, 24, 16, 6, 11, 12], "attempts_limit": 7,
                "checks": [{"number": number, "timestamp": now.isoformat(), "hit": hit}
                           for number, hit in checks],
                "hit": None if status == "open" else status == "hit", "hit_attempt": hit_attempt,
                "hit_position": 1 if status == "hit" else None,
                "created_at": now.isoformat(), "closed_at": None if status == "open" else now.isoformat(),
            }

        self.values = {
            VIEW_KEY: json.dumps({
                "version": 9, "updated_at": now.isoformat(), "attempts_limit": 7,
                "ranking": {"top": [{"position": 1, "number": 8, "points": 44, "exact": 2, "neighbor": 3}],
                            "built_after": spin, "analyzed_results": 100, "maximum": 1000},
                "last_numbers": [{**spin, "hit": True}],
                "analysis": [{"trigger": spin, "status": "ok", "occurrences": []}],
                "open_signals": [signal("v2-h3", "open", []), signal("v2-h2", "open", [(5, False)])],
            }),
            HEARTBEAT_KEY: json.dumps({
                "at": (now - timedelta(seconds=heartbeat_age)).isoformat(), "status": status,
                "detail": None, "mongo": {"configured": True, "pending": 0},
            }),
        }
        self.lists = {HISTORY_KEY: [
            json.dumps(signal("v2-h1", "hit", [(5, False), (8, True)], hit_attempt=2)),
            json.dumps(signal("v2-h0", "miss", [(n, False) for n in (1, 2, 3, 4, 5, 7, 9)])),
        ]}
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


def test_data_lists_open_signals_first_and_counts_only_closed_ones():
    response = client(FakeRedis()).get("/api/ranking-similaridade-contextual")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["worker"]["status"] == "online"
    assert data["version"] == 9
    assert data["attempts_limit"] == 7
    assert data["ranking"]["top"][0]["number"] == 8
    assert [(row["id"], row["status"]) for row in data["history"]] == [
        ("v2-h3", "open"), ("v2-h2", "open"), ("v2-h1", "hit"), ("v2-h0", "miss"),
    ]
    assert data["summary"] == {
        "open": 2, "recent": {"hits": 1, "total": 2}, "all_time": {"hits": 31, "total": 120},
    }


def test_history_limit_is_capped_at_fifty():
    redis_client = FakeRedis()
    test_client = client(redis_client)
    assert test_client.get("/api/ranking-similaridade-contextual?limit=51").status_code == 422
    data = test_client.get("/api/ranking-similaridade-contextual?limit=3").json()
    assert ("lrange", HISTORY_KEY, 0, 2) in redis_client.requests[-1]
    assert [row["id"] for row in data["history"]] == ["v2-h3", "v2-h2", "v2-h1"]
    assert data["summary"]["recent"] == {"hits": 1, "total": 1}


def test_api_reads_the_keys_the_worker_writes():
    from contextual_ranking import storage

    assert (VIEW_KEY, HEARTBEAT_KEY, HISTORY_KEY, SUMMARY_KEY) == (
        storage.VIEW_KEY, storage.HEARTBEAT_KEY, storage.HISTORY_KEY, storage.SUMMARY_KEY,
    )


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
