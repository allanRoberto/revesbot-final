from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from apps.collector.collector.config import CollectorSettings
from apps.collector.collector.models import RouletteResult
from apps.collector.collector.providers.pragmatic import PragmaticCollector
from apps.collector.collector.state import CollectorState


class FakeRepository:
    def __init__(self, documents=None):
        self.documents = list(documents or [])
        self.ids = {
            (item.roulette_id, item.external_game_id)
            for item in self.documents
        }

    def insert_if_new(self, result):
        key = (result.roulette_id, result.external_game_id)
        if key in self.ids:
            return False, "existing"
        self.ids.add(key)
        self.documents.append(result)
        return True, str(len(self.documents))

    def recent_results(self, roulette_id, limit=20):
        rows = [item for item in self.documents if item.roulette_id == roulette_id]
        return [
            {
                "external_game_id": item.external_game_id,
                "timestamp": item.timestamp,
            }
            for item in reversed(rows[-limit:])
        ]


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


def test_empty_database_starts_with_only_the_newest_result(monkeypatch):
    repository = FakeRepository()
    publisher = FakePublisher()
    state = CollectorState()
    collector = PragmaticCollector(settings(monkeypatch), repository, publisher, state)
    message = json.dumps({
        "tableId": "225",
        "last20Results": [
            {
                "gameId": "new", "result": "17", "time": "Aug 18, 2026 6:11:14 PM",
                "slots": {"17": 500, "2": 100},
            },
            {"gameId": "old", "result": "8", "time": "Aug 18, 2026 6:10:34 PM"},
        ],
    })
    subscription = {"sent": False}
    assert collector.process_message(FakeWebSocket(), message, subscription) == 1
    assert [item.external_game_id for item in repository.documents] == ["new"]
    assert [item["result"] for item in publisher.payloads] == [17]
    assert repository.documents[0].slots == {"17": 500, "2": 100}
    assert repository.documents[0].winning_multiplier == 500
    assert repository.documents[0].recovered is False
    assert repository.documents[0].timestamp == datetime(2026, 8, 18, 18, 11, 14, tzinfo=UTC)
    assert repository.documents[0].timestamp_source == "provider"
    assert repository.documents[0].as_document()["winning_multiplier"] == 500
    assert publisher.payloads[0]["full_result"]["slots"] == {"17": 500, "2": 100}
    assert publisher.payloads[0]["full_result"]["winning_multiplier"] == 500
    assert collector.process_message(FakeWebSocket(), message, subscription) == 0
    assert len(repository.documents) == 1


def test_reconnect_recovers_only_missing_ids_using_provider_times(monkeypatch):
    now = datetime.now(UTC)
    roulette_id = "pragmatic-auto-roulette"
    seeded = [
        RouletteResult(roulette_id, 1, now - timedelta(seconds=380), "older-2"),
        RouletteResult(roulette_id, 2, now - timedelta(seconds=340), "older-1"),
        RouletteResult(roulette_id, 3, now - timedelta(seconds=300), "anchor"),
    ]
    repository = FakeRepository(seeded)
    publisher = FakePublisher()
    state = CollectorState()
    collector = PragmaticCollector(settings(monkeypatch), repository, publisher, state)
    message = json.dumps({
        "tableId": "225",
        "last20Results": [
            {"gameId": "missing-5", "result": "8", "time": "Aug 18, 2026 6:14:34 PM"},
            {"gameId": "missing-4", "result": "8", "time": "Aug 18, 2026 6:13:54 PM"},
            {"gameId": "missing-3", "result": "6", "time": "Aug 18, 2026 6:13:14 PM"},
            {"gameId": "missing-2", "result": "5", "time": "Aug 18, 2026 6:12:34 PM"},
            {"gameId": "missing-1", "result": "4", "time": "Aug 18, 2026 6:11:54 PM"},
            {"gameId": "anchor", "result": "3", "time": "Aug 18, 2026 6:11:14 PM"},
            {"gameId": "older-1", "result": "2", "time": "Aug 18, 2026 6:10:34 PM"},
        ],
    })

    assert collector.process_message(FakeWebSocket(), message, {"sent": False}) == 5
    recovered = repository.documents[3:]
    assert [item.external_game_id for item in recovered] == [
        "missing-1", "missing-2", "missing-3", "missing-4", "missing-5"
    ]
    assert [item.value for item in recovered[-2:]] == [8, 8]
    assert all(item.recovered for item in recovered)
    assert all(item.timestamp_source == "provider" for item in recovered)
    assert [item.timestamp for item in recovered] == [
        datetime(2026, 8, 18, 18, 11, 54, tzinfo=UTC),
        datetime(2026, 8, 18, 18, 12, 34, tzinfo=UTC),
        datetime(2026, 8, 18, 18, 13, 14, tzinfo=UTC),
        datetime(2026, 8, 18, 18, 13, 54, tzinfo=UTC),
        datetime(2026, 8, 18, 18, 14, 34, tzinfo=UTC),
    ]
    assert publisher.payloads == []
    assert state.recovered_results_total == 5
    assert state.recovery_failures_total == 0


def test_live_capture_resumes_after_snapshot_reconciliation(monkeypatch):
    now = datetime.now(UTC)
    roulette_id = "pragmatic-auto-roulette"
    repository = FakeRepository([
        RouletteResult(roulette_id, 3, now - timedelta(seconds=40), "known")
    ])
    publisher = FakePublisher()
    collector = PragmaticCollector(
        settings(monkeypatch), repository, publisher, CollectorState()
    )
    subscription = {"sent": False}
    known = json.dumps({
        "tableId": "225",
        "last20Results": [
            {"gameId": "known", "result": "3", "time": "Aug 18, 2026 6:11:14 PM"}
        ],
    })
    live = json.dumps({
        "tableId": "225",
        "last20Results": [
            {"gameId": "live", "result": "4", "time": "Aug 18, 2026 6:11:54 PM"},
            {"gameId": "known", "result": "3", "time": "Aug 18, 2026 6:11:14 PM"},
        ],
    })

    assert collector.process_message(FakeWebSocket(), known, subscription) == 0
    assert collector.process_message(FakeWebSocket(), live, subscription) == 1
    assert repository.documents[-1].external_game_id == "live"
    assert repository.documents[-1].recovered is False
    assert repository.documents[-1].timestamp == repository.documents[-1].captured_at
    assert repository.documents[-1].timestamp_source == "captured"
    assert publisher.payloads[0]["full_result"]["recovered"] is False


def test_exhausted_recovery_window_is_marked_and_salvages_snapshot(monkeypatch):
    now = datetime.now(UTC)
    roulette_id = "pragmatic-auto-roulette"
    repository = FakeRepository([
        RouletteResult(roulette_id, 1, now - timedelta(seconds=160), "stored-2"),
        RouletteResult(roulette_id, 2, now - timedelta(seconds=120), "stored-1"),
    ])
    state = CollectorState()
    collector = PragmaticCollector(
        settings(monkeypatch), repository, FakePublisher(), state
    )
    message = json.dumps({
        "tableId": "225",
        "last20Results": [
            {"gameId": "available-2", "result": "4", "time": "Aug 18, 2026 6:11:54 PM"},
            {"gameId": "available-1", "result": "3", "time": "Aug 18, 2026 6:11:14 PM"},
        ],
    })

    assert collector.process_message(FakeWebSocket(), message, {"sent": False}) == 2
    assert [item.external_game_id for item in repository.documents[-2:]] == [
        "available-1", "available-2"
    ]
    assert all(item.recovered for item in repository.documents[-2:])
    assert state.recovery_failures_total == 1
    assert "recovery_window_exhausted" in (state.last_error or "")


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
            "time": "Aug 18, 2026 6:11:14 PM",
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
            "time": "Aug 18, 2026 6:11:14 PM",
            "slots": {"2": 100, "99": 500, "invalid": 50, "3": "200"},
        }],
    })

    assert collector.process_message(FakeWebSocket(), message, {"sent": False}) == 1
    assert repository.documents[0].slots == {"2": 100}
    assert repository.documents[0].winning_multiplier == 100


def test_missing_provider_time_uses_auditable_capture_fallback(monkeypatch):
    repository = FakeRepository()
    state = CollectorState()
    collector = PragmaticCollector(
        settings(monkeypatch), repository, FakePublisher(), state
    )
    message = json.dumps({
        "tableId": "225",
        "last20Results": [{"gameId": "missing-time", "result": "2"}],
    })

    assert collector.process_message(FakeWebSocket(), message, {"sent": False}) == 1
    assert repository.documents[0].timestamp_source == "captured_fallback"
    assert repository.documents[0].timestamp == repository.documents[0].captured_at
    assert state.invalid_messages_total == 1
    assert "provider_timestamp_unusable" in (state.last_error or "")


def test_future_provider_time_is_rejected(monkeypatch):
    repository = FakeRepository()
    state = CollectorState()
    collector = PragmaticCollector(
        settings(monkeypatch), repository, FakePublisher(), state
    )
    message = json.dumps({
        "tableId": "225",
        "last20Results": [{
            "gameId": "future-time",
            "result": "2",
            "time": "Aug 18, 2099 8:19:18 PM",
        }],
    })

    assert collector.process_message(FakeWebSocket(), message, {"sent": False}) == 1
    assert repository.documents[0].timestamp_source == "captured_fallback"
    assert repository.documents[0].timestamp == repository.documents[0].captured_at
    assert "reason=future" in (state.last_error or "")


def test_catalog_response_sends_subscription(monkeypatch):
    collector = PragmaticCollector(settings(monkeypatch), FakeRepository(), FakePublisher(), CollectorState())
    socket = FakeWebSocket()
    subscription = {"sent": False}
    collector.process_message(socket, json.dumps({"tableKey": ["225"]}), subscription)
    assert subscription["sent"] is True
    assert socket.messages[0]["type"] == "subscribe"
    assert "225" in socket.messages[0]["key"]
