from __future__ import annotations

from contextual_ranking import STRATEGY_VERSION
from contextual_ranking.engine import (
    ATTEMPTS_LIMIT, OCCURRENCES_PER_SEARCH, SPIN_MEMORY, WINDOW_SEARCHES, advance_signals, build_view,
    check_signals, open_signal, parse_time, process, rebuild,
)
from contextual_ranking.rules import analyze_occurrences, rank_columns, sort_occurrences
from contextual_ranking.tests.fixtures import production_occurrences
from contextual_ranking.tests.memory import START, FakeSearch, make_spins

NUMBERS = [3, 26, 0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36]


def ids(spins):
    return [item["history_id"] for item in spins]


def a_signal(top, trigger_number=7, first=500):
    trigger = make_spins([trigger_number], first=first)[0]
    ranking = {"top": [{"number": number} for number in top], "built_after": trigger,
               "full": [], "sources": []}
    return open_signal(ranking, START)


def outside(numbers):
    return next(number for number in range(37) if number not in numbers)


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
    expected = [row["number"] for row in rank_columns(chosen)["ranking"] if row["score"] > 0][:7]
    assert [row["number"] for row in state["ranking"]["top"]] == expected
    # 5 searches x 4 occurrences x (5 Anterior + 4 Sequência + 5 Posterior)
    assert state["ranking"]["analyzed_results"] == 280
    assert [row["position"] for row in state["ranking"]["top"]] == list(range(1, 8))


def test_every_ranking_opens_a_signal_with_its_top_seven_frozen():
    spins = make_spins(NUMBERS)
    search = FakeSearch(production_occurrences())
    state = rebuild(None, spins, search, START)
    [first] = state["open_signals"]
    assert first["_id"] == f"v{STRATEGY_VERSION}-{spins[-1]['history_id']}"
    assert first["top_numbers"] == [row["number"] for row in state["ranking"]["top"]]
    assert (first["status"], first["checks"], first["attempts_limit"]) == ("open", [], ATTEMPTS_LIMIT)
    assert len(first["ranking"]) == 37 and [len(s["occurrence_ids"]) for s in first["sources"]] == [4] * 5

    result = make_spins([outside(first["top_numbers"])], first=100)[0]
    state, closed = process(state, result, search, START)
    assert closed == []
    older, newer = state["open_signals"]
    assert older["top_numbers"] == first["top_numbers"]
    assert older["checks"] == [{"result": result, "attempt": 1, "hit": False}]
    assert newer["built_after"] == result and newer["checks"] == []


def test_first_hit_closes_the_signal_and_records_the_round():
    signal = a_signal([10, 11, 12, 13, 14, 15, 16])
    misses = make_spins([1, 2], first=600)
    still_open, closed = check_signals([signal], misses[0], START)
    still_open, closed = check_signals(still_open, misses[1], START)
    assert closed == [] and len(still_open[0]["checks"]) == 2
    hit = make_spins([13], first=602)[0]
    still_open, [done] = check_signals(still_open, hit, START)
    assert still_open == []
    assert (done["status"], done["hit"], done["hit_attempt"], done["hit_position"]) == ("hit", True, 3, 4)
    assert [check["hit"] for check in done["checks"]] == [False, False, True]
    assert done["closed_at"] is not None


def test_signal_closes_as_miss_after_seven_rounds():
    open_signals = [a_signal([10, 11, 12, 13, 14, 15, 16])]
    for index, result in enumerate(make_spins([1, 2, 3, 4, 5, 6, 7], first=700), start=1):
        open_signals, closed = check_signals(open_signals, result, START)
        if index < ATTEMPTS_LIMIT:
            assert closed == [] and len(open_signals[0]["checks"]) == index
    assert open_signals == []
    assert (closed[0]["status"], closed[0]["hit"], len(closed[0]["checks"])) == ("miss", False, 7)
    assert closed[0]["hit_attempt"] is None


def test_overlapping_signals_are_checked_independently():
    older = {**a_signal([1, 2, 3, 4, 5, 6, 7], first=800), "checks": [{"attempt": 1, "hit": False}] * 6}
    newer = a_signal([20, 21, 22, 23, 24, 25, 26], first=801)
    still_open, closed = check_signals([older, newer], make_spins([20], first=802)[0], START)
    assert [(signal["_id"], signal["status"]) for signal in closed] == [
        (older["_id"], "miss"), (newer["_id"], "hit"),
    ]
    assert still_open == []


def test_screen_mark_still_means_number_was_on_screen():
    search = FakeSearch(production_occurrences())
    state = rebuild(None, make_spins(NUMBERS), search, START)
    on_screen = [row["number"] for row in state["ranking"]["top"]]
    state, _ = process(state, make_spins([on_screen[0]], first=100)[0], search, START)
    assert state["recent_results"][-1]["hit"] is True
    on_screen = [row["number"] for row in state["ranking"]["top"]]
    state, _ = process(state, make_spins([outside(on_screen)], first=101)[0], search, START)
    assert state["recent_results"][-1]["hit"] is False


def test_gap_results_still_settle_open_signals_without_searches():
    state = {"open_signals": [a_signal([10, 11, 12, 13, 14, 15, 16], first=900),
                              a_signal([30, 31, 32, 33, 34, 35, 36], first=901)]}
    advanced, closed = advance_signals(state, make_spins([1, 33, 2, 3, 4, 5, 6, 8, 9], first=902), START)
    assert [(signal["status"], signal["hit_attempt"]) for signal in closed] == [("hit", 2), ("miss", None)]
    assert advanced["open_signals"] == []


def test_rebuild_keeps_open_signals_of_the_same_strategy():
    search = FakeSearch()
    carried = a_signal([10, 11, 12, 13, 14, 15, 16])
    state = rebuild({"strategy_version": STRATEGY_VERSION, "open_signals": [carried], "version": 4},
                    make_spins(NUMBERS), search, START)
    assert state["open_signals"][0] == carried and len(state["open_signals"]) == 2
    assert state["version"] == 5
    old = rebuild({"strategy_version": 1, "open_signals": [carried]}, make_spins(NUMBERS), search, START)
    assert carried not in old["open_signals"]


def test_processing_the_same_result_twice_changes_nothing():
    search = FakeSearch()
    state = rebuild(None, make_spins(NUMBERS), search, START)
    result = make_spins([7], first=100)[0]
    once, _ = process(state, result, search, START)
    again, closed = process(once, result, search, START)
    assert closed == []
    assert again is once


def test_failed_search_is_left_out_and_retried_on_the_next_results():
    spins = make_spins(NUMBERS)
    search = FakeSearch()
    search.failing.add(tuple(item["number"] for item in spins[-4:]))
    state = rebuild(None, spins, search, START)
    assert (state["searches"][-1]["status"], state["searches"][-1]["attempts"]) == ("failed", 1)
    assert state["ranking"]["analyzed_results"] == 224  # 4 searches x 4 x 14

    search.calls.clear()
    state, _ = process(state, make_spins([7], first=200)[0], search, START)
    assert (state["searches"][-2]["status"], state["searches"][-2]["attempts"]) == ("failed", 2)
    assert search.calls[-1][2] == 1

    search.failing.clear()
    state, _ = process(state, make_spins([8], first=201)[0], search, START)
    assert state["searches"][-3]["status"] == "ok"
    assert state["ranking"]["analyzed_results"] == 280


def test_searches_wait_until_nine_results_exist():
    state = rebuild(None, make_spins(list(range(1, 11))), FakeSearch(), START)
    assert [record["status"] for record in state["searches"]] == [
        "insufficient_history", "insufficient_history", "insufficient_history", "ok", "ok",
    ]


def test_view_lists_the_newest_items_first():
    search = FakeSearch(production_occurrences())
    state = rebuild(None, make_spins(NUMBERS), search, START)
    state, _ = process(state, make_spins([outside([row["number"] for row in state["ranking"]["top"]])],
                                         first=100)[0], search, START)
    view = build_view(state)
    assert view["last_numbers"][0] == state["recent_results"][-1]
    assert view["analysis"][0]["trigger"] == state["searches"][-1]["trigger"]
    assert view["ranking"]["top"] == state["ranking"]["top"]
    assert all(len(item["occurrences"]) == 4 for item in view["analysis"])
    assert [signal["id"] for signal in view["open_signals"]] == [
        signal["_id"] for signal in reversed(state["open_signals"])
    ]
    assert view["open_signals"][-1]["checks"][0]["hit"] is False
    assert view["attempts_limit"] == ATTEMPTS_LIMIT
