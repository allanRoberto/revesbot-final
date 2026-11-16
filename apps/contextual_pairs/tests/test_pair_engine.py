from __future__ import annotations

from contextual_pairs import PAIRS_VERSION, STRATEGY_TAG, rules
from contextual_pairs import engine as pairs
from contextual_pairs.rules import pair_bet
from contextual_pairs.tests.scripted import (
    BET_37, IGNORED_PAIR, NO_INTERSECTION, NO_PAIR, PAIR_37, PAIR_39, PROTECTION_37, TOO_MANY,
)
from contextual_ranking.tests.memory import START, make_spins

BET_39 = pair_bet(PAIR_39)["bet"]
OUTSIDE = [number for number in range(37) if number not in BET_37 and number not in BET_39]
INSIDE_37 = 13


def start(scripted, tops, count=13):
    scripted(tops)
    spins = make_spins([OUTSIDE[index % len(OUTSIDE)] for index in range(count)])
    return pairs.rebuild(None, spins, None, START), spins


def result(number, first):
    return make_spins([number], first=first)[0]


def step(state, number, first):
    return pairs.process(state, result(number, first), None, START)


def test_a_ranking_with_a_valid_pair_opens_one_signal(scripted):
    state, spins = start(scripted, [PAIR_37])
    [signal] = state["pair_signals"]
    assert signal["_id"] == f"{STRATEGY_TAG}-{spins[-1]['history_id']}" == f"pairs-1-{spins[-1]['history_id']}"
    assert (signal["strategy"], signal["strategy_version"], signal["status"]) == ("pairs", "pairs-1", "open")
    assert (signal["pair"], signal["pair_key"], signal["bases"], signal["kept"]) == ([3, 7], "3-7", [3, 7], [13, 16, 27, 33])
    assert signal["bet"] == BET_37
    assert signal["bet_arcs"] == [[21, 2, 25], [6, 27, 13, 36], [24, 16, 33, 1], [7, 28, 12], [3]]
    assert (signal["protection"], signal["protection_triples"]) == (PROTECTION_37, [[21, 2, 25], [7, 28, 12]])
    assert (signal["top_numbers"], signal["checks"], signal["attempts_limit"]) == (PAIR_37, [], 7)
    assert signal["built_after"] == spins[-1] and len(signal["ranking"]) == 7
    assert state["screen"]["state"] == "opened" and state["screen"]["bet"] == BET_37
    assert state["screen"]["protection"] == PROTECTION_37
    assert state["pairs_version"] == PAIRS_VERSION and state["open_signals"] == []


def test_signals_are_checked_by_the_bet_not_by_the_ranking_numbers(scripted):
    state, _ = start(scripted, [PAIR_37, NO_PAIR, NO_PAIR])
    # 20 is in the ranking but not in the bet: the signal goes on.
    state, closed = step(state, 20, 100)
    [signal] = state["pair_signals"]
    assert closed == [] and [(c["result"]["number"], c["hit"]) for c in signal["checks"]] == [(20, False)]
    # 13 is in the bet (not in the ranking): attempt 2 closes the signal as a hit.
    state, closed = step(state, INSIDE_37, 101)
    [done] = closed
    assert (done["status"], done["hit"], done["hit_attempt"], done["hit_number"]) == ("hit", True, 2, 13)
    assert [c["attempt"] for c in done["checks"]] == [1, 2] and done["closed_at"] is not None
    assert state["pair_signals"] == []


def test_the_two_numbers_of_the_pair_count_as_hits(scripted):
    state, _ = start(scripted, [PAIR_37, NO_PAIR])
    # 3 is not a neighbor of the intersection: it is in the bet only because it is a number of the pair.
    state, closed = step(state, 3, 100)
    [done] = closed
    assert (done["status"], done["hit_attempt"], done["hit_number"]) == ("hit", 1, 3)


def test_the_protection_numbers_count_as_hits(scripted, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(rules, "INCLUDE_PROTECTION", False)
        # 28 is neither in the intersection, nor a neighbor of it, nor a number of the pair
        assert 28 not in pair_bet(PAIR_37)["bet"]
    assert 28 in PROTECTION_37
    state, _ = start(scripted, [PAIR_37, NO_PAIR, NO_PAIR])
    state, closed = step(state, 28, 100)
    [done] = closed
    assert (done["status"], done["hit_attempt"], done["hit_number"]) == ("hit", 1, 28)
    assert done["protection"] == PROTECTION_37


def test_a_signal_closed_before_the_protection_rule_has_no_protection_in_its_compact_form():
    old = {"_id": "pairs-1-h0", "status": "miss", "built_after": {}, "top_numbers": [], "pair": [3, 7], "kept": [],
           "bet": [3, 7], "bet_arcs": [[3], [7]], "checks": [], "hit": False, "hit_attempt": None,
           "hit_number": None, "created_at": "2026-11-16T00:00:00+00:00", "closed_at": "2026-11-16T00:01:00+00:00"}
    assert pairs.compact_signal(old)["protection"] == []


def test_an_ignored_pair_opens_nothing_and_the_next_pair_opens_normally(scripted):
    state, _ = start(scripted, [IGNORED_PAIR, IGNORED_PAIR, PAIR_37])
    assert (state["screen"]["state"], state["screen"]["pair"], state["screen"]["bet"]) == ("ignored", [6, 9], [])
    assert state["pair_signals"] == []
    state, _ = step(state, OUTSIDE[0], 100)
    assert state["screen"]["state"] == "ignored" and state["pair_signals"] == []
    state, _ = step(state, OUTSIDE[1], 101)
    assert state["screen"]["state"] == "opened" and [s["pair_key"] for s in state["pair_signals"]] == ["3-7"]


def test_the_same_pair_is_blocked_while_its_signal_is_open_but_other_pairs_open(scripted):
    state, _ = start(scripted, [PAIR_37, PAIR_37, PAIR_39, PAIR_37, PAIR_39])
    assert [s["pair_key"] for s in state["pair_signals"]] == ["3-7"]

    state, closed = step(state, OUTSIDE[0], 100)  # ranking repeats pair 3-7: blocked
    assert closed == [] and state["screen"]["state"] == "active"
    assert [s["pair_key"] for s in state["pair_signals"]] == ["3-7"]
    assert state["screen"]["pair"] == [3, 7] and state["screen"]["bet"] == BET_37

    state, _ = step(state, OUTSIDE[1], 101)  # a different pair opens meanwhile
    assert state["screen"]["state"] == "opened"
    assert [s["pair_key"] for s in state["pair_signals"]] == ["3-7", "3-9"]

    for index, expected in ((102, "active"), (103, "active")):  # both pairs are now blocked
        state, _ = step(state, OUTSIDE[index % 5], index)
        assert state["screen"]["state"] == expected
        assert [s["pair_key"] for s in state["pair_signals"]] == ["3-7", "3-9"]


def test_a_pair_is_released_when_its_signal_closes_on_a_hit(scripted):
    state, _ = start(scripted, [PAIR_37, PAIR_37, PAIR_37])
    state, _ = step(state, OUTSIDE[0], 100)
    assert state["screen"]["state"] == "active" and len(state["pair_signals"]) == 1
    first = state["pair_signals"][0]["_id"]

    trigger = result(INSIDE_37, 101)
    state, closed = pairs.process(state, trigger, None, START)
    assert [(s["_id"], s["status"], s["hit_attempt"]) for s in closed] == [(first, "hit", 2)]
    # The ranking built right after the closing result may open the pair again.
    [reopened] = state["pair_signals"]
    assert state["screen"]["state"] == "opened"
    assert reopened["_id"] != first and reopened["built_after"] == trigger and reopened["checks"] == []


def test_a_signal_closes_as_a_miss_after_seven_rounds_and_releases_the_pair(scripted):
    state, _ = start(scripted, [PAIR_37] + [NO_PAIR] * 7 + [PAIR_37])
    for index in range(1, 7):
        state, closed = step(state, OUTSIDE[index], 100 + index)
        assert closed == [] and len(state["pair_signals"][0]["checks"]) == index
    state, closed = step(state, OUTSIDE[7], 107)
    [lost] = closed
    assert (lost["status"], lost["hit"], lost["hit_attempt"], lost["hit_number"]) == ("miss", False, None, None)
    assert len(lost["checks"]) == 7 and state["pair_signals"] == []
    state, _ = step(state, OUTSIDE[8], 108)
    assert [s["pair_key"] for s in state["pair_signals"]] == ["3-7"] and state["screen"]["state"] == "opened"


def test_rankings_without_a_valid_pair_open_nothing(scripted):
    state, _ = start(scripted, [NO_PAIR, TOO_MANY, NO_INTERSECTION])
    assert (state["screen"]["state"], state["screen"]["bet"], state["pair_signals"]) == ("no_pair", [], [])
    state, _ = step(state, OUTSIDE[0], 100)
    assert (state["screen"]["state"], state["screen"]["bases"], state["pair_signals"]) == ("too_many", [1, 2, 3], [])
    state, _ = step(state, OUTSIDE[1], 101)
    assert (state["screen"]["state"], state["screen"]["pair"], state["screen"]["bet"]) == ("no_intersection", [0, 7], [])
    assert state["pair_signals"] == []


def test_screen_marks_follow_the_bet_that_was_on_screen(scripted):
    state, _ = start(scripted, [PAIR_37, PAIR_37, NO_PAIR, NO_PAIR])
    assert [item["hit"] for item in state["recent_results"]] == [None, None, None]
    state, _ = step(state, 0, 100)  # outside the bet on screen
    state, _ = step(state, INSIDE_37, 101)  # inside the bet on screen (a different number than the ranking)
    state, _ = step(state, 5, 102)  # no bet on screen at that moment
    assert [item["hit"] for item in state["recent_results"]] == [False, True, None]


def test_the_same_result_is_never_processed_twice(scripted):
    state, _ = start(scripted, [PAIR_37, NO_PAIR])
    trigger = result(INSIDE_37, 100)
    once, closed = pairs.process(state, trigger, None, START)
    again, repeated = pairs.process(once, trigger, None, START)
    assert len(closed) == 1 and repeated == [] and again is once


def test_results_missed_by_the_worker_settle_open_signals_and_keep_the_pair_blocked(scripted):
    state, spins = start(scripted, [PAIR_37, PAIR_37])
    advanced, closed = pairs.advance_pair_signals(state, make_spins([OUTSIDE[0], INSIDE_37, 5], first=200), START)
    assert [(s["status"], s["hit_attempt"]) for s in closed] == [("hit", 2)] and advanced["pair_signals"] == []

    held, closed = pairs.advance_pair_signals(state, make_spins(OUTSIDE[:3], first=200), START)
    assert closed == [] and len(held["pair_signals"][0]["checks"]) == 3
    rebuilt = pairs.rebuild(held, spins, None, START)
    assert [s["_id"] for s in rebuilt["pair_signals"]] == [s["_id"] for s in held["pair_signals"]]
    assert rebuilt["screen"]["state"] == "active"

    other_version = pairs.rebuild({**held, "pairs_version": PAIRS_VERSION - 1}, spins, None, START)
    assert other_version["screen"]["state"] == "opened" and other_version["pair_signals"][0]["checks"] == []


def test_the_view_lists_the_newest_signals_first(scripted):
    state, _ = start(scripted, [PAIR_37, PAIR_39, NO_PAIR])
    state, _ = step(state, OUTSIDE[0], 100)
    view = pairs.build_view(state)
    assert [signal["pair"] for signal in view["open_signals"]] == [[3, 9], [3, 7]]
    newest, oldest = view["open_signals"]
    assert newest["checks"] == [] and [c["number"] for c in oldest["checks"]] == [OUTSIDE[0]]
    assert set(oldest) == {"id", "status", "built_after", "top_numbers", "pair", "kept", "protection", "bet",
                           "bet_arcs", "checks", "attempts_limit", "hit", "hit_attempt", "hit_number", "created_at",
                           "closed_at"}
    assert oldest["protection"] == PROTECTION_37
    assert view["attempts_limit"] == 7 and view["screen"]["state"] == "opened"
    assert view["last_numbers"][0]["number"] == OUTSIDE[0]
    assert pairs.build_view({})["screen"]["state"] == "waiting"
