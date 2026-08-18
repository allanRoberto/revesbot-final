from __future__ import annotations

import json

from apps.collector.collector.config import CollectorSettings
from apps.collector.collector.providers.pragmatic import PragmaticCollector
from apps.collector.collector.state import CollectorState


class FakeRepository:
    def __init__(self):
        self.documents = []
        self.ids = set()

    def insert_if_new(self, result):
        key = (result.roulette_id, result.external_game_id)
        if key in self.ids:
            return False, "existing"
        self.ids.add(key)
        self.documents.append(result)
        return True, str(len(self.documents))


class FakePublisher:
    def __init__(self):
        self.payloads = []

    def publish(self, payload):
        self.payloads.append(json.loads(payload))
        return 1


class FakeWebSocket:
    def __init__(self):
        self.messages = []

    def send(self, payload):
        self.messages.append(json.loads(payload))


def settings(monkeypatch):
    monkeypatch.setenv("MONGO_URL", "mongodb://example")
    monkeypatch.setenv("REDIS_CONNECT", "redis://example")
    return CollectorSettings.from_env()


def test_snapshot_is_reconciled_oldest_first_and_is_idempotent(monkeypatch):
    repository = FakeRepository()
    publisher = FakePublisher()
    state = CollectorState()
    collector = PragmaticCollector(settings(monkeypatch), repository, publisher, state)
    message = json.dumps({
        "tableId": "225",
        "last20Results": [
            {"gameId": "new", "result": "17"},
            {"gameId": "old", "result": "8"},
        ],
    })
    subscription = {"sent": False}
    assert collector.process_message(FakeWebSocket(), message, subscription) == 2
    assert [item.external_game_id for item in repository.documents] == ["old", "new"]
    assert [item["result"] for item in publisher.payloads] == [8, 17]
    assert collector.process_message(FakeWebSocket(), message, subscription) == 0
    assert len(repository.documents) == 2


def test_catalog_response_sends_subscription(monkeypatch):
    collector = PragmaticCollector(settings(monkeypatch), FakeRepository(), FakePublisher(), CollectorState())
    socket = FakeWebSocket()
    subscription = {"sent": False}
    collector.process_message(socket, json.dumps({"tableKey": ["225"]}), subscription)
    assert subscription["sent"] is True
    assert socket.messages[0]["type"] == "subscribe"
    assert "225" in socket.messages[0]["key"]
