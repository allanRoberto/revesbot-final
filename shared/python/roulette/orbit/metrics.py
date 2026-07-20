"""Metricas honestas para ranking, horizonte e exclusao."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from .schemas import Prediction


def random_hit_probability(k: int, horizon: int = 1) -> float:
    safe_k = max(0, min(37, int(k)))
    safe_horizon = max(1, int(horizon))
    return 1.0 - ((37 - safe_k) / 37.0) ** safe_horizon


@dataclass(slots=True)
class EvaluationAccumulator:
    decisions: int = 0
    top9_hits_next: int = 0
    top12_hits_next: int = 0
    top9_hit_any_horizon: int = 0
    top12_hit_any_horizon: int = 0
    exclusion_leaks: int = 0
    exclusion_claims: int = 0
    abstentions: int = 0
    log_loss_sum: float = 0.0
    brier_sum: float = 0.0

    def add(self, prediction: Prediction, targets: Sequence[int]) -> None:
        if not targets:
            return
        target_values = tuple(int(value) for value in targets)
        next_target = target_values[0]
        top9 = set(prediction.selected_top9)
        top12 = set(prediction.selected_top12)
        excluded = set(prediction.excluded)
        probability_map = {row.number: row.probability for row in prediction.ranking}
        probability = max(1e-15, float(probability_map.get(next_target, 0.0)))

        self.decisions += 1
        self.top9_hits_next += int(next_target in top9)
        self.top12_hits_next += int(next_target in top12)
        self.top9_hit_any_horizon += int(any(target in top9 for target in target_values))
        self.top12_hit_any_horizon += int(any(target in top12 for target in target_values))
        self.exclusion_claims += len(excluded) * len(target_values)
        self.exclusion_leaks += sum(1 for target in target_values if target in excluded)
        self.abstentions += int(prediction.abstained)
        self.log_loss_sum += -math.log(probability)
        self.brier_sum += sum(
            (float(probability_map.get(number, 0.0)) - (1.0 if number == next_target else 0.0)) ** 2
            for number in range(37)
        )

    def to_dict(self, horizon: int = 1) -> dict[str, float | int]:
        denominator = max(1, self.decisions)
        safe_horizon = max(1, int(horizon))
        top9_rate = self.top9_hits_next / denominator
        top12_rate = self.top12_hits_next / denominator
        return {
            "decisions": self.decisions,
            "top9_at_1": top9_rate,
            "top12_at_1": top12_rate,
            "top9_hit_any_horizon": self.top9_hit_any_horizon / denominator,
            "top12_hit_any_horizon": self.top12_hit_any_horizon / denominator,
            "top9_random_at_1": 9 / 37.0,
            "top12_random_at_1": 12 / 37.0,
            "top9_random_at_horizon": random_hit_probability(9, safe_horizon),
            "top12_random_at_horizon": random_hit_probability(12, safe_horizon),
            "top9_lift_at_1": (top9_rate / (9 / 37.0)) if self.decisions else 0.0,
            "top12_lift_at_1": (top12_rate / (12 / 37.0)) if self.decisions else 0.0,
            "exclusion_leak_rate": (
                self.exclusion_leaks / self.exclusion_claims if self.exclusion_claims else 0.0
            ),
            "exclusion_claims": self.exclusion_claims,
            "abstention_rate": self.abstentions / denominator,
            "multiclass_log_loss": self.log_loss_sum / denominator,
            "brier_score": self.brier_sum / denominator,
        }


def evaluate_predictions(
    rows: Iterable[tuple[Prediction, Sequence[int]]],
    *,
    horizon: int = 1,
) -> dict[str, float | int]:
    accumulator = EvaluationAccumulator()
    for prediction, targets in rows:
        accumulator.add(prediction, tuple(targets)[: max(1, int(horizon))])
    return accumulator.to_dict(horizon=horizon)
