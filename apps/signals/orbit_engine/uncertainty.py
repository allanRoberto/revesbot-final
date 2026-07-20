from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True, slots=True)
class ProbabilityInterval:
    number: int
    mean: float
    standard_deviation: float
    lower: float
    upper: float


def ensemble_intervals(
    probability_rows: Sequence[Mapping[int, float]],
    *,
    z_score: float = 1.96,
) -> dict[int, ProbabilityInterval]:
    if not probability_rows:
        raise ValueError("ensemble vazio")
    result: dict[int, ProbabilityInterval] = {}
    for number in range(37):
        values = [float(row.get(number, 0.0)) for row in probability_rows]
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / max(1, len(values) - 1)
        deviation = math.sqrt(max(0.0, variance))
        margin = float(z_score) * deviation
        result[number] = ProbabilityInterval(
            number=number,
            mean=mean,
            standard_deviation=deviation,
            lower=max(0.0, mean - margin),
            upper=min(1.0, mean + margin),
        )
    return result


def conservative_exclusions(
    intervals: Mapping[int, ProbabilityInterval],
    *,
    upper_threshold: float = 1.0 / 37.0,
    maximum: int = 25,
) -> tuple[int, ...]:
    eligible = [item for item in intervals.values() if item.upper < float(upper_threshold)]
    eligible.sort(key=lambda item: (item.upper, item.mean, item.number))
    return tuple(item.number for item in eligible[: max(0, int(maximum))])
