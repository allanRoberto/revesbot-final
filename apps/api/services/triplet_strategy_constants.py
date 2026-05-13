from __future__ import annotations

from typing import List, Set, Tuple


MONITORED_ROULETTES: List[str] = [
    "pragmatic-auto-roulette",
    "pragmatic-brazilian-roulette",
    "pragmatic-mega-roulette",
]

POSITIONS: int = 3
TOP_N: int = 14
MAX_ATTEMPTS: int = 4

EUROPEAN_WHEEL: List[int] = [
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23,
    10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26,
]

WHEEL_INDEX: dict = {n: i for i, n in enumerate(EUROPEAN_WHEEL)}
WHEEL_LEN: int = len(EUROPEAN_WHEEL)

MIRROR_PAIRS: List[Tuple[int, int]] = [(12, 21), (13, 31), (23, 32)]
MIRROR_LOOKUP: dict = {}
for _a, _b in MIRROR_PAIRS:
    MIRROR_LOOKUP[_a] = _b
    MIRROR_LOOKUP[_b] = _a


def are_wheel_neighbors(x: int, y: int) -> bool:
    if x == y:
        return False
    ix = WHEEL_INDEX.get(x)
    iy = WHEEL_INDEX.get(y)
    if ix is None or iy is None:
        return False
    diff = abs(ix - iy)
    return diff == 1 or diff == WHEEL_LEN - 1


def are_mirrors(x: int, y: int) -> bool:
    return MIRROR_LOOKUP.get(x) == y


def evaluate_skip(a: int, b: int, c: int) -> Tuple[bool, str]:
    if 0 in (a, b, c):
        return True, "contem_zero"
    nums = [a, b, c]
    if len(set(nums)) < 3:
        return True, "repetido"
    pairs = [(a, b), (b, c), (a, c)]
    for x, y in pairs:
        if are_wheel_neighbors(x, y):
            return True, f"vizinho:{x}-{y}"
    for x, y in pairs:
        if are_mirrors(x, y):
            return True, f"espelho:{x}-{y}"
    return False, ""


def assemble_bet_numbers(top_numbers: List[int]) -> List[int]:
    nums = list(top_numbers)
    if 0 not in nums:
        nums.append(0)
    return nums
