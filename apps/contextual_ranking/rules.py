"""Python port of the contextual similarity page rules.

The browser page is the reference implementation:

- ``apps/api/static/js/core/contextual-similarity-model.js`` (scoring, ranking);
- ``matchCounts``, ``compareDistribution``, ``duplicateCount``,
  ``liveHitDistribution`` and ``occurrenceOrder`` in
  ``apps/api/static/js/pages/contextual-similarity.js`` (table order).

``tests/test_rules_parity.py`` executes those JavaScript functions with Node and
requires identical results, so any change here must keep that parity.
"""
from __future__ import annotations

from functools import cmp_to_key
from typing import Any, Iterable, Sequence

CONTEXT_LENGTH = 5
SEQUENCE_LENGTH = 4
FOLLOWING_LENGTH = 5
EXACT_POINTS = 10
NEIGHBOR_POINTS = 8
MINIMUM_SIMILARITY = 30

WHEEL = (
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10,
    5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26,
)
_WHEEL_POSITIONS = {number: index for index, number in enumerate(WHEEL)}


def valid_number(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 36


def valid_numbers(values: Any, length: int) -> bool:
    return isinstance(values, list) and len(values) == length and all(valid_number(value) for value in values)


def neighbors_of(number: Any) -> tuple[int, ...]:
    if not valid_number(number):
        return ()
    index = _WHEEL_POSITIONS[number]
    return WHEEL[(index - 1) % len(WHEEL)], WHEEL[(index + 1) % len(WHEEL)]


def _best_matching(current: Sequence[int], historical: Sequence[int]) -> dict[str, Any]:
    """Maximum one-to-one matching: highest score, then most exact pairs."""
    best: dict[str, Any] = {"score": 0, "exact": 0, "neighbor": 0, "matches": []}
    used: set[int] = set()
    chosen: list[dict[str, Any]] = []

    def visit(index: int, score: int, exact: int, neighbor: int) -> None:
        nonlocal best
        if index == len(current):
            if score > best["score"] or (score == best["score"] and exact > best["exact"]):
                best = {"score": score, "exact": exact, "neighbor": neighbor,
                        "matches": [dict(match) for match in chosen]}
            return
        visit(index + 1, score, exact, neighbor)
        for historical_index, value in enumerate(historical):
            if historical_index in used:
                continue
            if current[index] == value:
                kind = "exact"
            elif value in neighbors_of(current[index]):
                kind = "neighbor"
            else:
                continue
            points = EXACT_POINTS if kind == "exact" else NEIGHBOR_POINTS
            used.add(historical_index)
            chosen.append({
                "current": current[index], "historical": value, "current_index": index,
                "historical_index": historical_index, "type": kind, "points": points,
            })
            visit(index + 1, score + points, exact + (kind == "exact"), neighbor + (kind == "neighbor"))
            chosen.pop()
            used.discard(historical_index)

    visit(0, 0, 0, 0)
    return best


def score_context(current: Any, historical: Any) -> dict[str, Any]:
    if not valid_numbers(current, CONTEXT_LENGTH) or not valid_numbers(historical, CONTEXT_LENGTH):
        return {"valid": False, "score": 0, "similarity": 0, "exact": 0, "neighbor": 0, "matches": []}
    result = _best_matching(current, historical)
    return {"valid": True, **result, "similarity": (result["score"] / 50) * 100}


def analyze_occurrences(current: Any, occurrences: Any) -> list[dict[str, Any]]:
    """Rows exactly as ``analyzeOccurrences`` builds them (``selected`` is not needed here)."""
    rows = []
    for index, occurrence in enumerate(occurrences if isinstance(occurrences, list) else []):
        occurrence = occurrence if isinstance(occurrence, dict) else {}
        preceding_valid = (occurrence.get("preceding_complete") is True
                           and valid_numbers(occurrence.get("preceding"), CONTEXT_LENGTH))
        context_valid = valid_numbers(occurrence.get("context"), SEQUENCE_LENGTH)
        following_valid = valid_numbers(occurrence.get("following"), FOLLOWING_LENGTH)
        score = score_context(current, occurrence["preceding"]) if preceding_valid else None
        rows.append({
            "id": occurrence["id"] if isinstance(occurrence.get("id"), str) else "",
            "context": occurrence.get("context"),
            "preceding": occurrence.get("preceding"),
            "following": occurrence.get("following"),
            "preceding_complete": occurrence.get("preceding_complete"),
            "preceding_lookup_status": occurrence.get("preceding_lookup_status") or "unavailable",
            "score": score,
            "preceding_valid": preceding_valid,
            "context_valid": context_valid,
            "following_valid": following_valid,
            "index": index,
            "approved": bool(score and score["valid"] and score["similarity"] >= MINIMUM_SIMILARITY
                             and context_valid),
        })
    return rows


def match_counts(current: Any, historical: Any) -> dict[str, int]:
    """Order-free matching that maximizes exact pairs, then neighbor pairs."""
    if not isinstance(current, list) or not isinstance(historical, list):
        return {"exact": 0, "neighbor": 0}
    best = {"exact": 0, "neighbor": 0}
    used: set[int] = set()

    def visit(index: int, exact: int, neighbor: int) -> None:
        nonlocal best
        if index == len(historical):
            if exact > best["exact"] or (exact == best["exact"] and neighbor > best["neighbor"]):
                best = {"exact": exact, "neighbor": neighbor}
            return
        visit(index + 1, exact, neighbor)
        for target_index, target in enumerate(current):
            if target_index in used:
                continue
            if historical[index] == target:
                kind = "exact"
            elif historical[index] in neighbors_of(target):
                kind = "neighbor"
            else:
                continue
            used.add(target_index)
            visit(index + 1, exact + (kind == "exact"), neighbor + (kind == "neighbor"))
            used.discard(target_index)

    visit(0, 0, 0)
    return best


def compare_distribution(left: Sequence[float], right: Sequence[float]) -> float:
    """More non-empty groups first, then the larger sorted counts."""
    left_sorted = sorted(left, reverse=True)
    right_sorted = sorted(right, reverse=True)
    left_groups = sum(1 for value in left if value > 0)
    right_groups = sum(1 for value in right if value > 0)
    if left_groups != right_groups:
        return right_groups - left_groups
    for index in range(max(len(left_sorted), len(right_sorted))):
        right_value = right_sorted[index] if index < len(right_sorted) else 0
        left_value = left_sorted[index] if index < len(left_sorted) else 0
        difference = right_value - left_value
        if difference:
            return difference
    return 0


def duplicate_count(values: Any) -> int:
    return len(values) - len(set(values)) if isinstance(values, list) else 0


def live_hit_distribution(row: dict[str, Any], live_numbers: Iterable[int]) -> list[int]:
    live = set(live_numbers)
    columns = (
        row["preceding"] if row["preceding_valid"] else None,
        row["context"] if row["context_valid"] else None,
        row["following"] if row["following_valid"] else None,
    )
    return [sum(1 for number in values if number in live) if isinstance(values, list) else 0
            for values in columns]


def _order_facts(row: dict[str, Any], search_sequence: Sequence[int], live: set[int],
                 selected: set[int]) -> dict[str, Any]:
    sequence = match_counts(list(search_sequence), row["context"])
    score = row["score"]
    return {
        "row": row,
        "sequence": sequence,
        "live": live_hit_distribution(row, live),
        "duplicates": duplicate_count(row["context"] if row["context_valid"] else None),
        "selected": [sum(1 for number in values if number in selected) if isinstance(values, list) else 0
                     for values in (row["preceding"], row["context"], row["following"])],
        "exact": (score["exact"] if score else 0) or 0,
        "neighbor": (score["neighbor"] if score else 0) or 0,
    }


def _compare_facts(left: dict[str, Any], right: dict[str, Any]) -> float:
    """``occurrenceOrder`` with every per-row value computed once."""
    difference = compare_distribution(
        [left["exact"], left["sequence"]["exact"], left["live"][2]],
        [right["exact"], right["sequence"]["exact"], right["live"][2]],
    )
    if difference:
        return difference
    difference = left["duplicates"] - right["duplicates"]
    if difference:
        return difference
    difference = compare_distribution(left["live"][:2], right["live"][:2])
    if difference:
        return difference
    difference = compare_distribution(left["selected"], right["selected"])
    if difference:
        return difference
    difference = compare_distribution(
        [left["neighbor"], left["sequence"]["neighbor"]],
        [right["neighbor"], right["sequence"]["neighbor"]],
    )
    if difference:
        return difference
    left_row, right_row = left["row"], right["row"]
    if not left_row["score"]:
        return 1 if right_row["score"] else left_row["index"] - right_row["index"]
    if not right_row["score"]:
        return -1
    return (right_row["score"]["score"] - left_row["score"]["score"]
            or right_row["score"]["exact"] - left_row["score"]["exact"]
            or left_row["index"] - right_row["index"])


def sort_occurrences(rows: Sequence[dict[str, Any]], search_sequence: Sequence[int],
                     live_numbers: Iterable[int] = (), selected_numbers: Iterable[int] = ()) -> list[dict[str, Any]]:
    """Table order of the page; live numbers are the results seen after the search."""
    live, selected = set(live_numbers), set(selected_numbers)
    facts = [_order_facts(row, search_sequence, live, selected) for row in rows]
    return [fact["row"] for fact in sorted(facts, key=cmp_to_key(_compare_facts))]


def rank_following(selected: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """``rankFollowing`` of the page: only the 5 following results of each occurrence."""
    results = [(number, row.get("id")) for row in selected
               if valid_numbers(row.get("following"), FOLLOWING_LENGTH) for number in row["following"]]
    return _rank(results)


# Columns used by the worker ranking (strategy 3): Anterior, Sequência, Posterior.
RANKING_COLUMNS = (
    ("preceding", "preceding_valid"),
    ("context", "context_valid"),
    ("following", "following_valid"),
)


def rank_columns(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Same scoring as the page, over the numbers of the three columns of each row.

    Every number counts (repeats included), also the ones equal to the current
    context or to the searched sequence; a column that is not valid is skipped.
    """
    results = [(number, row.get("id")) for row in rows for column, flag in RANKING_COLUMNS
               if row.get(flag) for number in row[column]]
    return _rank(results)


def _rank(results: Sequence[tuple[int, Any]]) -> dict[str, Any]:
    """10 points to each number and 8 to each wheel neighbor, ranked like the page."""
    scores = [{"number": number, "score": 0, "exact": 0, "neighbor": 0,
               "exact_sources": [], "neighbor_sources": []} for number in range(37)]
    for number, source in results:
        exact = scores[number]
        exact["score"] += EXACT_POINTS
        exact["exact"] += 1
        exact["exact_sources"].append(source)
        for neighbor_number in neighbors_of(number):
            neighbor = scores[neighbor_number]
            neighbor["score"] += NEIGHBOR_POINTS
            neighbor["neighbor"] += 1
            neighbor["neighbor_sources"].append(source)
    maximum = len(results) * EXACT_POINTS
    ranking = sorted(
        ({**row, "percentage": (row["score"] / maximum) * 100 if maximum else 0} for row in scores),
        key=lambda row: (-row["score"], -row["exact"], -row["neighbor"], row["number"]),
    )
    return {"ranking": ranking, "analyzed_results": len(results), "maximum": maximum}
