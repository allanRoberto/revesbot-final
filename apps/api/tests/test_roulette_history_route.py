from __future__ import annotations

import asyncio
from datetime import datetime

import pytz
from bson import ObjectId

from api.routes import roulette_history


class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    async def to_list(self, length=None):
        return list(self._docs)


class _FakeCollection:
    def __init__(self, docs):
        self._docs = docs

    def find(self, *args, **kwargs):
        return _FakeCursor(self._docs)


class _FakeRequest:
    def __init__(self):
        self.headers = {"accept": "application/json"}


def test_get_history_detailed_serializes_object_id(monkeypatch) -> None:
    docs = [
        {
            "_id": ObjectId(),
            "roulette_id": "pragmatic-brazilian-roulette",
            "roulette_name": "Pragmatic Brazilian Roulette",
            "value": 19,
            "timestamp": pytz.utc.localize(datetime(2026, 3, 29, 12, 0, 0)),
        }
    ]
    monkeypatch.setattr(roulette_history, "history_coll", _FakeCollection(docs))

    result = asyncio.run(
        roulette_history.get_history_detailed(
            "pragmatic-brazilian-roulette",
            _FakeRequest(),
            limit=10,
        )
    )

    assert isinstance(result, list)
    assert result[0]["_id"] == str(docs[0]["_id"])
    assert result[0]["value"] == 19
