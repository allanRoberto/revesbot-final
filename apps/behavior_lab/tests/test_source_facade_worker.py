from __future__ import annotations

import asyncio

import pytest

from behavior_lab.config import BehaviorLabConfig
from behavior_lab.contracts import RuleProposal, Spin, utc_now_iso
from behavior_lab.engine import BehaviorEngine
from behavior_lab.facade import read_health, read_live_state, read_signals
from behavior_lab.source_api import ResultAPIClient, history_url, websocket_url
from behavior_lab.state_store import RedisStateStore
from behavior_lab.worker import BehaviorLabWorker


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeHTTPClient:
    def __init__(self, payload):
        self.payload = payload
        self.requested = []

    async def get(self, url):
        self.requested.append(url)
        return FakeResponse(self.payload)


class FakeRedis:
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value):
        self.values[key] = value
        return True


class FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.commands = []

    def set(self, key, value):
        self.commands.append((key, value))
        return self

    async def execute(self):
        self.redis.execute_calls += 1
        for key, value in self.commands:
            self.redis.values[key] = value
        return [True] * len(self.commands)


class FakeTransactionalRedis(FakeRedis):
    def __init__(self):
        super().__init__()
        self.execute_calls = 0

    def pipeline(self, *, transaction):
        assert transaction is True
        return FakePipeline(self)


class FakeSource:
    def __init__(self, spins):
        self.spins = spins
        self.requested_limits = []

    async def fetch_history(self, limit=500):
        self.requested_limits.append(limit)
        return self.spins[-limit:]

    async def websocket_events(self):
        if False:
            yield None


class OneShotRule:
    name = "one_shot_worker_test"

    def detect(self, history, config):
        if len(history) != 1:
            return None
        return RuleProposal(
            rule=self.name,
            targets=(7,),
            exhausted_targets=(),
            evidence={"test": True},
        )


def test_urls_and_history_order_with_event_identity() -> None:
    async def scenario():
        payload = {
            "items": [
                {"value": 2, "roulette_id": "pragmatic-auto-roulette", "_id": "new"},
                {"value": 1, "roulette_id": "pragmatic-auto-roulette", "_id": "old"},
            ]
        }
        http = FakeHTTPClient(payload)
        client = ResultAPIClient(
            base_url="https://api.revesbot.com.br",
            roulette_id="pragmatic-auto-roulette",
            http_client=http,
        )
        spins = await client.fetch_history(500)
        assert [(spin.value, spin.event_id) for spin in spins] == [(1, "old"), (2, "new")]
        assert http.requested == [
            "https://api.revesbot.com.br/history/pragmatic-auto-roulette?limit=500"
        ]

    asyncio.run(scenario())
    assert websocket_url("https://api.revesbot.com.br", "pragmatic-auto-roulette") == (
        "wss://api.revesbot.com.br/ws?slug=pragmatic-auto-roulette"
    )
    assert history_url("http://local", "a/b", 2) == "http://local/history/a%2Fb?limit=2"


def test_ws_envelope_uses_full_result_identity_and_envelope_value() -> None:
    spin = Spin.from_raw(
        {
            "slug": "pragmatic-auto-roulette",
            "result": 14,
            "full_result": {
                "value": 99,
                "_id": "mongo-id",
                "external_game_id": "game-id",
                "timestamp": "2026-09-11T00:00:00+00:00",
            },
        }
    )
    assert spin.value == 14
    assert spin.event_id == "mongo-id"
    assert spin.external_game_id == "game-id"
    assert spin.identity_keys == ("external:game-id", "id:mongo-id")


def test_live_history_without_identity_fails_closed() -> None:
    async def scenario():
        client = ResultAPIClient(
            base_url="https://api.revesbot.com.br",
            roulette_id="pragmatic-auto-roulette",
            http_client=FakeHTTPClient({"results": [2, 1]}),
        )
        with pytest.raises(ValueError, match="_id ou external_game_id"):
            await client.fetch_history(2)

    asyncio.run(scenario())


def test_facade_reads_derived_namespace_with_injected_client() -> None:
    async def scenario():
        config = BehaviorLabConfig()
        redis = FakeRedis()
        store = RedisStateStore(config, redis_client=redis)
        snapshot = {
            "roulette_id": config.roulette_id,
            "processed_count": 0,
            "state_revision": 0,
            "suggestion": [13, 36],
        }
        await store.set_json("snapshot", snapshot)
        await store.set_json("signals", [{"status": "active"}, {"status": "lost"}])
        await store.set_json(
            "health",
            {
                "status": "healthy",
                "roulette_id": config.roulette_id,
                "heartbeat_at": utc_now_iso(),
                "ws_connected": True,
            },
        )
        live = await read_live_state(redis_client=redis, config=config)
        assert live["suggestion"] == snapshot["suggestion"]
        assert live["worker"]["status"] == "healthy"
        assert live["worker"]["fresh"] is True
        active = await read_signals(redis_client=redis, config=config, status="active")
        assert active["count"] == 1
        assert (await read_health(redis_client=redis, config=config))["status"] == "healthy"
        assert all(key.startswith("behavior_lab:v1:pragmatic-auto-roulette:") for key in redis.values)

    asyncio.run(scenario())


def test_state_snapshot_and_signals_are_published_in_one_transaction() -> None:
    async def scenario():
        config = BehaviorLabConfig()
        redis = FakeTransactionalRedis()
        store = RedisStateStore(config, redis_client=redis)
        engine = BehaviorEngine(config, rules=[])
        engine.process(14)

        await store.save_engine(engine)

        assert redis.execute_calls == 1
        assert set(redis.values) == {
            store.keys["state"],
            store.keys["snapshot"],
            store.keys["signals"],
        }
        snapshot = await store.get_json("snapshot")
        assert snapshot["state_revision"] == snapshot["processed_count"] == 1

    asyncio.run(scenario())


def test_stale_worker_state_cannot_publish_a_live_bet() -> None:
    async def scenario():
        config = BehaviorLabConfig()
        redis = FakeRedis()
        store = RedisStateStore(config, redis_client=redis)
        await store.set_json(
            "snapshot",
            {
                "roulette_id": config.roulette_id,
                "suggestion": [13, 36],
                "decision": "BET",
                "active_signals": [{"signal_id": "stale"}],
            },
        )
        await store.set_json(
            "health",
            {
                "status": "healthy",
                "roulette_id": config.roulette_id,
                "heartbeat_at": "2020-01-01T00:00:00+00:00",
            },
        )

        live = await read_live_state(redis_client=redis, config=config)
        health = await read_health(redis_client=redis, config=config)
        assert live["decision"] == "NO_BET"
        assert live["suggestion"] == []
        assert live["active_signals"] == []
        assert live["reason"] == "worker_state_stale"
        assert live["worker"]["fresh"] is False
        assert health["status"] == "stale"

    asyncio.run(scenario())


def test_health_and_snapshot_revision_mismatch_cannot_publish_a_bet() -> None:
    async def scenario():
        config = BehaviorLabConfig()
        redis = FakeRedis()
        store = RedisStateStore(config, redis_client=redis)
        await store.set_json(
            "snapshot",
            {
                "roulette_id": config.roulette_id,
                "processed_count": 10,
                "state_revision": 10,
                "suggestion": [13, 36],
                "decision": "BET",
            },
        )
        await store.set_json(
            "health",
            {
                "status": "healthy",
                "heartbeat_at": utc_now_iso(),
                "processed_count": 11,
                "state_revision": 11,
            },
        )

        live = await read_live_state(redis_client=redis, config=config)
        assert live["decision"] == "NO_BET"
        assert live["suggestion"] == []
        assert live["reason"] == "worker_state_lagging"

    asyncio.run(scenario())


def test_disconnected_worker_cannot_publish_a_bet() -> None:
    async def scenario():
        config = BehaviorLabConfig()
        redis = FakeRedis()
        store = RedisStateStore(config, redis_client=redis)
        await store.set_json(
            "snapshot",
            {
                "roulette_id": config.roulette_id,
                "processed_count": 10,
                "state_revision": 10,
                "suggestion": [13, 36],
                "decision": "BET",
            },
        )
        await store.set_json(
            "health",
            {
                "status": "healthy",
                "heartbeat_at": utc_now_iso(),
                "ws_connected": False,
                "processed_count": 10,
                "state_revision": 10,
            },
        )

        live = await read_live_state(redis_client=redis, config=config)
        assert live["decision"] == "NO_BET"
        assert live["suggestion"] == []
        assert live["reason"] == "worker_not_ready"

    asyncio.run(scenario())


def test_previous_release_heartbeat_cannot_publish_a_bet(monkeypatch) -> None:
    async def scenario():
        config = BehaviorLabConfig()
        redis = FakeRedis()
        store = RedisStateStore(config, redis_client=redis)
        await store.set_json(
            "snapshot",
            {
                "roulette_id": config.roulette_id,
                "processed_count": 10,
                "state_revision": 10,
                "suggestion": [13, 36],
                "decision": "BET",
            },
        )
        await store.set_json(
            "health",
            {
                "status": "healthy",
                "heartbeat_at": utc_now_iso(),
                "processed_count": 10,
                "state_revision": 10,
                "release_id": "previous-release",
            },
        )

        live = await read_live_state(redis_client=redis, config=config)
        assert live["decision"] == "NO_BET"
        assert live["suggestion"] == []
        assert live["worker"]["status"] == "stale_release"
        assert live["worker"]["release_matches"] is False

    monkeypatch.setenv("BEHAVIOR_LAB_RELEASE_ID", "current-release")
    asyncio.run(scenario())


def test_bootstrap_warms_context_without_live_metrics() -> None:
    async def scenario():
        config = BehaviorLabConfig(exhaustion_window=5)
        values = [26, 36, 2, 34, 5, *([8] * 9), 26, 36]
        spins = [
            Spin(value=value, event_id=f"id-{index}", source="history_api")
            for index, value in enumerate(values)
        ]
        redis = FakeRedis()
        worker = BehaviorLabWorker(
            config=config,
            source=FakeSource(spins),
            store=RedisStateStore(config, redis_client=redis),
            reconcile_interval_seconds=30,
        )
        await worker.initialize()
        snapshot = await worker.store.get_json("snapshot")
        assert snapshot["processed_count"] == len(spins)
        assert snapshot["metrics"]["spins"]["accepted"] == 0
        assert snapshot["metrics"]["spins"]["duplicate_events_ignored"] == 0
        assert snapshot["metrics"]["decisions"]["total"] == 0
        assert snapshot["active_signals"]
        assert await worker.reconcile() == 0
        assert worker.engine.duplicate_events == 0
        # A repeated numeric result with a fresh ID advances the carried signal.
        signal = worker.engine.ledger.active[0]
        await worker.process_event(Spin(value=36, event_id="fresh", source="websocket"))
        assert signal.attempts == 1
        assert (await worker.store.get_json("snapshot"))["metrics"]["spins"]["accepted"] == 1

    asyncio.run(scenario())


def test_websocket_reconciles_missed_event_before_newer_notification() -> None:
    async def scenario():
        config = BehaviorLabConfig()
        trigger = Spin(value=1, event_id="event-0", source="history_api")
        missed = Spin(value=0, event_id="event-1", source="history_api")
        newest = Spin(value=0, event_id="event-2", source="websocket")
        source = FakeSource([trigger, missed, newest])
        redis = FakeRedis()
        worker = BehaviorLabWorker(
            config=config,
            source=source,
            store=RedisStateStore(config, redis_client=redis),
        )
        worker.engine = BehaviorEngine(config, rules=[OneShotRule()])
        worker.engine.process(trigger, source="bootstrap")
        worker.engine.reset_prospective_metrics()

        accepted = await worker.process_websocket_event(newest)

        signal = worker.engine.ledger.active[0]
        assert accepted == 2
        assert [spin.event_id for spin in worker.engine.history] == [
            "event-0",
            "event-1",
            "event-2",
        ]
        assert signal.attempts == 2
        assert worker.engine.prospective_spins == 2
        assert worker.engine.duplicate_events == 0
        assert source.requested_limits == [config.context_size]

    asyncio.run(scenario())


def test_websocket_handshake_reconciles_before_worker_becomes_healthy() -> None:
    async def scenario():
        config = BehaviorLabConfig()
        trigger = Spin(value=1, event_id="event-0", source="history_api")
        repeated_value = Spin(value=1, event_id="event-1", source="history_api")
        source = FakeSource([trigger, repeated_value])
        redis = FakeRedis()
        worker = BehaviorLabWorker(
            config=config,
            source=source,
            store=RedisStateStore(config, redis_client=redis),
        )
        worker.engine = BehaviorEngine(config, rules=[OneShotRule()])
        worker.engine.process(trigger, source="bootstrap")
        worker.engine.reset_prospective_metrics()

        await worker._mark_websocket_connected()

        signal = worker.engine.ledger.active[0]
        health = await worker.store.get_json("health")
        assert worker._ws_connected is True
        assert worker.engine.processed_count == 2
        assert signal.attempts == 1
        assert health["status"] == "healthy"
        assert health["ws_connected"] is True
        assert health["state_revision"] == 2

    asyncio.run(scenario())


def test_reconcile_expands_history_to_find_a_stale_cursor() -> None:
    async def scenario():
        config = BehaviorLabConfig(context_size=2)
        base = Spin(value=1, event_id="base", source="history_api")
        missed = Spin(value=2, event_id="missed", source="history_api")
        newest = Spin(value=3, event_id="newest", source="history_api")
        source = FakeSource([base, missed, newest])
        worker = BehaviorLabWorker(
            config=config,
            source=source,
            store=RedisStateStore(config, redis_client=FakeRedis()),
        )
        worker.engine = BehaviorEngine(config, rules=[])
        worker.engine.process(base, source="bootstrap")
        worker.engine.reset_prospective_metrics()

        assert await worker.reconcile() == 2
        assert [spin.event_id for spin in worker.engine.history] == ["missed", "newest"]
        assert source.requested_limits == [2, 50_000]

    asyncio.run(scenario())


def test_identityless_websocket_copy_is_not_counted_twice() -> None:
    async def scenario():
        config = BehaviorLabConfig()
        base = Spin(value=1, event_id="base", source="history_api")
        persisted = Spin(value=14, event_id="persisted", source="history_api")
        source = FakeSource([base, persisted])
        worker = BehaviorLabWorker(
            config=config,
            source=source,
            store=RedisStateStore(config, redis_client=FakeRedis()),
        )
        worker.engine = BehaviorEngine(config, rules=[])
        worker.engine.process(base, source="bootstrap")
        worker.engine.reset_prospective_metrics()

        accepted = await worker.process_websocket_event(
            Spin(value=14, source="websocket")
        )

        assert accepted == 1
        assert [spin.event_id for spin in worker.engine.history] == ["base", "persisted"]
        assert worker.engine.prospective_spins == 1

    asyncio.run(scenario())
