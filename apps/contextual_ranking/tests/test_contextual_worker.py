from __future__ import annotations

from datetime import datetime

import pytest

from contextual_ranking.storage import (
    HEARTBEAT_KEY, HISTORY_KEY, OUTBOX_KEY, STATE_KEY, SUMMARY_KEY, VIEW_KEY, RedisStore, decode,
)
from contextual_ranking.tests.fixtures import production_occurrences
from contextual_ranking.tests.memory import (
    START, FakeSearch, FakeWriter, MemoryHistory, MemoryRedis, make_spins,
)
from contextual_ranking.worker import MAX_CATCHUP, ContextualRankingWorker

NUMBERS = [3, 26, 0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36]


def build(history, *, redis=None, writer=None, configured=True):
    redis = redis or MemoryRedis()
    worker = ContextualRankingWorker(
        history, RedisStore(redis), FakeSearch(production_occurrences()),
        search_configured=configured, writer=writer, clock=lambda: START,
    )
    return worker, redis


def top_numbers(redis):
    return [row["number"] for row in decode(redis.values[VIEW_KEY])["ranking"]["top"]]


def signals(redis):
    return [decode(raw) for raw in redis.lists.get(HISTORY_KEY, [])]


def test_first_cycle_publishes_the_ranking_without_signals():
    worker, redis = build(MemoryHistory(make_spins(NUMBERS)), writer=FakeWriter())
    worker.run_once()
    view = decode(redis.values[VIEW_KEY])
    assert len(view["ranking"]["top"]) == 7
    assert [item["number"] for item in view["last_numbers"]] == list(reversed(NUMBERS[-3:]))
    assert signals(redis) == []
    heartbeat = decode(redis.values[HEARTBEAT_KEY])
    assert heartbeat["status"] == "running"
    assert heartbeat["mongo"] == {"configured": True, "pending": 0, "last_error": None, "last_write_at": None}


def test_every_new_result_becomes_one_signal_in_redis_and_mongodb():
    history = MemoryHistory(make_spins(NUMBERS))
    writer = FakeWriter()
    worker, redis = build(history, writer=writer)
    worker.run_once()

    on_air = top_numbers(redis)
    history.spins.append(make_spins([on_air[0]], first=50)[0])
    worker.run_once()
    [first] = signals(redis)
    assert (first["hit"], first["hit_position"], first["top_numbers"]) == (True, 1, on_air)
    assert redis.hashes[SUMMARY_KEY] == {"signals": 1, "hits": 1}
    assert redis.lists.get(OUTBOX_KEY) == []
    document = writer.documents[first["id"]]
    assert isinstance(document["result"]["timestamp"], datetime)
    assert isinstance(document["created_at"], datetime)
    assert len(document["ranking"]) == 37

    on_air = top_numbers(redis)
    history.spins.append(make_spins([next(n for n in range(37) if n not in on_air)], first=51)[0])
    worker.run_once()
    assert [item["hit"] for item in signals(redis)] == [False, True]
    assert redis.hashes[SUMMARY_KEY] == {"signals": 2, "hits": 1, "misses": 1}
    assert len(writer.documents) == 2
    view = decode(redis.values[VIEW_KEY])
    assert [item["hit"] for item in view["last_numbers"][:2]] == [False, True]


def test_signals_wait_in_the_queue_while_mongodb_is_down():
    history = MemoryHistory(make_spins(NUMBERS))
    writer = FakeWriter()
    writer.failing = True
    worker, redis = build(history, writer=writer)
    worker.run_once()
    history.spins.extend(make_spins([1, 2], first=50))
    worker.run_once()
    assert len(redis.lists[OUTBOX_KEY]) == 2
    heartbeat = decode(redis.values[HEARTBEAT_KEY])
    assert heartbeat["mongo"]["pending"] == 2
    assert "TimeoutError" in heartbeat["mongo"]["last_error"]

    writer.failing = False
    worker.run_once()
    assert redis.lists[OUTBOX_KEY] == []
    assert sorted(writer.documents) == sorted(item["id"] for item in signals(redis))
    assert decode(redis.values[HEARTBEAT_KEY])["mongo"]["last_error"] is None


def test_without_mongodb_configuration_signals_stay_queued():
    history = MemoryHistory(make_spins(NUMBERS))
    worker, redis = build(history, writer=None)
    worker.run_once()
    history.spins.append(make_spins([1], first=50)[0])
    worker.run_once()
    assert len(redis.lists[OUTBOX_KEY]) == 1
    assert decode(redis.values[HEARTBEAT_KEY])["mongo"]["configured"] is False


def test_long_gap_rebuilds_the_window_without_inventing_signals():
    history = MemoryHistory(make_spins(NUMBERS))
    worker, redis = build(history)
    worker.run_once()
    version = decode(redis.values[STATE_KEY])["version"]
    history.spins.extend(make_spins(list(range(MAX_CATCHUP + 1)), first=60))
    worker.run_once()
    state = decode(redis.values[STATE_KEY])
    assert signals(redis) == []
    assert state["last_processed"]["history_id"] == history.spins[-1]["history_id"]
    assert state["version"] == version + 1


def test_restart_continues_from_redis_without_repeating_signals():
    history = MemoryHistory(make_spins(NUMBERS))
    worker, redis = build(history)
    worker.run_once()
    history.spins.append(make_spins([4], first=50)[0])
    worker.run_once()

    restarted, _ = build(history, redis=redis)
    restarted.run_once()
    assert len(signals(redis)) == 1
    history.spins.append(make_spins([21], first=51)[0])
    restarted.run_once()
    assert len(signals(redis)) == 2


def test_failed_save_neither_skips_nor_repeats_results():
    history = MemoryHistory(make_spins(NUMBERS))
    worker, redis = build(history)
    worker.run_once()
    history.spins.extend(make_spins([4, 21], first=70))
    redis.fail_next_execute = True
    with pytest.raises(ConnectionError):
        worker.run_once()
    assert signals(redis) == []
    worker.run_once()
    assert [item["result"]["number"] for item in signals(redis)] == [21, 4]


def test_missing_search_token_is_reported_without_processing():
    worker, redis = build(MemoryHistory(make_spins(NUMBERS)), configured=False)
    worker.run_once()
    assert decode(redis.values[HEARTBEAT_KEY])["status"] == "config_pending"
    assert VIEW_KEY not in redis.values
