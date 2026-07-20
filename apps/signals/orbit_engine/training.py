"""Treino temporal, calibracao e avaliacao do ensemble orbital."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Sequence

from shared.python.roulette.orbit.metrics import EvaluationAccumulator
from shared.python.roulette.orbit.orbit_builder import OrbitBuilder
from shared.python.roulette.orbit.scoring import OrbitalRuleScorer

from .artifacts import atomic_write_json
from .calibration import OrbitCalibration
from .dataset import ChronologicalSplit, iter_replay_decisions
from .ensemble import combine_probability_models
from .ranker import OnlineCandidateRanker
from .replay import prediction_from_probabilities
from .snapshot import SpinRecord
from .survival import CandidateSurvivalModel


def _decisions(
    records: Sequence[SpinRecord],
    builder: OrbitBuilder,
    *,
    horizon: int,
    warmup: int,
    start: int,
    end: int | None,
):
    return iter_replay_decisions(
        records,
        builder=builder,
        horizon=horizon,
        warmup=warmup,
        anchor_start=start,
        anchor_end=end,
    )


def train_evaluate_models(
    records: Sequence[SpinRecord],
    *,
    builder: OrbitBuilder,
    split: ChronologicalSplit,
    artifact_dir: Path,
    horizon: int = 3,
    warmup: int = 300,
    max_train: int | None = 20_000,
    max_validation: int | None = 5_000,
    max_test: int | None = 5_000,
) -> dict[str, Any]:
    """Treina sem embaralhar e sem permitir alvos cruzarem os blocos temporais."""

    safe_horizon = max(1, int(horizon))
    training_end = max(int(warmup) + 1, split.train_end - safe_horizon)
    validation_end = max(split.train_end + 1, split.validation_end - safe_horizon)

    ranker = OnlineCandidateRanker().fit(
        _decisions(
            records,
            builder,
            horizon=safe_horizon,
            warmup=warmup,
            start=warmup,
            end=training_end,
        ),
        max_decisions=max_train,
    )
    survival = CandidateSurvivalModel().fit(
        _decisions(
            records,
            builder,
            horizon=safe_horizon,
            warmup=warmup,
            start=warmup,
            end=training_end,
        ),
        horizon=safe_horizon,
        max_decisions=max_train,
    )

    calibration_scores: list[dict[int, float]] = []
    calibration_targets: list[int] = []
    for decision in _decisions(
        records,
        builder,
        horizon=safe_horizon,
        warmup=warmup,
        start=split.train_end,
        end=validation_end,
    ):
        calibration_scores.append(dict(ranker.predict(decision.context).scores))
        calibration_targets.append(int(decision.targets[0]))
        if max_validation is not None and len(calibration_targets) >= int(max_validation):
            break
    calibration = OrbitCalibration().fit(calibration_scores, calibration_targets)

    rule = OrbitalRuleScorer()
    accumulator = EvaluationAccumulator()
    conformal_hits = 0
    conformal_sizes: list[int] = []
    evaluated = 0
    for decision in _decisions(
        records,
        builder,
        horizon=safe_horizon,
        warmup=warmup,
        start=split.validation_end,
        end=None,
    ):
        rule_prediction = rule.score_context(decision.context, horizon=safe_horizon)
        rule_probabilities = {
            row.number: row.probability for row in rule_prediction.ranking
        }
        ranker_prediction = ranker.predict(decision.context)
        calibrated_ranker, conformal_set = calibration.calibrate(ranker_prediction.scores)
        survival_prediction = survival.predict(decision.context)
        ensemble = combine_probability_models(
            [rule_probabilities, calibrated_ranker, survival_prediction.appearance_probability],
            weights=[0.35, 0.45, 0.20],
        )
        prediction = prediction_from_probabilities(
            decision.context,
            ensemble.probabilities,
            horizon=safe_horizon,
            engine="orbital_ensemble_v1",
            excluded=ensemble.exclusions,
        )
        accumulator.add(prediction, decision.targets[:safe_horizon])
        conformal_hits += int(int(decision.targets[0]) in conformal_set)
        conformal_sizes.append(len(conformal_set))
        evaluated += 1
        if max_test is not None and evaluated >= int(max_test):
            break

    artifact_dir = artifact_dir.resolve()
    ranker_path = artifact_dir / "ranker.joblib"
    survival_path = artifact_dir / "survival.joblib"
    calibration_path = artifact_dir / "calibration.json"
    ranker.save(ranker_path)
    survival.save(survival_path)
    atomic_write_json(calibration_path, calibration.to_dict())

    metrics = accumulator.to_dict(horizon=safe_horizon)
    promotion_checks = {
        "top9_margin_at_least_1pp": float(metrics["top9_at_1"]) >= (9 / 37.0) + 0.01,
        "log_loss_not_worse_than_uniform": float(metrics["multiclass_log_loss"])
        <= math.log(37),
        "exclusion_leak_below_80pct_random": int(metrics["exclusion_claims"]) >= 1000
        and float(metrics["exclusion_leak_rate"]) < (0.8 / 37.0),
    }
    report = {
        "model": "orbital_ensemble_v1",
        "chronology": "train_then_validation_then_test",
        "split": {
            "train_end": split.train_end,
            "validation_end": split.validation_end,
            "total": split.total,
        },
        "horizon": safe_horizon,
        "training_decisions": ranker.training_decisions,
        "calibration": calibration.to_dict(),
        "test_metrics": metrics,
        "conformal_coverage": conformal_hits / max(1, evaluated),
        "conformal_average_set_size": sum(conformal_sizes) / max(1, len(conformal_sizes)),
        "artifacts": {
            "ranker": str(ranker_path),
            "survival": str(survival_path),
            "calibration": str(calibration_path),
        },
        "promotion_gate": {
            "eligible": all(promotion_checks.values()),
            "checks": promotion_checks,
            "default_action": "remain_in_shadow_mode",
        },
    }
    atomic_write_json(artifact_dir / "training-report.json", report)
    return report
