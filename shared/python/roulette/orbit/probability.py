"""Normalizacao, calibracao e conjuntos de previsao."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence


def softmax(scores: Mapping[int, float], temperature: float = 1.0) -> dict[int, float]:
    safe_temperature = max(1e-6, float(temperature))
    if not scores:
        return {}
    maximum = max(float(value) / safe_temperature for value in scores.values())
    exponentials = {
        int(number): math.exp((float(value) / safe_temperature) - maximum)
        for number, value in scores.items()
    }
    total = sum(exponentials.values())
    if total <= 0:
        uniform = 1.0 / len(exponentials)
        return {number: uniform for number in exponentials}
    return {number: value / total for number, value in exponentials.items()}


def multiclass_log_loss(probabilities: Mapping[int, float], target: int) -> float:
    probability = max(1e-15, min(1.0, float(probabilities.get(int(target), 0.0))))
    return -math.log(probability)


@dataclass(slots=True)
class TemperatureCalibrator:
    temperature: float = 1.0

    def fit(
        self,
        score_rows: Sequence[Mapping[int, float]],
        targets: Sequence[int],
        grid: Iterable[float] | None = None,
    ) -> "TemperatureCalibrator":
        if len(score_rows) != len(targets):
            raise ValueError("scores e targets precisam ter o mesmo tamanho")
        candidates = tuple(
            grid
            or (
                0.35,
                0.5,
                0.7,
                0.85,
                1.0,
                1.2,
                1.5,
                2.0,
                3.0,
                5.0,
                7.5,
                10.0,
                15.0,
                20.0,
                30.0,
                50.0,
                75.0,
                100.0,
                150.0,
                200.0,
            )
        )
        if not score_rows:
            self.temperature = 1.0
            return self
        best_temperature = 1.0
        best_loss = float("inf")
        for temperature in candidates:
            loss = sum(
                multiclass_log_loss(softmax(scores, temperature), target)
                for scores, target in zip(score_rows, targets)
            ) / len(score_rows)
            if loss < best_loss:
                best_loss = loss
                best_temperature = float(temperature)
        self.temperature = best_temperature
        return self


@dataclass(slots=True)
class ConformalSetCalibrator:
    alpha: float = 0.10
    threshold: float = 1.0
    calibration_size: int = 0

    def fit(
        self,
        probability_rows: Sequence[Mapping[int, float]],
        targets: Sequence[int],
    ) -> "ConformalSetCalibrator":
        if len(probability_rows) != len(targets):
            raise ValueError("probabilidades e targets precisam ter o mesmo tamanho")
        scores = sorted(
            1.0 - float(probabilities.get(int(target), 0.0))
            for probabilities, target in zip(probability_rows, targets)
        )
        self.calibration_size = len(scores)
        if not scores:
            self.threshold = 1.0
            return self
        rank = math.ceil((len(scores) + 1) * (1.0 - float(self.alpha)))
        rank = max(1, min(len(scores), rank))
        self.threshold = scores[rank - 1]
        return self

    def prediction_set(self, probabilities: Mapping[int, float]) -> tuple[int, ...]:
        minimum_probability = 1.0 - float(self.threshold)
        return tuple(sorted(
            (int(number) for number, probability in probabilities.items() if float(probability) >= minimum_probability),
            key=lambda number: (-float(probabilities[number]), number),
        ))
