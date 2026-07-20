from __future__ import annotations

from collections import Counter
from typing import Mapping, Sequence


def _normalize(counts: Mapping[int, float]) -> dict[int, float]:
    total = sum(float(counts.get(number, 0.0)) for number in range(37))
    if total <= 0:
        return {number: 1.0 / 37.0 for number in range(37)}
    return {number: float(counts.get(number, 0.0)) / total for number in range(37)}


class UniformBaseline:
    def predict_proba(self, pivot: int | None = None) -> dict[int, float]:
        return {number: 1.0 / 37.0 for number in range(37)}


class FrequencyBaseline:
    def __init__(self, alpha: float = 1.0) -> None:
        self.alpha = max(0.0, float(alpha))
        self.counts = Counter({number: self.alpha for number in range(37)})

    def fit(self, history_chronological: Sequence[int]) -> "FrequencyBaseline":
        self.counts = Counter({number: self.alpha for number in range(37)})
        self.counts.update(int(value) for value in history_chronological)
        return self

    def predict_proba(self, pivot: int | None = None) -> dict[int, float]:
        return _normalize(self.counts)


class PivotConditionalBaseline:
    def __init__(self, alpha: float = 1.0) -> None:
        self.alpha = max(0.0, float(alpha))
        self.counts = {
            pivot: Counter({number: self.alpha for number in range(37)})
            for pivot in range(37)
        }

    def fit(self, history_chronological: Sequence[int]) -> "PivotConditionalBaseline":
        self.counts = {
            pivot: Counter({number: self.alpha for number in range(37)})
            for pivot in range(37)
        }
        for pivot, target in zip(history_chronological, history_chronological[1:]):
            self.counts[int(pivot)][int(target)] += 1
        return self

    def predict_proba(self, pivot: int | None = None) -> dict[int, float]:
        if pivot is None or int(pivot) not in self.counts:
            return {number: 1.0 / 37.0 for number in range(37)}
        return _normalize(self.counts[int(pivot)])
