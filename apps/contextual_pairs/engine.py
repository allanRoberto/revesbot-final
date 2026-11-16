"""Pair signals on top of the contextual ranking engine. No I/O.

The ranking (search of every result, the 4 first occurrences of the 5 latest searches, the three
columns, top 7) is produced by ``contextual_ranking.engine`` exactly as for the ranking page.
This module turns each ranking into at most one bet:

* exactly two of the 7 numbers are from 0 to 9 (the pair) and the rule finds a bet for them;
* no signal of the same pair is open. A different pair may open meanwhile.

A signal keeps its bet frozen and is checked against the next 7 results: the first number inside
the bet closes it (recording the round), 7 misses close it as lost. Closing releases the pair, so
the ranking built right after the closing result may open the same pair again.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

from contextual_ranking import engine as ranking_engine
from contextual_ranking.engine import ROULETTE_ID, SearchFunction, iso

from contextual_pairs import PAIRS_VERSION, STRATEGY, STRATEGY_TAG
from contextual_pairs.rules import pair_bet

ATTEMPTS_LIMIT = 7
# What the ranking on screen did: opened a signal, was blocked by an open signal of the same pair,
# or was ignored (fewer than 2 / more than 2 numbers from 0 to 9, a pair listed as an exception,
# or a pair without intersection).
SCREEN_STATES = ("opened", "active", "ignored", "no_pair", "too_many", "no_intersection")


def pair_key(pair: Sequence[int]) -> str:
    return f"{pair[0]}-{pair[1]}"


def waiting_screen() -> dict[str, Any]:
    return {"state": "waiting", "bases": [], "pair": None, "kept": [], "bet": [], "arcs": [], "built_after": None}


def open_pair_signal(ranking: dict[str, Any], top: Sequence[int], info: dict[str, Any],
                     now: datetime) -> dict[str, Any] | None:
    """A ranking with a valid pair becomes a signal; its bet stays frozen for 7 results."""
    trigger = ranking.get("built_after")
    if not trigger or info["kind"] != "ok":
        return None
    return {
        "_id": f"{STRATEGY_TAG}-{trigger['history_id']}",
        "roulette_id": ROULETTE_ID,
        "strategy": STRATEGY,
        "strategy_version": STRATEGY_TAG,
        "attempts_limit": ATTEMPTS_LIMIT,
        "status": "open",
        "built_after": trigger,
        "top_numbers": list(top),
        "pair": info["pair"],
        "pair_key": pair_key(info["pair"]),
        "bases": info["bases"],
        "kept": info["kept"],
        "bet": info["bet"],
        "bet_arcs": info["arcs"],
        "ranking": ranking.get("full", []),
        "sources": ranking.get("sources", []),
        "checks": [],
        "hit": None,
        "hit_attempt": None,
        "hit_number": None,
        "created_at": iso(now),
        "closed_at": None,
    }


def evaluate_ranking(ranking: dict[str, Any], open_signals: Sequence[dict[str, Any]],
                     now: datetime) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """The screen state of a ranking and, when its pair is free, the signal it opens."""
    top = [row["number"] for row in ranking.get("top") or []]
    info = pair_bet(top)
    screen = {"state": info["kind"], "bases": info["bases"], "pair": info["pair"], "kept": info["kept"],
              "bet": info["bet"], "arcs": info["arcs"], "built_after": ranking.get("built_after")}
    if info["kind"] != "ok":
        return screen, None
    if pair_key(info["pair"]) in {signal["pair_key"] for signal in open_signals}:
        screen["state"] = "active"
        return screen, None
    signal = open_pair_signal(ranking, top, info, now)
    screen["state"] = "opened" if signal else "waiting"
    return screen, signal


def check_pair_signals(signals: Sequence[dict[str, Any]], result: dict[str, Any],
                       now: datetime) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Check one result against every open signal; returns (still open, closed)."""
    still_open: list[dict[str, Any]] = []
    closed: list[dict[str, Any]] = []
    for signal in signals:
        attempt = len(signal["checks"]) + 1
        hit = result["number"] in signal["bet"]
        checked = {**signal, "checks": [*signal["checks"], {"result": result, "attempt": attempt, "hit": hit}]}
        if hit:
            closed.append({**checked, "status": "hit", "hit": True, "hit_attempt": attempt,
                           "hit_number": result["number"], "closed_at": iso(now)})
        elif attempt >= signal.get("attempts_limit", ATTEMPTS_LIMIT):
            closed.append({**checked, "status": "miss", "hit": False, "closed_at": iso(now)})
        else:
            still_open.append(checked)
    return still_open, closed


def advance_pair_signals(state: dict[str, Any], results: Sequence[dict[str, Any]],
                         now: datetime) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Check open signals against results the worker could not follow live (no searches)."""
    still_open = list(state.get("pair_signals") or [])
    closed: list[dict[str, Any]] = []
    for result in results:
        if not still_open:
            break
        still_open, newly_closed = check_pair_signals(still_open, result, now)
        closed.extend(newly_closed)
    return {**state, "pair_signals": still_open}, closed


def _with_pairs(engine_state: dict[str, Any], open_signals: Sequence[dict[str, Any]], now: datetime,
                result: dict[str, Any] | None = None, on_screen_bet: Sequence[int] = ()) -> dict[str, Any]:
    """Attach the pair signals and the screen to the state the ranking engine returned."""
    screen, signal = evaluate_ranking(engine_state.get("ranking") or {}, open_signals, now)
    recent = list(engine_state.get("recent_results") or [])
    if result is not None and recent:
        # The mark answers: was the result inside the pair bet that was on screen?
        recent[-1] = {**recent[-1], "hit": (result["number"] in on_screen_bet) if on_screen_bet else None}
    return {
        **engine_state,
        "pairs_version": PAIRS_VERSION,
        "open_signals": [],  # the ranking engine's own signals are not used here
        "recent_results": recent,
        "pair_signals": [*open_signals, *([signal] if signal else [])],
        "screen": screen,
    }


def rebuild(previous: dict[str, Any] | None, spins: Sequence[dict[str, Any]], search: SearchFunction,
            now: datetime) -> dict[str, Any]:
    """Start (or restart) from the latest results; open pair signals of this version carry over."""
    previous = previous or {}
    carried = (previous.get("pair_signals") or []) if previous.get("pairs_version") == PAIRS_VERSION else []
    base = {**previous, "open_signals": []} if previous else None
    engine_state = ranking_engine.rebuild(base, spins, search, now)
    return _with_pairs(engine_state, carried, now)


def process(state: dict[str, Any], result: dict[str, Any], search: SearchFunction,
            now: datetime) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Check open signals, search the new result, build the ranking and open the next signal."""
    last = state.get("last_processed")
    if last and last["history_id"] == result["history_id"]:
        return state, []
    on_screen_bet = (state.get("screen") or {}).get("bet") or []
    still_open, closed = check_pair_signals(state.get("pair_signals") or [], result, now)
    engine_state, _ = ranking_engine.process({**state, "open_signals": []}, result, search, now)
    return _with_pairs(engine_state, still_open, now, result, on_screen_bet), closed


def compact_signal(signal: dict[str, Any]) -> dict[str, Any]:
    """Short form kept in Redis for the page history tab."""
    return {
        "id": signal["_id"],
        "status": signal["status"],
        "built_after": signal["built_after"],
        "top_numbers": signal["top_numbers"],
        "pair": signal["pair"],
        "kept": signal["kept"],
        "bet": signal["bet"],
        "bet_arcs": signal["bet_arcs"],
        "checks": [{"number": check["result"]["number"], "timestamp": check["result"]["timestamp"],
                    "hit": check["hit"]} for check in signal["checks"]],
        "attempts_limit": signal.get("attempts_limit", ATTEMPTS_LIMIT),
        "hit": signal["hit"],
        "hit_attempt": signal["hit_attempt"],
        "hit_number": signal["hit_number"],
        "created_at": signal["created_at"],
        "closed_at": signal["closed_at"],
    }


def build_view(state: dict[str, Any]) -> dict[str, Any]:
    """Projection read by the page: only what the screen and the tabs show."""
    ranking = state.get("ranking") or {}
    return {
        "version": state.get("version", 0),
        "updated_at": state.get("updated_at"),
        "roulette_id": ROULETTE_ID,
        "ranking": {
            "top": ranking.get("top", []),
            "built_after": ranking.get("built_after"),
            "analyzed_results": ranking.get("analyzed_results", 0),
            "maximum": ranking.get("maximum", 0),
        },
        "screen": state.get("screen") or waiting_screen(),
        "last_numbers": list(reversed(state.get("recent_results") or [])),
        "analysis": list(reversed(state.get("analysis") or [])),
        "open_signals": [compact_signal(signal) for signal in reversed(state.get("pair_signals") or [])],
        "attempts_limit": ATTEMPTS_LIMIT,
        "resynced_at": state.get("resynced_at"),
    }
