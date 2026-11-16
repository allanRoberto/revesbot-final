"""Rules of the pair bet.

From the top 7 numbers of the contextual ranking: when exactly two of them are from 0 to 9
(the bases), each base forms a group made of

* its terminals (same last digit);
* the mirror of the base, from the fixed mirror list;
* the numbers whose digit sum (digital root) is the base.

A number is kept when one of its wheel neighbors belongs to the group of the other base
(a number that belongs to both groups is kept too). The bet is every kept number plus one
wheel neighbor on each side, the two numbers of the pair themselves (without their neighbors)
and the protection numbers.

Protection numbers: a number of the wheel whose two neighbors belong one to each group sits
between the groups. It and its two neighbors (a wheel triple) protect the bet. Example, pair
4 and 5: 17 is between 25 (group of 5) and 34 (group of 4), so 25, 17 and 34 are protection
numbers; 15, 19 and 4 are another triple of the same pair.
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

from contextual_ranking.rules import WHEEL, neighbors_of

BASE_LIMIT = 9  # bases are the ranking numbers from 0 to BASE_LIMIT
# Strategy switches. Changing them changes the bets: bump PAIRS_VERSION, unless the history is kept
# on purpose (see the note in __init__.py about the 2026-11-16 changes).
INCLUDE_PAIR_NUMBERS = True  # the two numbers of the pair are always in the bet, without their neighbors
INCLUDE_PROTECTION = True  # the numbers between a number of one group and a number of the other are in the bet
IGNORED_PAIRS: frozenset[tuple[int, int]] = frozenset({(6, 9)})  # exceptions: these pairs never open a signal
MIRROR_PAIRS = ((1, 10), (2, 20), (3, 30), (6, 9), (12, 21), (13, 31), (14, 34), (16, 19), (23, 32), (26, 29))
MIRROR: dict[int, int] = {}
for _left, _right in MIRROR_PAIRS:
    MIRROR[_left], MIRROR[_right] = _right, _left
_WHEEL_POSITION = {number: index for index, number in enumerate(WHEEL)}


def digital_root(number: int) -> int:
    while number >= 10:
        number = number // 10 + number % 10
    return number


def group(base: int) -> list[int]:
    """Terminals of the base, the mirror of the base and the numbers whose digit sum is the base."""
    members = [number for number in range(len(WHEEL)) if number % 10 == base]
    mirror = MIRROR.get(base)
    if mirror is not None and mirror not in members:
        members.append(mirror)
    for number in range(10, len(WHEEL)):
        if digital_root(number) == base and number not in members:
            members.append(number)
    return members


def kept_numbers(first: int, second: int) -> list[int]:
    """Numbers of one group that are wheel neighbors of a number of the other group."""
    group_a, group_b = group(first), group(second)
    kept: list[int] = []
    for number, other in [(n, group_b) for n in group_a] + [(n, group_a) for n in group_b]:
        in_both = number in group_a and number in group_b
        if (in_both or any(neighbor in other for neighbor in neighbors_of(number))) and number not in kept:
            kept.append(number)
    return kept


def protection_triples(first: int, second: int) -> list[list[int]]:
    """Wheel triples [left, middle, right] whose neighbors belong one to each group (in wheel order).

    The middle number sits between a number of one group and a number of the other; a number that
    belongs to both groups counts for either side.
    """
    group_a, group_b = set(group(first)), set(group(second))
    triples: list[list[int]] = []
    for middle in WHEEL:
        left, right = neighbors_of(middle)
        if (left in group_a and right in group_b) or (left in group_b and right in group_a):
            triples.append([left, middle, right])
    return triples


def wheel_arcs(numbers: Iterable[int]) -> list[list[int]]:
    """Group numbers into runs of adjacent pockets of the wheel (circular), in wheel order."""
    present = {_WHEEL_POSITION[number] for number in set(numbers)}
    if not present:
        return []
    size = len(WHEEL)
    if len(present) == size:
        return [list(WHEEL)]
    start = next(position for position in sorted(present) if (position - 1) % size not in present)
    arcs: list[list[int]] = []
    current: list[int] = []
    for offset in range(size):
        position = (start + offset) % size
        if position in present:
            current.append(WHEEL[position])
        elif current:
            arcs.append(current)
            current = []
    if current:
        arcs.append(current)
    return arcs


def pair_bet(top_numbers: Sequence[int]) -> dict[str, Any]:
    """The bet for a ranking.

    ``kind`` tells what happened: ``ok`` (a bet exists), ``no_pair`` (fewer than two numbers
    from 0 to 9), ``too_many`` (three or more, ignored), ``ignored`` (a pair listed in
    ``IGNORED_PAIRS``) or ``no_intersection`` (a pair, but no number of one group is a neighbor
    of the other group).

    ``protection`` lists only the protection numbers the rest of the bet did not already have;
    ``protection_triples`` keeps the wheel triples they come from (the reason of each number).
    """
    bases = [number for number in top_numbers if 0 <= number <= BASE_LIMIT]
    info: dict[str, Any] = {"kind": "no_pair", "bases": bases, "pair": None, "kept": [], "bet": [], "arcs": [],
                            "protection": [], "protection_triples": []}
    if len(bases) < 2:
        return info
    if len(bases) > 2:
        info["kind"] = "too_many"
        return info
    pair = sorted(bases)
    info["pair"] = pair
    if (pair[0], pair[1]) in IGNORED_PAIRS:
        info["kind"] = "ignored"
        return info
    kept = kept_numbers(pair[0], pair[1])
    if not kept:
        info["kind"] = "no_intersection"
        return info
    members: set[int] = set()
    for number in kept:
        members.update((number, *neighbors_of(number)))
    if INCLUDE_PAIR_NUMBERS:
        members.update(pair)
    protection: list[int] = []
    if INCLUDE_PROTECTION:
        triples = protection_triples(pair[0], pair[1])
        protection = sorted({number for triple in triples for number in triple} - members)
        members.update(protection)
        info["protection_triples"] = triples
    bet = sorted(members)
    info.update(kind="ok", kept=sorted(kept), bet=bet, arcs=wheel_arcs(bet), protection=protection)
    return info
