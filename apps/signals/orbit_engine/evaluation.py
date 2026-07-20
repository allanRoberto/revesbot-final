from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from shared.python.roulette.orbit.metrics import EvaluationAccumulator
from shared.python.roulette.orbit.schemas import ReplayDecision
from shared.python.roulette.orbit.scoring import OrbitalRuleScorer

from .baselines import FrequencyBaseline, PivotConditionalBaseline, UniformBaseline
from .calibration import OrbitCalibration
from .replay import RuleReplayRunner, prediction_from_probabilities


@dataclass(frozen=True, slots=True)
class ConfidenceInterval:
    estimate: float
    lower: float
    upper: float
    confidence: float


def wilson_interval(successes: int, total: int, z_score: float = 1.96) -> ConfidenceInterval:
    if total <= 0:
        return ConfidenceInterval(0.0, 0.0, 0.0, 0.95)
    proportion = successes / total
    z2 = z_score * z_score
    denominator = 1.0 + z2 / total
    center = (proportion + z2 / (2 * total)) / denominator
    margin = (
        z_score
        * math.sqrt((proportion * (1 - proportion) / total) + (z2 / (4 * total * total)))
        / denominator
    )
    return ConfidenceInterval(proportion, max(0.0, center - margin), min(1.0, center + margin), 0.95)


def block_bootstrap_mean(
    values: Sequence[float],
    *,
    block_size: int = 100,
    iterations: int = 1000,
    seed: int = 42,
) -> ConfidenceInterval:
    if not values:
        return ConfidenceInterval(0.0, 0.0, 0.0, 0.95)
    safe_block = max(1, min(len(values), int(block_size)))
    blocks = [values[index : index + safe_block] for index in range(0, len(values), safe_block)]
    generator = random.Random(seed)
    means: list[float] = []
    for _ in range(max(100, int(iterations))):
        sample: list[float] = []
        while len(sample) < len(values):
            sample.extend(generator.choice(blocks))
        sample = sample[: len(values)]
        means.append(sum(sample) / len(sample))
    means.sort()
    lower_index = int(0.025 * (len(means) - 1))
    upper_index = int(0.975 * (len(means) - 1))
    estimate = sum(values) / len(values)
    return ConfidenceInterval(estimate, means[lower_index], means[upper_index], 0.95)


def evaluate_baseline(
    decisions: Iterable[ReplayDecision],
    model,
    *,
    horizon: int = 3,
    maximum: int | None = None,
    engine_name: str,
) -> Mapping[str, float | int]:
    accumulator = EvaluationAccumulator()
    count = 0
    for decision in decisions:
        probabilities = model.predict_proba(decision.context.pivot)
        prediction = prediction_from_probabilities(
            decision.context,
            probabilities,
            horizon=horizon,
            engine=engine_name,
        )
        accumulator.add(prediction, decision.targets[:horizon])
        count += 1
        if maximum is not None and count >= int(maximum):
            break
    return accumulator.to_dict(horizon=horizon)


def comparison_report(
    history: Sequence[int],
    decisions_factory,
    *,
    horizon: int = 3,
    maximum: int | None = 5000,
    training_end: int | None = None,
    calibration_decisions_factory=None,
    rule_runner: RuleReplayRunner | None = None,
) -> dict:
    fit_history = history if training_end is None else history[: max(1, int(training_end))]
    frequency = FrequencyBaseline().fit(fit_history)
    conditional = PivotConditionalBaseline().fit(fit_history)
    uniform = UniformBaseline()
    uniform_metrics = evaluate_baseline(
        decisions_factory(), uniform, horizon=horizon, maximum=maximum, engine_name="uniform"
    )
    frequency_metrics = evaluate_baseline(
        decisions_factory(), frequency, horizon=horizon, maximum=maximum, engine_name="frequency"
    )
    conditional_metrics = evaluate_baseline(
        decisions_factory(), conditional, horizon=horizon, maximum=maximum, engine_name="pivot_conditional"
    )
    scorer = (rule_runner or RuleReplayRunner()).scorer
    calibration_payload = None
    if calibration_decisions_factory is not None:
        calibration_scores: list[dict[int, float]] = []
        calibration_targets: list[int] = []
        for decision in calibration_decisions_factory():
            row = scorer.score_context(decision.context, horizon=horizon)
            calibration_scores.append(
                {candidate.number: candidate.final_score for candidate in row.ranking}
            )
            calibration_targets.append(int(decision.targets[0]))
            if maximum is not None and len(calibration_targets) >= int(maximum):
                break
        calibration = OrbitCalibration().fit(calibration_scores, calibration_targets)
        raw_accumulator = EvaluationAccumulator()
        calibrated_accumulator = EvaluationAccumulator()
        evaluated = 0
        for decision in decisions_factory():
            raw_prediction = scorer.score_context(decision.context, horizon=horizon)
            raw_accumulator.add(raw_prediction, decision.targets[:horizon])
            raw_scores = {
                candidate.number: candidate.final_score for candidate in raw_prediction.ranking
            }
            probabilities, _prediction_set = calibration.calibrate(raw_scores)
            calibrated_prediction = prediction_from_probabilities(
                decision.context,
                probabilities,
                horizon=horizon,
                engine="orbital_rule_calibrated_v1",
            )
            calibrated_accumulator.add(calibrated_prediction, decision.targets[:horizon])
            evaluated += 1
            if maximum is not None and evaluated >= int(maximum):
                break
        raw_rule_metrics = raw_accumulator.to_dict(horizon=horizon)
        calibrated_rule_metrics = calibrated_accumulator.to_dict(horizon=horizon)
        calibration_payload = calibration.to_dict()
    else:
        rule_result = (rule_runner or RuleReplayRunner()).run(
            decisions_factory(), horizon=horizon, max_decisions=maximum, keep_predictions=0
        )
        raw_rule_metrics = dict(rule_result.metrics)
        calibrated_rule_metrics = dict(rule_result.metrics)
    return {
        "horizon": horizon,
        "maximum_decisions": maximum,
        "baseline_training_records": len(fit_history),
        "uniform": dict(uniform_metrics),
        "frequency": dict(frequency_metrics),
        "pivot_conditional": dict(conditional_metrics),
        "orbital_rule_raw": dict(raw_rule_metrics),
        "orbital_rule_calibrated": dict(calibrated_rule_metrics),
        "rule_calibration": calibration_payload,
        "deltas_vs_uniform": {
            "top9_at_1": float(calibrated_rule_metrics["top9_at_1"]) - float(uniform_metrics["top9_at_1"]),
            "top12_at_1": float(calibrated_rule_metrics["top12_at_1"]) - float(uniform_metrics["top12_at_1"]),
            "log_loss": float(calibrated_rule_metrics["multiclass_log_loss"]) - float(uniform_metrics["multiclass_log_loss"]),
        },
    }
