from __future__ import annotations

import asyncio
import json

from api.routes import suggestion_monitor


class _FakeAsyncCollection:
    def __init__(self, count: int, docs: list[dict] | None = None) -> None:
        self._count = count
        self._docs = docs or []
        self.deleted_filters = []

    async def count_documents(self, filter_query):
        return self._count

    async def delete_many(self, filter_query):
        self.deleted_filters.append(dict(filter_query))
        return None

    def find(self, *args, **kwargs):
        return self

    async def to_list(self, length=None):
        return list(self._docs)


class _FakeRedis:
    def __init__(self) -> None:
        self.published = []

    async def publish(self, channel: str, payload: str) -> int:
        self.published.append((channel, json.loads(payload)))
        return 1


def test_reset_suggestion_monitor_clears_collections_and_publishes_control(monkeypatch) -> None:
    fake_events = _FakeAsyncCollection(10, docs=[{"_id": "evt-1"}, {"_id": "evt-2"}])
    fake_attempts = _FakeAsyncCollection(40)
    fake_patterns = _FakeAsyncCollection(30)
    fake_offsets = _FakeAsyncCollection(1)
    fake_redis = _FakeRedis()

    monkeypatch.setattr(suggestion_monitor, "suggestion_monitor_events_coll", fake_events)
    monkeypatch.setattr(suggestion_monitor, "suggestion_monitor_attempts_coll", fake_attempts)
    monkeypatch.setattr(suggestion_monitor, "suggestion_monitor_pattern_outcomes_coll", fake_patterns)
    monkeypatch.setattr(suggestion_monitor, "suggestion_monitor_offsets_coll", fake_offsets)
    monkeypatch.setattr(suggestion_monitor, "redis_client", fake_redis)

    result = asyncio.run(
        suggestion_monitor.reset_suggestion_monitor(
            roulette_id="pragmatic-auto-roulette",
            config_key=None,
        )
    )

    assert result["deleted_events"] == 2
    assert result["deleted_attempts"] == 40
    assert result["deleted_patterns"] == 30
    assert result["deleted_offsets"] == 1
    assert result["published_reset_signal"] == 1
    assert fake_redis.published[0][0] == suggestion_monitor.SUGGESTION_MONITOR_CONTROL_CHANNEL
    assert fake_redis.published[0][1]["action"] == "reset_monitor"
