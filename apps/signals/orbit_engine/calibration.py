from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from shared.python.roulette.orbit.probability import ConformalSetCalibrator, TemperatureCalibrator, softmax


@dataclass(slots=True)
class OrbitCalibration:
    alpha: float = 0.10
    temperature: TemperatureCalibrator = field(default_factory=TemperatureCalibrator)
    conformal: ConformalSetCalibrator = field(init=False)

    def __post_init__(self) -> None:
        self.conformal = ConformalSetCalibrator(alpha=self.alpha)

    def fit(self, score_rows: Sequence[Mapping[int, float]], targets: Sequence[int]) -> "OrbitCalibration":
        self.temperature.fit(score_rows, targets)
        probability_rows = [softmax(row, self.temperature.temperature) for row in score_rows]
        self.conformal.fit(probability_rows, targets)
        return self

    def calibrate(self, scores: Mapping[int, float]) -> tuple[dict[int, float], tuple[int, ...]]:
        probabilities = softmax(scores, self.temperature.temperature)
        return probabilities, self.conformal.prediction_set(probabilities)

    def to_dict(self) -> dict[str, float | int]:
        return {
            "temperature": self.temperature.temperature,
            "conformal_alpha": self.conformal.alpha,
            "conformal_threshold": self.conformal.threshold,
            "calibration_size": self.conformal.calibration_size,
        }
