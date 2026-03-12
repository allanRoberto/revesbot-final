from __future__ import annotations

import math
from datetime import datetime, timedelta, date
from typing import Dict, List, Set, Tuple

import pytz

# --- Configuração de layout da roleta europeia (sentido horário) ---
EURO_WHEEL_ORDER: List[int] = [
    0,
    32, 15, 19, 4, 21, 2, 25, 17, 34, 6,
    27, 13, 36, 11, 30, 8, 23, 10, 5, 24,
    16, 33, 1, 20, 14, 31, 9, 22, 18, 29,
    7, 28, 12, 35, 3, 26,
]

NUM2IDX: Dict[int, int] = {n: i for i, n in enumerate(EURO_WHEEL_ORDER)}
IDX2NUM: Dict[int, int] = {i: n for i, n in enumerate(EURO_WHEEL_ORDER)}
WHEEL_SIZE = len(EURO_WHEEL_ORDER)


def slide_window_wrap(vec: List[int], window_size: int) -> Tuple[int, int]:
    assert window_size % 2 == 1, "window_size deve ser ímpar"
    half = window_size // 2

    s = 0
    for offset in range(-half, half + 1):
        s += vec[(0 + offset) % WHEEL_SIZE]
    best_sum = s
    best_center = 0

    for c in range(1, WHEEL_SIZE):
        out_idx = (c - 1 - half) % WHEEL_SIZE
        in_idx = (c + half) % WHEEL_SIZE
        s = s - vec[out_idx] + vec[in_idx]
        if s > best_sum:
            best_sum = s
            best_center = c

    return best_center, best_sum


def sector_indices(center_idx: int, neighbor_span: int) -> List[int]:
    return [(center_idx + k) % WHEEL_SIZE for k in range(-neighbor_span, neighbor_span + 1)]


def indices_to_numbers(indices: List[int]) -> List[int]:
    return [IDX2NUM[i] for i in indices]


def cosine_similarity(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def count_vector_for_day(numbers: List[int]) -> List[int]:
    vec = [0] * WHEEL_SIZE
    for n in numbers:
        idx = NUM2IDX.get(n)
        if idx is not None:
            vec[idx] += 1
    return vec


def add_vectors(a: List[int], b: List[int]) -> None:
    for i in range(WHEEL_SIZE):
        a[i] += b[i]


def overlap_size(a_indices: Set[int], b_indices: Set[int]) -> int:
    return len(a_indices.intersection(b_indices))


def get_br_timezone() -> pytz.BaseTzInfo:
    return pytz.timezone("America/Sao_Paulo")


def parse_time_window(time_str: str, interval: int) -> Tuple[int, int, int, int]:
    base_hour, base_minute = map(int, time_str.split(":"))

    start_minute = base_minute - interval
    end_minute = base_minute + interval
    start_hour = base_hour
    end_hour = base_hour

    if start_minute < 0:
        start_hour = (base_hour - 1) % 24
        start_minute = 60 + start_minute
    if end_minute >= 60:
        end_hour = (base_hour + 1) % 24
        end_minute = end_minute % 60

    return start_hour, start_minute, end_hour, end_minute

