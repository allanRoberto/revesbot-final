from __future__ import annotations

import random
from datetime import datetime

from contextual_pairs.rules import pair_bet
from contextual_pairs.storage import (
    HEARTBEAT_KEY, HISTORY_KEY, OUTBOX_KEY, STATE_KEY, SUMMARY_KEY, VIEW_KEY, PairsRedisStore,
)
from contextual_pairs.tests.scripted import BET_37, NO_PAIR, PAIR_12, PAIR_37, PAIR_39, PROTECTION_37
from contextual_pairs.worker import PairsWorker
from contextual_ranking.engine import iso
from contextual_ranking.storage import decode, encode, to_mongo_document
from contextual_ranking.tests.fixtures import random_case
from contextual_ranking.tests.memory import (
    START, FakeSearch, FakeWriter, MemoryHistory, MemoryRedis, make_spins,
)
from contextual_ranking.worker import MAX_CATCHUP

BET_39 = pair_bet(PAIR_39)["bet"]
BET_12 = pair_bet(PAIR_12)["bet"]
OUTSIDE = [number for number in range(37) if number not in BET_37 and number not in BET_39]
INSIDE = 13  # in the 3-7 bet
INSIDE_39 = next(number for number in BET_39 if number not in BET_37)
FAR_NUMBERS = [OUTSIDE[index % len(OUTSIDE)] for index in range(13)]  # no number of the 3-7 or 3-9 bets among them
NUMBERS = [3, 26, 0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6]
# With this sequence and random_case(Random(4)) the real ranking has exactly two numbers from 0 to 9.
REAL_NUMBERS = [3, 26, 0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36]


def build(history, *, redis=None, writer=None, configured=True, search=None):
    redis = redis or MemoryRedis()
    worker = PairsWorker(
        history, PairsRedisStore(redis), search or (lambda *args: {}),
        search_configured=configured, writer=writer, clock=lambda: START,
    )
    return worker, redis


def closed_entries(redis):
    return [decode(raw) for raw in redis.lists.get(HISTORY_KEY, [])]


def view(redis):
    return decode(redis.values[VIEW_KEY])


def test_the_numbers_used_as_inside_and_outside_are_what_they_claim():
    assert INSIDE in BET_37 and len(OUTSIDE) >= MAX_CATCHUP + 1
    assert all(number not in BET_37 and number not in BET_39 for number in OUTSIDE)


def test_first_cycle_publishes_the_view_and_opens_a_signal(scripted):
    scripted([PAIR_37])
    worker, redis = build(MemoryHistory(make_spins(NUMBERS)), writer=FakeWriter())
    worker.run_once()
    page = view(redis)
    assert (page["screen"]["state"], page["screen"]["pair"], page["screen"]["bet"]) == ("opened", [3, 7], BET_37)
    [signal] = page["open_signals"]
    assert (signal["status"], signal["pair"], signal["bet"], signal["checks"]) == ("open", [3, 7], BET_37, [])
    assert redis.hashes[SUMMARY_KEY] == {"rankings": 1, "ranking_opened": 1, "tags_since": iso(START),
                                         "supremo_since": iso(START)}
    heartbeat = decode(redis.values[HEARTBEAT_KEY])
    assert heartbeat["status"] == "running"
    assert heartbeat["mongo"] == {"configured": True, "pending": 0, "last_error": None, "last_write_at": None}


def test_closed_signals_go_to_redis_and_to_mongodb_with_their_pair(scripted):
    scripted([PAIR_37, NO_PAIR])
    history, writer = MemoryHistory(make_spins(NUMBERS)), FakeWriter()
    worker, redis = build(history, writer=writer)
    worker.run_once()
    history.spins.append(make_spins([INSIDE], first=50)[0])
    worker.run_once()

    [entry] = closed_entries(redis)
    assert (entry["status"], entry["hit_attempt"], entry["hit_number"], entry["pair"]) == ("hit", 1, 13, [3, 7])
    # The trigger (6) is in this bet of 15 numbers: a medium bet with the exact near, so the watch tag counts it.
    assert redis.hashes[SUMMARY_KEY] == {
        "rankings": 2, "ranking_opened": 1, "ranking_no_pair": 1, "signals": 1, "hits": 1, "tags_since": iso(START),
        "supremo_since": iso(START), "tag_watch_12_15_exact_near_signals": 1, "tag_watch_12_15_exact_near_hits": 1,
    }
    assert redis.lists[OUTBOX_KEY] == []
    [document] = writer.documents.values()
    assert document["_id"] == entry["id"] and document["_id"].startswith("pairs-1-")
    assert (document["strategy"], document["strategy_version"]) == ("pairs", "pairs-1")
    assert (document["pair"], document["bet"], document["kept"]) == ([3, 7], BET_37, [13, 16, 27, 33])
    assert document["protection"] == PROTECTION_37 and document["protection_triples"] == [[21, 2, 25], [7, 28, 12]]
    assert entry["protection"] == PROTECTION_37
    # The quality tags and what they were decided from: in the page history and in MongoDB.
    assert entry["tags"] == document["tags"] == ["watch_12_15_exact_near"]
    assert entry["entry_context"] == document["entry_context"] == {"rule": 1, "chips": 15, "last_exact_distance": 1}
    assert isinstance(document["built_after"]["timestamp"], datetime)
    assert isinstance(document["checks"][0]["result"]["timestamp"], datetime)
    assert isinstance(document["created_at"], datetime) and isinstance(document["closed_at"], datetime)
    assert len(document["ranking"]) == 7
    # The analysis of the ranking is stored with the signal (dates as dates), never in the page history.
    assert "analysis" not in entry
    [searched] = document["analysis"]
    assert isinstance(searched["trigger"]["timestamp"], datetime)
    assert searched["trigger"]["history_id"] == document["built_after"]["history_id"]
    assert [row["id"] for row in searched["occurrences"]] == [f"occ-{document['built_after']['history_id']}"]


def test_tagged_signals_count_their_hits_and_misses_in_the_summary(scripted):
    # 3-9 is a bet of 11 numbers. Signal A opens after results far from the bet; B opens after 3 more results with the
    # last number of the bet 3 results back: both are high quality. A hits (round 1), B misses (7 rounds).
    scripted([PAIR_39, NO_PAIR, NO_PAIR, PAIR_39, NO_PAIR])
    history, writer = MemoryHistory(make_spins(FAR_NUMBERS)), FakeWriter()
    worker, redis = build(history, writer=writer)
    worker.run_once()
    assert view(redis)["screen"]["tags"] == ["high_quality"]
    [open_a] = view(redis)["open_signals"]
    assert (open_a["tags"], open_a["entry_context"]) == (
        ["high_quality"], {"rule": 1, "chips": 11, "last_exact_distance": None})
    assert "tag_high_quality_signals" not in redis.hashes[SUMMARY_KEY]  # only closed signals are counted

    history.spins.extend(make_spins([INSIDE_39, OUTSIDE[0], OUTSIDE[1]], first=50))
    worker.run_once()
    assert redis.hashes[SUMMARY_KEY]["tag_high_quality_signals"] == 1
    [open_b] = view(redis)["open_signals"]
    assert open_b["tags"] == ["high_quality"] and open_b["entry_context"]["last_exact_distance"] == 3

    for first, count in ((60, 4), (70, 3)):  # 7 results outside the bet, fed within the catch-up limit
        history.spins.extend(make_spins([OUTSIDE[(first + index) % len(OUTSIDE)] for index in range(count)], first=first))
        worker.run_once()
    summary = redis.hashes[SUMMARY_KEY]
    assert (summary["tag_high_quality_signals"], summary["tag_high_quality_hits"],
            summary["tag_high_quality_misses"]) == (2, 1, 1)
    assert summary["signals"] == 2 and summary["tags_since"] == iso(START)
    assert not any(name.startswith("tag_watch") for name in summary)
    by_status = {entry["status"]: entry for entry in closed_entries(redis)}
    assert by_status["hit"]["tags"] == by_status["miss"]["tags"] == ["high_quality"]
    assert {document["status"]: document["tags"] for document in writer.documents.values()} == {
        "hit": ["high_quality"], "miss": ["high_quality"]}


def test_untagged_signals_leave_the_tag_counters_alone(scripted):
    scripted([PAIR_12, NO_PAIR])  # the biggest bet (22 numbers) is never tagged
    history, writer = MemoryHistory(make_spins(FAR_NUMBERS)), FakeWriter()
    worker, redis = build(history, writer=writer)
    worker.run_once()
    assert view(redis)["screen"]["state"] == "opened" and view(redis)["screen"]["tags"] == []
    history.spins.append(make_spins([BET_12[0]], first=50)[0])
    worker.run_once()
    [entry] = closed_entries(redis)
    assert entry["status"] == "hit" and entry["tags"] == [] and entry["entry_context"]["chips"] == 22
    assert redis.hashes[SUMMARY_KEY] == {"rankings": 2, "ranking_opened": 1, "ranking_no_pair": 1, "signals": 1,
                                         "hits": 1, "tags_since": iso(START), "supremo_since": iso(START)}
    [document] = writer.documents.values()
    assert document["tags"] == [] and document["entry_context"]["chips"] == 22


def test_tags_since_is_written_once_and_kept(scripted):
    scripted([NO_PAIR])
    history = MemoryHistory(make_spins(FAR_NUMBERS))
    first_clock = START
    worker, redis = build(history)
    worker.run_once()
    assert redis.hashes[SUMMARY_KEY]["tags_since"] == iso(first_clock)
    later = PairsWorker(history, PairsRedisStore(redis), lambda *args: {}, search_configured=True,
                        clock=lambda: first_clock.replace(hour=20))
    history.spins.append(make_spins([OUTSIDE[0]], first=50)[0])
    later.run_once()
    assert decode(redis.values[VIEW_KEY])["updated_at"] == iso(first_clock.replace(hour=20))
    assert redis.hashes[SUMMARY_KEY]["tags_since"] == iso(first_clock)  # the first save set it; later ones keep it


def test_the_mongodb_document_converts_the_dates_of_the_analysis_and_leaves_other_signals_alone():
    trigger = make_spins([5], first=7)[0]
    signal = {"_id": "pairs-1-h0007", "built_after": trigger, "checks": [], "sources": [],
              "created_at": iso(START), "closed_at": None,
              "analysis": [{"trigger": trigger, "status": "ok", "occurrences": []}]}
    document = to_mongo_document(signal)
    assert isinstance(document["analysis"][0]["trigger"]["timestamp"], datetime)
    assert document["analysis"][0]["trigger"]["history_id"] == "h0007"
    assert isinstance(signal["analysis"][0]["trigger"]["timestamp"], str)  # the input is not changed
    without = {key: value for key, value in signal.items() if key != "analysis"}
    assert "analysis" not in to_mongo_document(without)  # ranking-page signals never had one


def test_closed_signals_wait_in_the_queue_while_mongodb_is_down(scripted):
    scripted([PAIR_37, NO_PAIR])
    history, writer = MemoryHistory(make_spins(NUMBERS)), FakeWriter()
    writer.failing = True
    worker, redis = build(history, writer=writer)
    worker.run_once()
    history.spins.append(make_spins([INSIDE], first=50)[0])
    worker.run_once()
    assert len(redis.lists[OUTBOX_KEY]) == 1
    heartbeat = decode(redis.values[HEARTBEAT_KEY])
    assert heartbeat["mongo"]["pending"] == 1 and "TimeoutError" in heartbeat["mongo"]["last_error"]

    writer.failing = False
    worker.run_once()
    assert redis.lists[OUTBOX_KEY] == [] and sorted(writer.documents) == [closed_entries(redis)[0]["id"]]
    assert decode(redis.values[HEARTBEAT_KEY])["mongo"]["last_error"] is None
    assert writer.documents[closed_entries(redis)[0]["id"]]["analysis"]  # the queue carried it along


def test_without_mongodb_configuration_closed_signals_stay_queued(scripted):
    scripted([PAIR_37, NO_PAIR])
    history = MemoryHistory(make_spins(NUMBERS))
    worker, redis = build(history, writer=None)
    worker.run_once()
    history.spins.append(make_spins([INSIDE], first=50)[0])
    worker.run_once()
    assert len(redis.lists[OUTBOX_KEY]) == 1
    assert decode(redis.values[HEARTBEAT_KEY])["mongo"]["configured"] is False


def test_restart_continues_from_redis_without_repeating_signals(scripted):
    scripted([PAIR_37, NO_PAIR, NO_PAIR, NO_PAIR])
    history = MemoryHistory(make_spins(NUMBERS))
    worker, redis = build(history)
    worker.run_once()
    history.spins.append(make_spins([INSIDE], first=50)[0])
    worker.run_once()
    before = closed_entries(redis)
    assert len(before) == 1

    restarted, _ = build(history, redis=redis)
    restarted.run_once()
    assert closed_entries(redis) == before
    history.spins.append(make_spins([OUTSIDE[0]], first=51)[0])
    restarted.run_once()
    assert decode(redis.values[STATE_KEY])["last_processed"]["history_id"] == "h0051"
    assert closed_entries(redis) == before


def test_a_long_gap_settles_open_signals_and_rebuilds_the_window(scripted):
    scripted([PAIR_37, PAIR_37])
    history = MemoryHistory(make_spins(NUMBERS))
    worker, redis = build(history)
    worker.run_once()
    [opened] = view(redis)["open_signals"]
    gap = [OUTSIDE[0], INSIDE] + OUTSIDE[1:MAX_CATCHUP]  # MAX_CATCHUP + 1 results in total
    history.spins.extend(make_spins(gap, first=60))
    worker.run_once()

    [settled] = closed_entries(redis)
    assert (settled["id"], settled["status"], settled["hit_attempt"]) == (opened["id"], "hit", 2)
    state = decode(redis.values[STATE_KEY])
    assert state["last_processed"]["history_id"] == history.spins[-1]["history_id"]
    [current] = view(redis)["open_signals"]  # the pair was released, the rebuilt ranking opened it again
    assert current["id"] != opened["id"] and current["built_after"]["history_id"] == history.spins[-1]["history_id"]


def test_state_from_another_pairs_version_is_rebuilt_without_carrying_its_signals(scripted):
    scripted([PAIR_37])
    history = MemoryHistory(make_spins(NUMBERS))
    worker, redis = build(history)
    worker.run_once()
    state = decode(redis.values[STATE_KEY])
    redis.values[STATE_KEY] = encode({**state, "pairs_version": 0})
    restarted, _ = build(history, redis=redis)
    restarted.run_once()
    assert decode(redis.values[STATE_KEY])["pairs_version"] == 1
    assert len(view(redis)["open_signals"]) == 1


def test_missing_search_token_is_reported_without_processing(scripted):
    scripted([PAIR_37])
    worker, redis = build(MemoryHistory(make_spins(NUMBERS)), configured=False)
    worker.run_once()
    assert decode(redis.values[HEARTBEAT_KEY])["status"] == "config_pending"
    assert VIEW_KEY not in redis.values


def test_real_ranking_engine_keeps_the_pair_rules_on_every_result():
    case = random_case(random.Random(4))
    history, writer = MemoryHistory(make_spins(REAL_NUMBERS)), FakeWriter()
    worker, redis = build(history, writer=writer, search=FakeSearch(case["occurrences"]))
    worker.run_once()
    assert view(redis)["screen"]["state"] == "opened"

    rng = random.Random(11)
    for index in range(80):
        history.spins.append(make_spins([rng.randrange(37)], first=100 + index)[0])
        worker.run_once()
        state = decode(redis.values[STATE_KEY])
        keys = [signal["pair_key"] for signal in state["pair_signals"]]
        assert len(keys) == len(set(keys)), "two open signals with the same pair"
        assert state["open_signals"] == []
        for signal in state["pair_signals"]:
            info = pair_bet(signal["top_numbers"])
            assert (info["kind"], signal["bet"], signal["pair"]) == ("ok", info["bet"], info["pair"])
            assert signal["status"] == "open" and 0 <= len(signal["checks"]) < 7
            assert not any(check["hit"] for check in signal["checks"])

    closed = closed_entries(redis)
    assert closed and len({entry["id"] for entry in closed}) == len(closed)
    for entry in closed:
        hits = [check["hit"] for check in entry["checks"]]
        assert 1 <= len(hits) <= 7
        assert (entry["status"] == "hit") == hits[-1] and not any(hits[:-1])
        assert entry["status"] == "hit" or len(hits) == 7
    assert sorted(writer.documents) == sorted(entry["id"] for entry in closed)
    for document in writer.documents.values():
        # The stored analysis is the one behind the stored sources: same searches, same chosen occurrences.
        analysis = document["analysis"]
        assert len(analysis) == 5 and all(isinstance(entry["trigger"]["timestamp"], datetime) for entry in analysis)
        assert all(entry["status"] == "ok" for entry in analysis)
        assert [entry["trigger"]["history_id"] for entry in analysis] == \
            [source["trigger"]["history_id"] for source in document["sources"]]
        assert [[row["id"] for row in entry["occurrences"]] for entry in analysis] == \
            [source["occurrence_ids"] for source in document["sources"]]
    # The tags and the entry context, recomputed from the results the worker was fed (the 10 latest up to the trigger).
    positions = {item["history_id"]: index for index, item in enumerate(history.spins)}
    tagged = {"high_quality": [0, 0], "watch_12_15_exact_near": [0, 0]}
    supremo = {"signals": 0, "hits": 0, "staked": 0, "net": 0}
    for document in writer.documents.values():
        end = positions[document["built_after"]["history_id"]] + 1
        latest = [item["number"] for item in history.spins[end - 10:end]]
        distance = next((back for back, number in enumerate(reversed(latest), start=1)
                         if number in document["bet"]), None)
        near = distance is not None and distance <= 2
        chips = len(document["bet"])
        expected = [tag for tag, condition in (("high_quality", 8 <= chips <= 11 and not near),
                                               ("watch_12_15_exact_near", 12 <= chips <= 15 and near)) if condition]
        assert document["entry_context"] == {"rule": 1, "chips": chips, "last_exact_distance": distance}
        # Supremo, recomputed from the ranking: the digit of the sum of its 7 numbers and the size of the bet.
        total = sum(document["top_numbers"])
        root = total
        while root >= 10:
            root = sum(int(digit) for digit in str(root))
        play_until = {5: 2, 6: 2, 7: 1}.get(root)
        assert document["supremo"] == {"rule": 1, "chips": chips, "rank_sum": total, "rank_root": root,
                                       "play_until": play_until}
        is_supremo = play_until is not None and chips in (9, 10, 11, 14, 19, 20, 21, 22)
        assert document["tags"] == expected + (["supremo"] if is_supremo else [])
        if is_supremo:
            attempt = document["hit_attempt"] if document["hit"] else None
            won = attempt is not None and attempt <= play_until
            played = attempt if won else play_until
            supremo["signals"] += 1
            supremo["hits"] += won
            supremo["staked"] += chips * played
            supremo["net"] += (36 if won else 0) - chips * played
        for tag in expected:
            tagged[tag][0] += 1
            tagged[tag][1] += bool(document["hit"])
    summary = redis.hashes[SUMMARY_KEY]
    assert all(signals for signals, _ in tagged.values()), "the random run should meet both tags"
    for tag, (signals, hits) in tagged.items():
        assert (summary.get(f"tag_{tag}_signals", 0), summary.get(f"tag_{tag}_hits", 0)) == (signals, hits)
    assert supremo["signals"], "the random run should meet the Supremo tag"
    assert {name: summary.get(f"tag_supremo_{name}", 0) for name in supremo} == supremo
    assert summary.get("tag_supremo_misses", 0) == supremo["signals"] - supremo["hits"]
    assert summary["tags_since"] == summary["supremo_since"] == iso(START)
    assert summary["rankings"] == 81 and summary["signals"] == len(closed)
    assert summary["ranking_opened"] + summary.get("ranking_active", 0) + summary.get("ranking_no_pair", 0) \
        + summary.get("ranking_too_many", 0) + summary.get("ranking_no_intersection", 0) == 81
