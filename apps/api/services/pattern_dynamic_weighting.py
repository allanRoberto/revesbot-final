from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Sequence


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class DynamicWeightConfig:
    """Hyperparameters for offline dynamic pattern weighting."""

    prior_strength: float = 24.0
    min_sample: int = 20
    full_sample: int = 120
    weight_floor: float = 0.75
    weight_ceil: float = 1.30
    lift_alpha: float = 0.85
    smoothing_alpha: float = 0.35
    recent_window: int = 30
    recent_decay_start: int = 2
    recent_decay_per_miss: float = 0.05
    recent_decay_cap: float = 0.25

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prior_strength": float(self.prior_strength),
            "min_sample": int(self.min_sample),
            "full_sample": int(self.full_sample),
            "weight_floor": float(self.weight_floor),
            "weight_ceil": float(self.weight_ceil),
            "lift_alpha": float(self.lift_alpha),
            "smoothing_alpha": float(self.smoothing_alpha),
            "recent_window": int(self.recent_window),
            "recent_decay_start": int(self.recent_decay_start),
            "recent_decay_per_miss": float(self.recent_decay_per_miss),
            "recent_decay_cap": float(self.recent_decay_cap),
        }


def _recent_miss_streak(recent_outcomes: Sequence[bool], window: int) -> int:
    streak = 0
    for outcome in list(recent_outcomes)[: max(1, int(window))]:
        if outcome:
            break
        streak += 1
    return streak


def _sample_gate(sample_size: int, min_sample: int, full_sample: int) -> float:
    if sample_size <= min_sample:
        return 0.0
    if full_sample <= min_sample:
        return 1.0
    return _clamp((sample_size - min_sample) / (full_sample - min_sample), 0.0, 1.0)


def compute_dynamic_weights(
    pattern_metrics: Mapping[str, Mapping[str, Any]],
    *,
    baseline_hit_rate: float,
    previous_weights: Mapping[str, float] | None = None,
    config: DynamicWeightConfig | None = None,
) -> Dict[str, Any]:
    """
    Computes dynamic weights offline.

    Expected metric fields per pattern:
    - sample_size: int
    - hits_at_4: int
    - recent_outcomes: list[bool] ordered from most recent to oldest
    """

    cfg = config or DynamicWeightConfig()
    prev = dict(previous_weights or {})
    base_rate = _clamp(float(baseline_hit_rate), 1e-4, 1.0)

    weights: Dict[str, float] = {}
    details: Dict[str, Dict[str, Any]] = {}

    for pattern_id, raw in sorted(pattern_metrics.items(), key=lambda kv: kv[0]):
        sample_size = max(0, int(raw.get("sample_size", 0) or 0))
        hits_at_4 = max(0, int(raw.get("hits_at_4", 0) or 0))
        recent_outcomes = raw.get("recent_outcomes", [])
        if not isinstance(recent_outcomes, list):
            recent_outcomes = []

        prior_hits = float(base_rate * cfg.prior_strength)
        posterior_rate = (hits_at_4 + prior_hits) / (sample_size + cfg.prior_strength)
        lift = posterior_rate / base_rate

        sample_gate = _sample_gate(
            sample_size=sample_size,
            min_sample=max(1, int(cfg.min_sample)),
            full_sample=max(int(cfg.min_sample) + 1, int(cfg.full_sample)),
        )

        miss_streak = _recent_miss_streak(recent_outcomes, window=max(1, int(cfg.recent_window)))
        if miss_streak <= int(cfg.recent_decay_start):
            recent_decay = 0.0
        else:
            extra = miss_streak - int(cfg.recent_decay_start)
            recent_decay = _clamp(extra * float(cfg.recent_decay_per_miss), 0.0, float(cfg.recent_decay_cap))

        raw_target = 1.0 + ((lift - 1.0) * float(cfg.lift_alpha) * sample_gate)
        raw_target *= (1.0 - recent_decay)
        target_weight = _clamp(raw_target, float(cfg.weight_floor), float(cfg.weight_ceil))

        prev_weight = float(prev.get(pattern_id, 1.0))
        smoothed_weight = (prev_weight * (1.0 - float(cfg.smoothing_alpha))) + (
            target_weight * float(cfg.smoothing_alpha)
        )
        dynamic_weight = _clamp(smoothed_weight, float(cfg.weight_floor), float(cfg.weight_ceil))

        weights[pattern_id] = round(dynamic_weight, 6)
        details[pattern_id] = {
            "sample_size": sample_size,
            "hits_at_4": hits_at_4,
            "posterior_rate": round(float(posterior_rate), 6),
            "lift": round(float(lift), 6),
            "sample_gate": round(float(sample_gate), 6),
            "recent_miss_streak": int(miss_streak),
            "recent_decay": round(float(recent_decay), 6),
            "target_weight": round(float(target_weight), 6),
            "previous_weight": round(float(prev_weight), 6),
            "dynamic_weight": round(float(dynamic_weight), 6),
        }

    return {
        "baseline_hit_rate": round(base_rate, 6),
        "weights": weights,
        "details": details,
        "config": cfg.to_dict(),
    }

