from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from api.services.jev_history_service import JevHistorySourceError, fetch_recent_history


class FakeCursor:
    def __init__(self, documents):
        self.documents = list(documents)
        self.sort_spec = None
        self.limit_value = None

    def sort(self, spec):
        self.sort_spec = spec
        return self

    def limit(self, amount):
        self.limit_value = amount
        return self

    async def to_list(self, length=None):
        return self.documents[:length]


class FakeCollection:
    def __init__(self, documents):
        self.cursor = FakeCursor(documents)
        self.query = None
        self.projection = None

    def find(self, query, projection):
        self.query = query
        self.projection = projection
        return self.cursor


def test_history_selects_newest_then_returns_oldest_first_without_deduplication() -> None:
    base = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
    collection = FakeCollection(
        [
            {"value": 7, "timestamp": base},
            {"value": 7, "timestamp": base - timedelta(seconds=10)},
            {"value": 7, "timestamp": base - timedelta(seconds=20)},
        ]
    )
    result = asyncio.run(fetch_recent_history(collection, 3))

    assert collection.query == {"roulette_id": "pragmatic-auto-roulette"}
    assert collection.cursor.sort_spec == [("timestamp", -1), ("_id", -1)]
    assert collection.cursor.limit_value == 3
    assert result["historico"] == [7, 7, 7]
    assert result["history_order"] == "oldest_to_newest"
    assert result["quantidade_retornada"] == 3
    assert result["ultimo_resultado_em"] == "2026-09-25T12:00:00Z"


def test_history_returns_fewer_or_empty_without_fabricating_values() -> None:
    one = asyncio.run(fetch_recent_history(FakeCollection([{"value": 2}]), 50))
    empty = asyncio.run(fetch_recent_history(FakeCollection([]), 50))
    assert one["historico"] == [2]
    assert one["quantidade_solicitada"] == 50
    assert one["quantidade_retornada"] == 1
    assert one["ultimo_resultado_em"] is None
    assert empty["historico"] == []
    assert empty["quantidade_retornada"] == 0


@pytest.mark.parametrize("document", [{"value": True}, {"value": "7"}, {"value": 37}, {}])
def test_history_rejects_invalid_source_records(document) -> None:
    with pytest.raises(JevHistorySourceError):
        asyncio.run(fetch_recent_history(FakeCollection([document]), 1))


def test_history_exposes_source_failure_without_fallback() -> None:
    class BrokenCollection:
        def find(self, *_args, **_kwargs):
            raise RuntimeError("database unavailable")

    with pytest.raises(JevHistorySourceError):
        asyncio.run(fetch_recent_history(BrokenCollection(), 10))
