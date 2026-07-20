from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

from shared.python.roulette.orbit.probability import softmax

from .uncertainty import ProbabilityInterval, conservative_exclusions, ensemble_intervals


@dataclass(frozen=True, slots=True)
class EnsemblePrediction:
    probabilities: Mapping[int, float]
    ranking: tuple[int, ...]
    intervals: Mapping[int, ProbabilityInterval]
    exclusions: tuple[int, ...]
    components: int


def combine_probability_models(
    probability_rows: Sequence[Mapping[int, float]],
    *,
    weights: Sequence[float] | None = None,
) -> EnsemblePrediction:
    if not probability_rows:
        raise ValueError("nenhum modelo para combinar")
    safe_weights = tuple(float(value) for value in (weights or [1.0] * len(probability_rows)))
    if len(safe_weights) != len(probability_rows):
        raise ValueError("quantidade de pesos difere dos modelos")
    if sum(max(0.0, value) for value in safe_weights) <= 0:
        raise ValueError("ao menos um peso precisa ser positivo")
    log_scores: dict[int, float] = {}
    for number in range(37):
        log_scores[number] = sum(
            max(0.0, weight) * math.log(max(1e-15, float(row.get(number, 0.0))))
            for row, weight in zip(probability_rows, safe_weights)
        ) / sum(max(0.0, value) for value in safe_weights)
    probabilities = softmax(log_scores)
    ranking = tuple(sorted(range(37), key=lambda number: (-probabilities[number], number)))
    intervals = ensemble_intervals(probability_rows)
    exclusions = conservative_exclusions(intervals)
    return EnsemblePrediction(
        probabilities=probabilities,
        ranking=ranking,
        intervals=intervals,
        exclusions=exclusions,
        components=len(probability_rows),
    )
