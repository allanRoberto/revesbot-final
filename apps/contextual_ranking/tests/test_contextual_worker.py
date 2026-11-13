from __future__ import annotations

from datetime import datetime

import pytest

from contextual_ranking import STRATEGY_VERSION
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


def view(redis):
    return decode(redis.values[VIEW_KEY])


def closed_signals(redis):
    return [decode(raw) for raw in redis.lists.get(HISTORY_KEY, [])]


def oldest_open_top(redis):
    return view(redis)["open_signals"][-1]["top_numbers"]


def test_first_cycle_publishes_the_ranking_and_opens_a_signal():
    worker, redis = build(MemoryHistory(make_spins(NUMBERS)), writer=FakeWriter())
    worker.run_once()
    page = view(redis)
    assert len(page["ranking"]["top"]) == 7
    assert [item["number"] for item in page["last_numbers"]] == list(reversed(NUMBERS[-3:]))
    [signal] = page["open_signals"]
    assert (signal["status"], signal["checks"]) == ("open", [])
    assert signal["top_numbers"] == [row["number"] for row in page["ranking"]["top"]]
    assert closed_signals(redis) == []
    heartbeat = decode(redis.values[HEARTBEAT_KEY])
    assert heartbeat["status"] == "running"
    assert heartbeat["mongo"] == {"configured": True, "pending": 0, "last_error": None, "last_write_at": None}


def test_signals_stay_open_until_a_hit_and_are_then_saved_in_redis_and_mongodb():
    history = MemoryHistory(make_spins(NUMBERS))
    writer = FakeWriter()
    worker, redis = build(history, writer=writer)
    worker.run_once()
    first_top = oldest_open_top(redis)

    history.spins.append(make_spins([next(n for n in range(37) if n not in first_top)], first=50)[0])
    worker.run_once()
    page = view(redis)
    assert closed_signals(redis) == []
    oldest = page["open_signals"][-1]
    assert oldest["top_numbers"] == first_top and len(oldest["checks"]) == 1

    history.spins.append(make_spins([first_top[2]], first=51)[0])
    worker.run_once()
    finished = {item["id"]: item for item in closed_signals(redis)}
    signal = finished[oldest["id"]]
    assert (signal["status"], signal["hit_attempt"], signal["hit_position"]) == ("hit", 2, 3)
    assert [check["hit"] for check in signal["checks"]] == [False, True]
    assert int(redis.hashes[SUMMARY_KEY]["hits"]) >= 1
    assert redis.lists.get(OUTBOX_KEY) == []
    document = writer.documents[oldest["id"]]
    assert document["strategy_version"] == STRATEGY_VERSION
    assert isinstance(document["built_after"]["timestamp"], datetime)
    assert isinstance(document["checks"][0]["result"]["timestamp"], datetime)
    assert isinstance(document["closed_at"], datetime)
    assert oldest["id"] not in [item["id"] for item in view(redis)["open_signals"]]


def test_closed_signals_wait_in_the_queue_while_mongodb_is_down():
    history = MemoryHistory(make_spins(NUMBERS))
    writer = FakeWriter()
    writer.failing = True
    worker, redis = build(history, writer=writer)
    worker.run_once()
    history.spins.append(make_spins([oldest_open_top(redis)[0]], first=50)[0])
    worker.run_once()
    pending = len(redis.lists[OUTBOX_KEY])
    assert pending >= 1
    heartbeat = decode(redis.values[HEARTBEAT_KEY])
    assert heartbeat["mongo"]["pending"] == pending
    assert "TimeoutError" in heartbeat["mongo"]["last_error"]

    writer.failing = False
    worker.run_once()
    assert redis.lists[OUTBOX_KEY] == []
    assert sorted(writer.documents) == sorted(item["id"] for item in closed_signals(redis))
    assert decode(redis.values[HEARTBEAT_KEY])["mongo"]["last_error"] is None


def test_without_mongodb_configuration_closed_signals_stay_queued():
    history = MemoryHistory(make_spins(NUMBERS))
    worker, redis = build(history, writer=None)
    worker.run_once()
    history.spins.append(make_spins([oldest_open_top(redis)[0]], first=50)[0])
    worker.run_once()
    assert len(redis.lists[OUTBOX_KEY]) >= 1
    assert decode(redis.values[HEARTBEAT_KEY])["mongo"]["configured"] is False


def test_long_gap_settles_open_signals_then_rebuilds_without_new_signals_for_the_gap():
    history = MemoryHistory(make_spins(NUMBERS))
    worker, redis = build(history)
    worker.run_once()
    [opened] = view(redis)["open_signals"]
    version = decode(redis.values[STATE_KEY])["version"]
    gap = [opened["top_numbers"][0]] + [n for n in range(37) if n not in opened["top_numbers"]][:MAX_CATCHUP]
    history.spins.extend(make_spins(gap, first=60))
    worker.run_once()

    [settled] = closed_signals(redis)
    assert (settled["id"], settled["status"], settled["hit_attempt"]) == (opened["id"], "hit", 1)
    state = decode(redis.values[STATE_KEY])
    assert state["last_processed"]["history_id"] == history.spins[-1]["history_id"]
    assert state["version"] == version + 1
    [current] = view(redis)["open_signals"]
    assert current["built_after"]["history_id"] == history.spins[-1]["history_id"]


def test_restart_continues_from_redis_without_repeating_signals():
    history = MemoryHistory(make_spins(NUMBERS))
    worker, redis = build(history)
    worker.run_once()
    history.spins.append(make_spins([oldest_open_top(redis)[0]], first=50)[0])
    worker.run_once()
    before = closed_signals(redis)

    restarted, _ = build(history, redis=redis)
    restarted.run_once()
    assert closed_signals(redis) == before
    history.spins.append(make_spins([oldest_open_top(redis)[0]], first=51)[0])
    restarted.run_once()
    assert len(closed_signals(redis)) > len(before)


def test_failed_save_neither_skips_nor_repeats_results():
    history = MemoryHistory(make_spins(NUMBERS))
    worker, redis = build(history)
    worker.run_once()
    top = oldest_open_top(redis)
    history.spins.extend(make_spins([top[0], top[1]], first=70))
    redis.fail_next_execute = True
    with pytest.raises(ConnectionError):
        worker.run_once()
    assert closed_signals(redis) == []
    worker.run_once()
    state = decode(redis.values[STATE_KEY])
    assert state["last_processed"]["history_id"] == history.spins[-1]["history_id"]
    ids = [item["id"] for item in closed_signals(redis)]
    assert len(ids) == len(set(ids)) >= 1


def test_missing_search_token_is_reported_without_processing():
    worker, redis = build(MemoryHistory(make_spins(NUMBERS)), configured=False)
    worker.run_once()
    assert decode(redis.values[HEARTBEAT_KEY])["status"] == "config_pending"
    assert VIEW_KEY not in redis.values
