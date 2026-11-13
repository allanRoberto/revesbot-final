"""Live ranking state machine. No I/O: searches are injected and time is explicit.

For each result X: check X against every open signal, search X (the four
latest results ending in X, filtered by the five before them), keep the
searches of the five latest results, take the first four occurrences of each in
the page's table order (results seen after a search count as live) and rank
the 37 numbers from the following results of those 20 occurrences.

Every new ranking opens a signal with its top 7 frozen. A signal is checked
against the next 7 results: the first hit closes it, 7 misses close it as lost.
Signals overlap (one is born after every result).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Sequence

from contextual_ranking import STRATEGY_VERSION
from contextual_ranking.rules import (
    CONTEXT_LENGTH, analyze_occurrences, rank_following, sort_occurrences,
)

ROULETTE_ID = "pragmatic-brazilian-roulette"
WINDOW_SEARCHES = 5
OCCURRENCES_PER_SEARCH = 4
TOP_NUMBERS = 7
ATTEMPTS_LIMIT = 7
SEARCH_SPAN = 9
SPIN_MEMORY = SEARCH_SPAN + WINDOW_SEARCHES - 1
RECENT_RESULTS = 3
NEW_SEARCH_ATTEMPTS = 3
RETRY_SEARCH_ATTEMPTS = 1
MAX_SEARCH_ATTEMPTS = 3

# search(sequence, cutoff, attempts) -> {"occurrences": [...], "total_matches": int}
SearchFunction = Callable[[list[int], datetime, int], dict[str, Any]]


def iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def spin(history_id: Any, number: int, timestamp: datetime) -> dict[str, Any]:
    return {"history_id": str(history_id), "number": int(number), "timestamp": iso(timestamp)}


def empty_state() -> dict[str, Any]:
    return {
        "strategy_version": STRATEGY_VERSION, "roulette_id": ROULETTE_ID, "version": 0,
        "spins": [], "searches": [], "ranking": None, "analysis": [], "recent_results": [],
        "open_signals": [], "last_processed": None, "updated_at": None, "resynced_at": None,
    }


def run_search(spins: Sequence[dict[str, Any]], position: int, search: SearchFunction,
               now: datetime, attempts: int = NEW_SEARCH_ATTEMPTS, previous_attempts: int = 0) -> dict[str, Any]:
    trigger = spins[position]
    window = list(spins[:position + 1])[-SEARCH_SPAN:]
    record: dict[str, Any] = {
        "trigger": trigger, "current_context": None, "sequence": None, "status": "insufficient_history",
        "occurrences": [], "total_matches": 0, "error": None, "searched_at": iso(now),
        "attempts": previous_attempts + 1,
    }
    if len(window) < SEARCH_SPAN:
        record["error"] = "Ainda não há 9 resultados até este número."
        return record
    numbers = [item["number"] for item in window]
    record["current_context"], record["sequence"] = numbers[:CONTEXT_LENGTH], numbers[CONTEXT_LENGTH:]
    try:
        result = search(record["sequence"], parse_time(trigger["timestamp"]), attempts)
    except Exception as error:  # the ranking must survive a failed search
        record.update(status="failed", error=str(error)[:300] or type(error).__name__)
        return record
    record.update(status="ok", occurrences=list(result["occurrences"]),
                  total_matches=int(result.get("total_matches", len(result["occurrences"]))))
    return record


def _unique(numbers: Sequence[int]) -> list[int]:
    return list(dict.fromkeys(numbers))


def _occurrence_view(row: dict[str, Any], raw: dict[str, Any], position: int,
                     live: set[int]) -> dict[str, Any]:
    score = row["score"]
    return {
        "position": position,
        "id": row["id"],
        "preceding": row["preceding"] if row["preceding_valid"] else None,
        "preceding_status": row["preceding_lookup_status"],
        "context": row["context"] if row["context_valid"] else None,
        "following": row["following"] if row["following_valid"] else None,
        "exact": score["exact"] if score else None,
        "neighbor": score["neighbor"] if score else None,
        "points": score["score"] if score else None,
        "similarity": score["similarity"] if score else None,
        "approved": row["approved"],
        "vector_similarity": raw.get("similarity"),
        "live_in_following": sum(1 for number in (row["following"] or []) if number in live)
        if row["following_valid"] else 0,
    }


def build_ranking(searches: Sequence[dict[str, Any]], spins: Sequence[dict[str, Any]]) -> tuple[dict, list]:
    positions = {item["history_id"]: index for index, item in enumerate(spins)}
    chosen: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    analysis: list[dict[str, Any]] = []
    for search in searches:
        position = positions.get(search["trigger"]["history_id"])
        live_numbers = _unique([item["number"] for item in spins[position + 1:]]) if position is not None else []
        entry = {
            "trigger": search["trigger"], "status": search["status"], "error": search.get("error"),
            "current_context": search.get("current_context"), "sequence": search.get("sequence"),
            "live_numbers": live_numbers, "total_matches": search.get("total_matches", 0), "occurrences": [],
        }
        if search["status"] == "ok":
            rows = analyze_occurrences(search["current_context"], search["occurrences"])
            top = sort_occurrences(rows, search["sequence"], live_numbers)[:OCCURRENCES_PER_SEARCH]
            chosen.extend(top)
            live = set(live_numbers)
            entry["occurrences"] = [
                _occurrence_view(row, search["occurrences"][row["index"]], index + 1, live)
                for index, row in enumerate(top)
            ]
            sources.append({"trigger": search["trigger"], "occurrence_ids": [row["id"] for row in top]})
        analysis.append(entry)
    ranked = rank_following(chosen)
    positive = [row for row in ranked["ranking"] if row["score"] > 0][:TOP_NUMBERS]
    ranking = {
        "top": [{"position": index + 1, "number": row["number"], "points": row["score"],
                 "exact": row["exact"], "neighbor": row["neighbor"]} for index, row in enumerate(positive)],
        "full": [[row["number"], row["score"], row["exact"], row["neighbor"]] for row in ranked["ranking"]],
        "analyzed_results": ranked["analyzed_results"],
        "maximum": ranked["maximum"],
        "sources": sources,
        "built_after": spins[-1] if spins else None,
    }
    return ranking, analysis


def open_signal(ranking: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    """A new ranking becomes a signal; its top 7 stays frozen for 7 results."""
    numbers = [row["number"] for row in ranking.get("top") or []]
    trigger = ranking.get("built_after")
    if not numbers or not trigger:
        return None
    return {
        "_id": f"v{STRATEGY_VERSION}-{trigger['history_id']}",
        "roulette_id": ROULETTE_ID,
        "strategy_version": STRATEGY_VERSION,
        "attempts_limit": ATTEMPTS_LIMIT,
        "status": "open",
        "built_after": trigger,
        "top_numbers": numbers,
        "ranking": ranking.get("full", []),
        "sources": ranking.get("sources", []),
        "checks": [],
        "hit": None,
        "hit_attempt": None,
        "hit_position": None,
        "created_at": iso(now),
        "closed_at": None,
    }


def check_signals(signals: Sequence[dict[str, Any]], result: dict[str, Any],
                  now: datetime) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Check one result against every open signal; returns (still open, closed)."""
    still_open: list[dict[str, Any]] = []
    closed: list[dict[str, Any]] = []
    for signal in signals:
        attempt = len(signal["checks"]) + 1
        hit = result["number"] in signal["top_numbers"]
        checked = {**signal, "checks": [*signal["checks"], {"result": result, "attempt": attempt, "hit": hit}]}
        if hit:
            closed.append({**checked, "status": "hit", "hit": True, "hit_attempt": attempt,
                           "hit_position": signal["top_numbers"].index(result["number"]) + 1,
                           "closed_at": iso(now)})
        elif attempt >= signal.get("attempts_limit", ATTEMPTS_LIMIT):
            closed.append({**checked, "status": "miss", "hit": False, "closed_at": iso(now)})
        else:
            still_open.append(checked)
    return still_open, closed


def advance_signals(state: dict[str, Any], results: Sequence[dict[str, Any]],
                    now: datetime) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Check open signals against results the worker could not follow live (no searches)."""
    still_open = list(state.get("open_signals") or [])
    closed: list[dict[str, Any]] = []
    for result in results:
        if not still_open:
            break
        still_open, newly_closed = check_signals(still_open, result, now)
        closed.extend(newly_closed)
    return {**state, "open_signals": still_open}, closed


def _finish(state: dict[str, Any], spins: list[dict[str, Any]], searches: list[dict[str, Any]],
            recent: list[dict[str, Any]], open_signals: Sequence[dict[str, Any]], now: datetime,
            **extra: Any) -> dict[str, Any]:
    ranking, analysis = build_ranking(searches, spins)
    signal = open_signal(ranking, now)
    return {
        **state, **extra,
        "strategy_version": STRATEGY_VERSION, "roulette_id": ROULETTE_ID,
        "spins": spins, "searches": searches, "ranking": ranking, "analysis": analysis,
        "recent_results": recent[-RECENT_RESULTS:],
        "open_signals": [*open_signals, *([signal] if signal else [])],
        "last_processed": {"history_id": spins[-1]["history_id"], "timestamp": spins[-1]["timestamp"]}
        if spins else None,
        "version": int(state.get("version") or 0) + 1,
        "updated_at": iso(now),
    }


def rebuild(previous: dict[str, Any] | None, spins: Sequence[dict[str, Any]], search: SearchFunction,
            now: datetime) -> dict[str, Any]:
    """Start (or restart) from the latest results; open signals of the same strategy carry over."""
    previous = previous or {}
    same_strategy = previous.get("strategy_version") == STRATEGY_VERSION
    carried = (previous.get("open_signals") or []) if same_strategy else []
    state = {**empty_state(), "version": int(previous.get("version") or 0)}
    spins = list(spins)[-SPIN_MEMORY:]
    start = max(0, len(spins) - WINDOW_SEARCHES)
    searches = [run_search(spins, position, search, now) for position in range(start, len(spins))]
    recent = [{**item, "hit": None} for item in spins[-RECENT_RESULTS:]]
    return _finish(state, spins, searches, recent, carried, now, resynced_at=iso(now))


def process(state: dict[str, Any], result: dict[str, Any], search: SearchFunction,
            now: datetime) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Check open signals, search the new result and open the next signal."""
    last = state.get("last_processed")
    if last and last["history_id"] == result["history_id"]:
        return state, []
    on_screen = [row["number"] for row in (state.get("ranking") or {}).get("top") or []]
    still_open, closed = check_signals(state.get("open_signals") or [], result, now)
    spins = (list(state.get("spins") or []) + [result])[-SPIN_MEMORY:]
    searches = (list(state.get("searches") or []) + [run_search(spins, len(spins) - 1, search, now)])
    searches = searches[-WINDOW_SEARCHES:]
    positions = {item["history_id"]: index for index, item in enumerate(spins)}
    for index, item in enumerate(searches[:-1]):
        position = positions.get(item["trigger"]["history_id"])
        if item["status"] == "failed" and position is not None and item.get("attempts", 1) < MAX_SEARCH_ATTEMPTS:
            searches[index] = run_search(spins, position, search, now, RETRY_SEARCH_ATTEMPTS,
                                         previous_attempts=item.get("attempts", 1))
    # The screen mark keeps its meaning: was X among the 7 numbers on screen?
    recent = list(state.get("recent_results") or []) + [
        {**result, "hit": (result["number"] in on_screen) if on_screen else None},
    ]
    return _finish(state, spins, searches, recent, still_open, now), closed


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
        "last_numbers": list(reversed(state.get("recent_results") or [])),
        "analysis": list(reversed(state.get("analysis") or [])),
        "open_signals": [compact_signal(signal) for signal in reversed(state.get("open_signals") or [])],
        "attempts_limit": ATTEMPTS_LIMIT,
        "resynced_at": state.get("resynced_at"),
    }


def compact_signal(signal: dict[str, Any]) -> dict[str, Any]:
    """Short form kept in Redis for the page history tab."""
    return {
        "id": signal["_id"],
        "status": signal["status"],
        "built_after": signal["built_after"],
        "top_numbers": signal["top_numbers"],
        "checks": [{"number": check["result"]["number"], "timestamp": check["result"]["timestamp"],
                    "hit": check["hit"]} for check in signal["checks"]],
        "attempts_limit": signal.get("attempts_limit", ATTEMPTS_LIMIT),
        "hit": signal["hit"],
        "hit_attempt": signal["hit_attempt"],
        "hit_position": signal["hit_position"],
        "created_at": signal["created_at"],
        "closed_at": signal["closed_at"],
    }
