from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError

from api.routes.contextual_pairs import asset_version, get_pairs_redis, router
from api.services.contextual_pairs_service import HEARTBEAT_KEY, HISTORY_KEY, SUMMARY_KEY, VIEW_KEY


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
        arcs = [[6, 27, 13, 36], [24, 16, 33, 1]]

        def signal(identifier, status, pair, checks, hit_attempt=None, hit_number=None):
            return {
                "id": identifier, "status": status, "built_after": spin, "top_numbers": [3, 7, 20, 25, 28, 12, 31],
                "pair": pair, "kept": [13, 16, 27, 33], "protection": [2, 12, 21, 25, 28],
                "bet": [1, 2, 3, 6, 7, 12, 13, 16, 21, 24, 25, 27, 28, 33, 36], "bet_arcs": arcs,
                "checks": [{"number": number, "timestamp": now.isoformat(), "hit": hit} for number, hit in checks],
                "attempts_limit": 7, "hit": None if status == "open" else status == "hit",
                "hit_attempt": hit_attempt, "hit_number": hit_number,
                "created_at": now.isoformat(), "closed_at": None if status == "open" else now.isoformat(),
            }

        screen = {"state": "active", "bases": [3, 7], "pair": [3, 7], "kept": [13, 16, 27, 33],
                  "protection": [2, 12, 21, 25, 28],
                  "bet": [1, 2, 3, 6, 7, 12, 13, 16, 21, 24, 25, 27, 28, 33, 36], "arcs": arcs, "built_after": spin}
        self.values = {
            VIEW_KEY: json.dumps({
                "version": 9, "updated_at": now.isoformat(), "attempts_limit": 7,
                "ranking": {"top": [{"position": 1, "number": 3, "points": 44, "exact": 2, "neighbor": 3}],
                            "built_after": spin, "analyzed_results": 280, "maximum": 2800},
                "screen": screen,
                "last_numbers": [{**spin, "hit": True}],
                "analysis": [{"trigger": spin, "status": "ok", "occurrences": []}],
                "open_signals": [signal("pairs-1-h3", "open", [3, 7], []), signal("pairs-1-h2", "open", [1, 5], [(20, False)])],
            }),
            HEARTBEAT_KEY: json.dumps({
                "at": (now - timedelta(seconds=heartbeat_age)).isoformat(), "status": status,
                "detail": None, "mongo": {"configured": True, "pending": 0},
            }),
        }
        self.lists = {HISTORY_KEY: [
            json.dumps(signal("pairs-1-h1", "hit", [2, 4], [(20, False), (13, True)], 2, 13)),
            json.dumps(signal("pairs-1-h0", "miss", [0, 3], [(n, False) for n in (20, 21, 22, 23, 25, 26, 28)])),
        ]}
        self.hashes = {SUMMARY_KEY: {
            "signals": "120", "hits": "95", "misses": "25", "rankings": "400", "ranking_opened": "120",
            "ranking_active": "80", "ranking_ignored": "7", "ranking_no_pair": "90", "ranking_too_many": "100",
            "ranking_no_intersection": "10",
        }}

    def pipeline(self, *, transaction):
        assert transaction is False
        return FakePipeline(self)


def client(redis_client):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_pairs_redis] = lambda: redis_client
    return TestClient(app)


def test_page_shell_has_the_pair_and_bet_columns_without_touching_redis():
    redis_client = FakeRedis()
    response = client(redis_client).get("/ranking-similaridade-pares")
    assert response.status_code == 200
    assert "Pares do ranking" in response.text
    version = asset_version()
    for asset in ("css/pages/contextual-ranking.css", "css/pages/contextual-pairs.css", "js/pages/contextual-pairs.js"):
        assert f"/static/{asset}?v={version}" in response.text
    assert 'id="panel-history"' in response.text and 'id="panel-analysis"' in response.text
    assert "<th>Par</th>" in response.text and "<th>Aposta do par</th>" in response.text
    assert "<th>Proteção</th>" in response.text and 'id="pair-protection"' in response.text
    assert redis_client.requests == []


def test_data_lists_open_signals_first_and_counts_only_closed_ones():
    response = client(FakeRedis()).get("/api/ranking-similaridade-pares")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["worker"]["status"] == "online"
    assert (data["version"], data["attempts_limit"]) == (9, 7)
    assert data["screen"]["state"] == "active" and data["screen"]["pair"] == [3, 7]
    assert [(row["id"], row["status"], row["pair"]) for row in data["history"]] == [
        ("pairs-1-h3", "open", [3, 7]), ("pairs-1-h2", "open", [1, 5]),
        ("pairs-1-h1", "hit", [2, 4]), ("pairs-1-h0", "miss", [0, 3]),
    ]
    assert data["history"][2]["hit_number"] == 13 and data["history"][0]["bet_arcs"][0] == [6, 27, 13, 36]
    assert data["history"][0]["protection"] == data["screen"]["protection"] == [2, 12, 21, 25, 28]
    assert data["summary"] == {
        "open": 2, "recent": {"hits": 1, "total": 2}, "all_time": {"hits": 95, "total": 120},
        "rankings": {"total": 400, "opened": 120, "active": 80, "ignored": 7, "no_pair": 90, "too_many": 100,
                     "no_intersection": 10},
    }


def test_history_limit_is_capped_at_fifty():
    redis_client = FakeRedis()
    test_client = client(redis_client)
    assert test_client.get("/api/ranking-similaridade-pares?limit=51").status_code == 422
    data = test_client.get("/api/ranking-similaridade-pares?limit=3").json()
    assert ("lrange", HISTORY_KEY, 0, 2) in redis_client.requests[-1]
    assert [row["id"] for row in data["history"]] == ["pairs-1-h3", "pairs-1-h2", "pairs-1-h1"]
    assert data["summary"]["recent"] == {"hits": 1, "total": 1}


def test_api_reads_the_keys_the_worker_writes():
    from contextual_pairs import storage

    assert (VIEW_KEY, HEARTBEAT_KEY, HISTORY_KEY, SUMMARY_KEY) == (
        storage.VIEW_KEY, storage.HEARTBEAT_KEY, storage.HISTORY_KEY, storage.SUMMARY_KEY,
    )


def test_worker_status_follows_the_heartbeat():
    data = client(FakeRedis(heartbeat_age=45)).get("/api/ranking-similaridade-pares").json()
    assert data["worker"]["status"] == "atrasado"
    data = client(FakeRedis(heartbeat_age=600)).get("/api/ranking-similaridade-pares").json()
    assert data["worker"]["status"] == "offline"
    data = client(FakeRedis(status="config_pending")).get("/api/ranking-similaridade-pares").json()
    assert data["worker"]["status"] == "configuracao_pendente"


def test_empty_redis_still_answers_with_a_waiting_screen():
    redis_client = FakeRedis()
    redis_client.values, redis_client.lists, redis_client.hashes = {}, {}, {}
    data = client(redis_client).get("/api/ranking-similaridade-pares").json()
    assert data["worker"]["status"] == "offline"
    assert data["ranking"]["top"] == [] and data["history"] == []
    assert data["screen"]["state"] == "waiting" and data["screen"]["bet"] == []
    assert data["screen"]["protection"] == []
    assert data["summary"]["all_time"] == {"hits": 0, "total": 0}
    assert data["summary"]["rankings"]["total"] == 0


def test_redis_failure_returns_service_unavailable():
    redis_client = FakeRedis()
    redis_client.broken = True
    response = client(redis_client).get("/api/ranking-similaridade-pares")
    assert response.status_code == 503
