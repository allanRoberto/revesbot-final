"""Quality tags of a pair signal, decided when it opens (before any result of its own). No I/O.

Both rules come from the reading of 1,070 closed signals on 17/11/2026 (docs/design/pares-similaridade-contextual.md).
Every pair has one fixed bet and how often a signal closes depends mostly on the size of that bet (8 to 22 numbers).
Inside each size the signals were split by how long ago a number of the bet last came out before the signal:
"exact near" is a number of the bet among the last 2 results (the trigger is the first), "exact far" is none of them.

* ``high_quality``: a bet of 8 to 11 numbers and the exact far. 84 signals, 82 hits (97.6%), against 83.6% with the
  exact near.
* ``watch_12_15_exact_near``: a bet of 12 to 15 numbers and the exact near. 285 signals, 278 hits (97.5%); only
  watched, to see whether that rate holds.

They are monitoring tags found by cutting the same data many ways, not proven rules. A tag only records that the
condition held when the signal opened, so its hit rate can be measured on the signals opened after the rule went live
(``entry_context.rule`` tells which version of the rule tagged a signal).
"""
from __future__ import annotations

from typing import Any, Sequence

QUALITY_RULE = 1  # bump when a condition below changes; stored in every ``entry_context``
LOOKBACK = 10  # results looked at before the signal, the trigger being the first
NEAR_DISTANCE = 2  # "near": a number of the bet came out in the last 2 results

HIGH_QUALITY = "high_quality"
WATCH_NEAR = "watch_12_15_exact_near"
TAGS = (HIGH_QUALITY, WATCH_NEAR)

SMALL_BET = range(8, 12)  # 8 to 11 numbers
MEDIUM_BET = range(12, 16)  # 12 to 15 numbers


def last_exact_distance(bet: Sequence[int], numbers: Sequence[int], lookback: int = LOOKBACK) -> int | None:
    """How many results back (the latest is 1) a number of the bet came out; None when none did in the lookback."""
    wanted = set(bet)
    for distance, number in enumerate(reversed(list(numbers)[-lookback:]), start=1):
        if number in wanted:
            return distance
    return None


def entry_context(bet: Sequence[int], numbers: Sequence[int]) -> dict[str, Any] | None:
    """What the tags look at. ``numbers`` are the latest results, oldest first, the last one being the trigger.

    ``None`` when there are not enough results to look back (the signal is then not tagged)."""
    if len(numbers) < LOOKBACK:
        return None
    return {"rule": QUALITY_RULE, "chips": len(bet), "last_exact_distance": last_exact_distance(bet, numbers)}


def quality_tags(context: dict[str, Any] | None) -> list[str]:
    """The tags of a signal, from its entry context."""
    if not context:
        return []
    chips, distance = context["chips"], context["last_exact_distance"]
    near = distance is not None and distance <= NEAR_DISTANCE
    tags: list[str] = []
    if chips in SMALL_BET and not near:
        tags.append(HIGH_QUALITY)
    if chips in MEDIUM_BET and near:
        tags.append(WATCH_NEAR)
    return tags
