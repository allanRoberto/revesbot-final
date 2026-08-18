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
            {"gameId": "new", "result": "17", "slots": {"17": 500, "2": 100}},
            {"gameId": "old", "result": "8"},
        ],
    })
    subscription = {"sent": False}
    assert collector.process_message(FakeWebSocket(), message, subscription) == 2
    assert [item.external_game_id for item in repository.documents] == ["old", "new"]
    assert [item["result"] for item in publisher.payloads] == [8, 17]
    assert repository.documents[0].slots == {}
    assert repository.documents[0].winning_multiplier is None
    assert repository.documents[1].slots == {"17": 500, "2": 100}
    assert repository.documents[1].winning_multiplier == 500
    assert repository.documents[1].as_document()["winning_multiplier"] == 500
    assert publisher.payloads[1]["full_result"]["slots"] == {"17": 500, "2": 100}
    assert publisher.payloads[1]["full_result"]["winning_multiplier"] == 500
    assert collector.process_message(FakeWebSocket(), message, subscription) == 0
    assert len(repository.documents) == 2


def test_slots_are_saved_without_false_multiplier_payment(monkeypatch):
    repository = FakeRepository()
    publisher = FakePublisher()
    collector = PragmaticCollector(
        settings(monkeypatch), repository, publisher, CollectorState()
    )
    message = json.dumps({
        "tableId": "204",
        "last20Results": [{
            "gameId": "mega-1",
            "result": "3",
            "slots": {"1": 100, "16": 100, "28": 50},
        }],
    })

    assert collector.process_message(FakeWebSocket(), message, {"sent": False}) == 1
    assert repository.documents[0].slots == {"1": 100, "16": 100, "28": 50}
    assert repository.documents[0].winning_multiplier is None
    assert publisher.payloads[0]["full_result"]["winning_multiplier"] is None


def test_invalid_slots_are_ignored(monkeypatch):
    repository = FakeRepository()
    collector = PragmaticCollector(
        settings(monkeypatch), repository, FakePublisher(), CollectorState()
    )
    message = json.dumps({
        "tableId": "204",
        "last20Results": [{
            "gameId": "mega-2",
            "result": "2",
            "slots": {"2": 100, "99": 500, "invalid": 50, "3": "200"},
        }],
    })

    assert collector.process_message(FakeWebSocket(), message, {"sent": False}) == 1
    assert repository.documents[0].slots == {"2": 100}
    assert repository.documents[0].winning_multiplier == 100


def test_catalog_response_sends_subscription(monkeypatch):
    collector = PragmaticCollector(settings(monkeypatch), FakeRepository(), FakePublisher(), CollectorState())
    socket = FakeWebSocket()
    subscription = {"sent": False}
    collector.process_message(socket, json.dumps({"tableKey": ["225"]}), subscription)
    assert subscription["sent"] is True
    assert socket.messages[0]["type"] == "subscribe"
    assert "225" in socket.messages[0]["key"]
