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

``supremo`` (fixed on 24/11/2026 for a live test, see docs/design/pares-similaridade-contextual.md) looks at the
ranking instead: the 7 numbers of the ranking are added up and the sum is reduced to one digit (149 -> 14 -> 5). The
signal is "Supremo" when that digit is 5, 6 or 7 and the bet has 9, 10, 11, 14, 19, 20, 21 or 22 numbers. It is played
only on the first results: up to the 2nd with the digit 5 or 6, only the 1st with the digit 7 (``play_until``). Found
on the 6,481 signals of 16 to 24/11/2026 (1,081 Supremo signals, +14.2% with R$ 1 per number); it only counts on the
signals opened after it went live. Its context is kept apart (``supremo_context``) so ``entry_context`` is unchanged.
"""
from __future__ import annotations

from typing import Any, Sequence

from contextual_pairs.rules import digital_root

QUALITY_RULE = 1  # bump when a condition below changes; stored in every ``entry_context``
LOOKBACK = 10  # results looked at before the signal, the trigger being the first
NEAR_DISTANCE = 2  # "near": a number of the bet came out in the last 2 results

HIGH_QUALITY = "high_quality"
WATCH_NEAR = "watch_12_15_exact_near"
SUPREMO = "supremo"
TAGS = (HIGH_QUALITY, WATCH_NEAR, SUPREMO)

SUPREMO_RULE = 1  # never changes during the live test; a new rule needs a new tag name
RANKING_SIZE = 7  # the top of the ranking the sum is made of
SUPREMO_CHIPS = frozenset({9, 10, 11, 14, 19, 20, 21, 22})
SUPREMO_PLAY_UNTIL = {5: 2, 6: 2, 7: 1}  # digit of the sum -> last result played

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


def supremo_context(bet: Sequence[int], top: Sequence[int]) -> dict[str, Any] | None:
    """Sum of the 7 numbers of the ranking, its digit and how far a Supremo signal is played.

    Recorded for every signal (``play_until`` is None when the digit is not 5, 6 or 7); ``None`` when the ranking does
    not have 7 numbers."""
    if len(top) != RANKING_SIZE:
        return None
    total = sum(top)
    root = digital_root(total)
    return {"rule": SUPREMO_RULE, "chips": len(bet), "rank_sum": total, "rank_root": root,
            "play_until": SUPREMO_PLAY_UNTIL.get(root)}


def supremo_tags(context: dict[str, Any] | None) -> list[str]:
    if not context or context.get("play_until") is None:
        return []
    return [SUPREMO] if context["chips"] in SUPREMO_CHIPS else []


def supremo_result(signal: dict[str, Any]) -> tuple[bool, int, int] | None:
    """(won, staked, net) of a closed Supremo signal played with R$ 1 per number; None for other signals.

    The signal is played on each result up to ``play_until`` and stops at its first hit; a hit later than that is a
    loss for the Supremo bet even when the signal itself closed as a hit."""
    context = signal.get("supremo")
    if SUPREMO not in (signal.get("tags") or []) or not context:
        return None
    last = context["play_until"]
    chips = len(signal.get("bet") or [])
    attempt = signal.get("hit_attempt") if signal.get("hit") else None
    won = attempt is not None and attempt <= last
    played = attempt if won else last
    staked = chips * played
    return won, staked, (36 if won else 0) - staked
