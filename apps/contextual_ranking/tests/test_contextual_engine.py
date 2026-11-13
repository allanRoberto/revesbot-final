from __future__ import annotations

from contextual_ranking.engine import (
    OCCURRENCES_PER_SEARCH, SPIN_MEMORY, WINDOW_SEARCHES, build_view, parse_time, process, rebuild,
)
from contextual_ranking.rules import analyze_occurrences, rank_following, sort_occurrences
from contextual_ranking.tests.fixtures import production_occurrences
from contextual_ranking.tests.memory import START, FakeSearch, make_spins

NUMBERS = [3, 26, 0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36]


def ids(spins):
    return [item["history_id"] for item in spins]


def test_rebuild_searches_the_five_latest_results_like_the_page():
    spins = make_spins(NUMBERS)
    search = FakeSearch()
    state = rebuild(None, spins, search, START)

    assert ids(state["spins"]) == ids(spins[-SPIN_MEMORY:])
    triggers = spins[-WINDOW_SEARCHES:]
    assert [record["trigger"] for record in state["searches"]] == triggers
    for (sequence, cutoff, attempts), trigger in zip(search.calls, triggers, strict=True):
        position = spins.index(trigger)
        assert sequence == [item["number"] for item in spins[position - 3:position + 1]]
        assert cutoff == parse_time(trigger["timestamp"])
        assert attempts == 3
    first = state["searches"][0]
    position = spins.index(first["trigger"])
    assert first["current_context"] == [item["number"] for item in spins[position - 8:position - 3]]
    assert state["ranking"]["built_after"] == spins[-1]
    assert state["recent_results"] == [{**item, "hit": None} for item in spins[-3:]]


def test_ranking_takes_four_occurrences_per_search_in_table_order_with_live_results():
    spins = make_spins(NUMBERS)
    state = rebuild(None, spins, FakeSearch(production_occurrences()), START)
    memory = state["spins"]
    chosen = []
    for record in state["searches"]:
        position = ids(memory).index(record["trigger"]["history_id"])
        live = [item["number"] for item in memory[position + 1:]]
        rows = analyze_occurrences(record["current_context"], record["occurrences"])
        top = sort_occurrences(rows, record["sequence"], live)[:OCCURRENCES_PER_SEARCH]
        chosen.extend(top)
        analysis = next(item for item in state["analysis"] if item["trigger"] == record["trigger"])
        assert [row["id"] for row in analysis["occurrences"]] == [row["id"] for row in top]
        assert analysis["live_numbers"] == list(dict.fromkeys(live))
    expected = [row["number"] for row in rank_following(chosen)["ranking"] if row["score"] > 0][:7]
    assert [row["number"] for row in state["ranking"]["top"]] == expected
    assert state["ranking"]["analyzed_results"] == 100
    assert [row["position"] for row in state["ranking"]["top"]] == list(range(1, 8))


def test_each_result_is_checked_against_the_top_seven_on_air():
    spins = make_spins(NUMBERS)
    search = FakeSearch(production_occurrences())
    state = rebuild(None, spins, search, START)
    on_air = [row["number"] for row in state["ranking"]["top"]]

    hit = make_spins([on_air[2]], first=100)[0]
    after_hit, signal = process(state, hit, search, START)
    assert (signal["hit"], signal["hit_position"]) == (True, 3)
    assert signal["top_numbers"] == on_air
    assert signal["result"] == hit
    assert signal["ranking_built_after"] == spins[-1]
    assert len(signal["ranking"]) == 37
    assert [len(source["occurrence_ids"]) for source in signal["sources"]] == [4] * 5

    next_top = [row["number"] for row in after_hit["ranking"]["top"]]
    miss = make_spins([next(n for n in range(37) if n not in next_top)], first=101)[0]
    after_miss, signal = process(after_hit, miss, search, START)
    assert (signal["hit"], signal["hit_position"]) == (False, None)
    assert after_miss["recent_results"][-2:] == [{**hit, "hit": True}, {**miss, "hit": False}]
    assert [record["trigger"] for record in after_miss["searches"]][-2:] == [hit, miss]
    assert len(after_miss["searches"]) == WINDOW_SEARCHES
    assert after_miss["version"] == state["version"] + 2


def test_processing_the_same_result_twice_changes_nothing():
    search = FakeSearch()
    state = rebuild(None, make_spins(NUMBERS), search, START)
    result = make_spins([7], first=100)[0]
    once, _ = process(state, result, search, START)
    again, signal = process(once, result, search, START)
    assert signal is None
    assert again is once


def test_failed_search_is_left_out_and_retried_on_the_next_results():
    spins = make_spins(NUMBERS)
    search = FakeSearch()
    search.failing.add(tuple(item["number"] for item in spins[-4:]))
    state = rebuild(None, spins, search, START)
    assert (state["searches"][-1]["status"], state["searches"][-1]["attempts"]) == ("failed", 1)
    assert state["ranking"]["analyzed_results"] == 80

    search.calls.clear()
    state, _ = process(state, make_spins([7], first=200)[0], search, START)
    assert (state["searches"][-2]["status"], state["searches"][-2]["attempts"]) == ("failed", 2)
    assert search.calls[-1][2] == 1

    search.failing.clear()
    state, _ = process(state, make_spins([8], first=201)[0], search, START)
    assert state["searches"][-3]["status"] == "ok"
    assert state["ranking"]["analyzed_results"] == 100


def test_searches_wait_until_nine_results_exist():
    state = rebuild(None, make_spins(list(range(1, 11))), FakeSearch(), START)
    assert [record["status"] for record in state["searches"]] == [
        "insufficient_history", "insufficient_history", "insufficient_history", "ok", "ok",
    ]


def test_view_lists_the_newest_items_first():
    state = rebuild(None, make_spins(NUMBERS), FakeSearch(production_occurrences()), START)
    view = build_view(state)
    assert view["last_numbers"][0] == state["recent_results"][-1]
    assert view["analysis"][0]["trigger"] == state["searches"][-1]["trigger"]
    assert view["ranking"]["top"] == state["ranking"]["top"]
    assert all(len(item["occurrences"]) == 4 for item in view["analysis"])
