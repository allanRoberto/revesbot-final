"""Online shadow meta-ranking for Jev's 0-36 Choice distribution.

The champion remains the original Jev ranking.  A bounded residual softmax model
learns global evidence weights after each resolved next-spin outcome and produces
a challenger ranking without another paid inference.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from api.services.jev_history_service import ROULETTE_SLUG
from api.services.jev_statistics import relation_labels


ADAPTIVE_SCHEMA_VERSION = "jev-adaptive-softmax-v1"
FEATURE_NAMES = (
    "walk_forward_probability_delta",
    "walk_forward_reliability",
    "relation_strength",
    "relation_support",
    "relation_lift",
    "recent_frequency",
    "gap_percentile",
    "mirror",
    "wheel_neighbor_distance_1",
    "wheel_neighbor_distance_2",
    "digit_sum_substitution",
    "same_terminal",
    "same_terminal_group",
    "exact_sequence_pressure",
    "relational_sequence_pressure",
)
MAXIMUM_SAMPLES = 1_000
RECENT_EVALUATION_WINDOW = 200
MINIMUM_SHADOW_SAMPLES = 30
MINIMUM_PROMOTION_SAMPLES = 50
MAXIMUM_LOGIT_CORRECTION = 1.25
BASE_LEARNING_RATE = 0.055
L2_REGULARIZATION = 0.003
WEIGHT_LIMIT = 2.0
_EPSILON = 1e-12


class JevAdaptiveRankingError(ValueError):
    pass


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return min(maximum, max(minimum, value))


def _rounded(value: float | None) -> float | None:
    return round(value, 6) if value is not None else None


def _probability_rows(probabilities: Mapping[str, float]) -> dict[int, float]:
    if set(probabilities) != {str(number) for number in range(37)}:
        raise JevAdaptiveRankingError("a Choice deve conter exatamente os números 0 a 36")
    rows: dict[int, float] = {}
    for number in range(37):
        raw = probabilities[str(number)]
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise JevAdaptiveRankingError("a Choice contém probabilidade inválida")
        value = float(raw)
        if not math.isfinite(value) or value < 0:
            raise JevAdaptiveRankingError("a Choice contém probabilidade inválida")
        rows[number] = value
    total = sum(rows.values())
    if total <= 0:
        raise JevAdaptiveRankingError("a Choice não possui massa positiva")
    return {number: value / total for number, value in rows.items()}


def _table_by_number(state: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    evidence = state.get("evidence_tables")
    if not isinstance(evidence, Mapping):
        raise JevAdaptiveRankingError("evidence_tables ausente")
    columns = evidence.get("number_profile_columns")
    rows = evidence.get("number_profiles")
    if not isinstance(columns, list) or not isinstance(rows, list):
        raise JevAdaptiveRankingError("number_profiles inválido")
    result = {}
    for row in rows:
        if not isinstance(row, list) or len(row) != len(columns):
            continue
        mapped = dict(zip(columns, row))
        number = mapped.get("number")
        if isinstance(number, int) and not isinstance(number, bool):
            result[number] = mapped
    if set(result) != set(range(37)):
        raise JevAdaptiveRankingError("number_profiles não cobre 0 a 36")
    return result


def _sequence_pressure(state: Mapping[str, Any]) -> tuple[dict[int, float], dict[int, float]]:
    relational = state.get("relational_context")
    evidence = relational.get("sequence_evidence") if isinstance(relational, Mapping) else None
    if not isinstance(evidence, Mapping):
        return ({number: 0.0 for number in range(37)}, {number: 0.0 for number in range(37)})
    columns = evidence.get("episode_columns")
    if not isinstance(columns, list):
        return ({number: 0.0 for number in range(37)}, {number: 0.0 for number in range(37)})

    def pressure(rows: Any, *, relational_rows: bool) -> dict[int, float]:
        values = {number: 0.0 for number in range(37)}
        if not isinstance(rows, list):
            return values
        for row in rows:
            if not isinstance(row, list) or len(row) != len(columns):
                continue
            episode = dict(zip(columns, row))
            after = episode.get("after_up_to_5")
            if not isinstance(after, list):
                continue
            similarity = float(episode.get("mean_similarity") or 0.0) if relational_rows else 1.0
            for offset, number in enumerate(after[:5], start=1):
                if isinstance(number, int) and not isinstance(number, bool) and 0 <= number <= 36:
                    values[number] += similarity / offset
        maximum = max(values.values(), default=0.0)
        return {
            number: (value / maximum if maximum > 0 else 0.0)
            for number, value in values.items()
        }

    return (
        pressure(evidence.get("exact_episodes"), relational_rows=False),
        pressure(evidence.get("relational_episodes"), relational_rows=True),
    )


def extract_adaptive_snapshot(
    ranking_payload: Mapping[str, Any], probabilities: Mapping[str, float]
) -> dict[str, Any]:
    """Create the pre-outcome feature matrix used by champion and challenger."""
    state = ranking_payload.get("state")
    catalog = ranking_payload.get("catalog")
    walk_forward = ranking_payload.get("walk_forward")
    if not all(isinstance(item, Mapping) for item in (state, catalog, walk_forward)):
        raise JevAdaptiveRankingError("o payload do ranking está incompleto")
    normalized = _probability_rows(probabilities)
    profiles = _table_by_number(state)
    relations = {
        int(item["target_number"]): item
        for item in catalog.get("relations", [])
        if isinstance(item, Mapping) and isinstance(item.get("target_number"), int)
    }
    validation = walk_forward.get("numbers")
    if not isinstance(validation, Mapping):
        raise JevAdaptiveRankingError("a validação walk-forward está incompleta")
    exact_pressure, relational_pressure = _sequence_pressure(state)
    latest = state.get("history_context", {}).get("latest_observed_number")
    if not isinstance(latest, int) or not 0 <= latest <= 36:
        raise JevAdaptiveRankingError("o último número observado é inválido")

    vectors: dict[str, dict[str, float]] = {}
    one_spin_baseline = 1 / 37
    for number in range(37):
        number_validation = validation.get(number, validation.get(str(number)))
        horizon = number_validation.get("horizon_1") if isinstance(number_validation, Mapping) else None
        combined = horizon.get("combined") if isinstance(horizon, Mapping) else None
        relation = relations.get(number, {})
        profile = profiles[number]
        deterministic = float(combined.get("calibrated_probability", one_spin_baseline)) if isinstance(combined, Mapping) else one_spin_baseline
        reliability = float(combined.get("reliability", 0.0)) if isinstance(combined, Mapping) else 0.0
        support = max(0, int(relation.get("support", 0)))
        lift = float(relation.get("lift_vs_baseline", 1.0))
        strength = float(relation.get("deterministic_strength", 0.0))
        recent_rate = float(profile.get("last_30_rate") or 0.0)
        gap_percentile = float(profile.get("gap_historical_percentile") or 0.0)
        labels = set(relation_labels(latest, number))
        values = {
            "walk_forward_probability_delta": _clamp(
                (deterministic - one_spin_baseline) / (3 * one_spin_baseline), -1.0, 1.0
            ),
            "walk_forward_reliability": _clamp(reliability),
            "relation_strength": _clamp(strength),
            "relation_support": _clamp(math.log1p(support) / math.log(1_001)),
            "relation_lift": _clamp((lift - 1.0) / 2.0, -1.0, 1.0),
            "recent_frequency": _clamp((recent_rate * 37 - 1.0) / 3.0, -1.0, 1.0),
            "gap_percentile": _clamp(gap_percentile),
            "mirror": float("mirror" in labels),
            "wheel_neighbor_distance_1": float("wheel_neighbor_distance_1" in labels),
            "wheel_neighbor_distance_2": float("wheel_neighbor_distance_2" in labels),
            "digit_sum_substitution": float("digit_sum_substitution" in labels),
            "same_terminal": float("same_terminal" in labels),
            "same_terminal_group": float("same_terminal_group" in labels),
            "exact_sequence_pressure": exact_pressure[number],
            "relational_sequence_pressure": relational_pressure[number],
        }
        vectors[str(number)] = {name: _rounded(values[name]) for name in FEATURE_NAMES}
    context = state.get("history_context", {})
    return {
        "schema_version": ADAPTIVE_SCHEMA_VERSION,
        "context_sha256": context.get("full_history_sha256"),
        "roulette_slug": state.get("task", {}).get("roulette_slug", ROULETTE_SLUG),
        "latest_number": latest,
        "jev_probabilities": {str(number): _rounded(normalized[number]) for number in range(37)},
        "features": vectors,
    }


def new_adaptive_state() -> dict[str, Any]:
    return {
        "schema_version": ADAPTIVE_SCHEMA_VERSION,
        "sample_count": 0,
        "weights": {name: 0.0 for name in FEATURE_NAMES},
    }


def _validated_state(state: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(state, Mapping) or state.get("schema_version") != ADAPTIVE_SCHEMA_VERSION:
        return new_adaptive_state()
    weights = state.get("weights")
    if not isinstance(weights, Mapping):
        return new_adaptive_state()
    try:
        normalized = {name: float(weights[name]) for name in FEATURE_NAMES}
    except (KeyError, TypeError, ValueError):
        return new_adaptive_state()
    if not all(math.isfinite(value) for value in normalized.values()):
        return new_adaptive_state()
    return {
        "schema_version": ADAPTIVE_SCHEMA_VERSION,
        "sample_count": max(0, int(state.get("sample_count", 0))),
        "weights": normalized,
    }


def predict_adaptive_ranking(
    snapshot: Mapping[str, Any], state: Mapping[str, Any] | None, *, top_k: int
) -> dict[str, Any]:
    if snapshot.get("schema_version") != ADAPTIVE_SCHEMA_VERSION:
        raise JevAdaptiveRankingError("snapshot adaptativo incompatível")
    if not 1 <= top_k <= 36:
        raise JevAdaptiveRankingError("top_k deve estar entre 1 e 36")
    model = _validated_state(state)
    weights = model["weights"]
    jev = _probability_rows(snapshot.get("jev_probabilities", {}))
    features = snapshot.get("features")
    if not isinstance(features, Mapping):
        raise JevAdaptiveRankingError("matriz de características ausente")
    logits = {}
    corrections = {}
    for number in range(37):
        vector = features.get(str(number))
        if not isinstance(vector, Mapping):
            raise JevAdaptiveRankingError("matriz adaptativa incompleta")
        correction = sum(float(vector[name]) * weights[name] for name in FEATURE_NAMES)
        correction = _clamp(correction, -MAXIMUM_LOGIT_CORRECTION, MAXIMUM_LOGIT_CORRECTION)
        corrections[number] = correction
        logits[number] = math.log(max(_EPSILON, jev[number])) + correction
    maximum = max(logits.values())
    exponentials = {number: math.exp(value - maximum) for number, value in logits.items()}
    denominator = sum(exponentials.values())
    adaptive = {number: exponentials[number] / denominator for number in range(37)}

    def ranking(probability_map: Mapping[int, float]) -> list[dict[str, Any]]:
        ordered = sorted(probability_map, key=lambda number: (-probability_map[number], number))
        return [
            {
                "position": position,
                "number": number,
                "probability": _rounded(probability_map[number]),
                "jev_probability": _rounded(jev[number]),
                "correction": _rounded(corrections[number]),
            }
            for position, number in enumerate(ordered, start=1)
        ]

    jev_ranking = ranking(jev)
    adaptive_ranking = ranking(adaptive)
    return {
        "schema_version": ADAPTIVE_SCHEMA_VERSION,
        "sample_count_before": model["sample_count"],
        "top_k": top_k,
        "jev_ranking": jev_ranking,
        "adaptive_ranking": adaptive_ranking,
        "jev_selected_numbers": [row["number"] for row in jev_ranking[:top_k]],
        "adaptive_selected_numbers": [row["number"] for row in adaptive_ranking[:top_k]],
        "adaptive_probabilities": {
            str(number): _rounded(adaptive[number]) for number in range(37)
        },
    }


def _multiclass_metrics(probabilities: Mapping[str, float], actual: int) -> tuple[float, float]:
    brier = sum(
        (float(probabilities[str(number)]) - float(number == actual)) ** 2
        for number in range(37)
    )
    log_loss = -math.log(max(_EPSILON, float(probabilities[str(actual)])))
    return brier, log_loss


def _first_hit(selected: Sequence[int], future: Sequence[int]) -> int | None:
    selected_set = set(selected)
    return next(
        (attempt for attempt, number in enumerate(future, start=1) if number in selected_set),
        None,
    )


def _rank_of(ranking: Sequence[Mapping[str, Any]], actual: int) -> int:
    return next(int(row["position"]) for row in ranking if int(row["number"]) == actual)


def update_adaptive_state(
    state: Mapping[str, Any] | None,
    snapshot: Mapping[str, Any],
    adaptive_probabilities: Mapping[str, float],
    *,
    actual_number: int,
) -> dict[str, Any]:
    model = _validated_state(state)
    features = snapshot.get("features")
    if not isinstance(features, Mapping):
        raise JevAdaptiveRankingError("matriz adaptativa ausente")
    count = model["sample_count"]
    learning_rate = BASE_LEARNING_RATE / math.sqrt(1 + count / 50)
    weights = dict(model["weights"])
    gradients = {name: 0.0 for name in FEATURE_NAMES}
    for number in range(37):
        vector = features.get(str(number))
        if not isinstance(vector, Mapping):
            raise JevAdaptiveRankingError("matriz adaptativa incompleta")
        error = float(adaptive_probabilities[str(number)]) - float(number == actual_number)
        for name in FEATURE_NAMES:
            gradients[name] += error * float(vector[name])
    for name in FEATURE_NAMES:
        updated = weights[name] * (1 - learning_rate * L2_REGULARIZATION)
        updated -= learning_rate * gradients[name]
        weights[name] = _clamp(updated, -WEIGHT_LIMIT, WEIGHT_LIMIT)
    return {
        "schema_version": ADAPTIVE_SCHEMA_VERSION,
        "sample_count": count + 1,
        "weights": weights,
    }


def build_adaptive_sample(
    snapshot: Mapping[str, Any], *, model: str, actual_number: int
) -> dict[str, Any]:
    return {
        "schema_version": ADAPTIVE_SCHEMA_VERSION,
        "context_sha256": snapshot.get("context_sha256"),
        "roulette_slug": snapshot.get("roulette_slug", ROULETTE_SLUG),
        "model": model,
        "jev_probabilities": dict(snapshot["jev_probabilities"]),
        "features": snapshot["features"],
        "actual_number": actual_number,
    }


def _empty_metrics() -> dict[str, Any]:
    return {
        "signals": 0,
        "hits": 0,
        "misses": 0,
        "accuracy": None,
        "brier_sum": 0.0,
        "brier": None,
        "log_loss_sum": 0.0,
        "log_loss": None,
        "winner_rank_sum": 0,
        "average_winner_rank": None,
    }


def _update_metrics(
    metrics: dict[str, Any], *, hit: bool, brier: float, log_loss: float, winner_rank: int
) -> None:
    metrics["signals"] += 1
    metrics["hits" if hit else "misses"] += 1
    metrics["accuracy"] = metrics["hits"] / metrics["signals"]
    metrics["brier_sum"] += brier
    metrics["brier"] = metrics["brier_sum"] / metrics["signals"]
    metrics["log_loss_sum"] += log_loss
    metrics["log_loss"] = metrics["log_loss_sum"] / metrics["signals"]
    metrics["winner_rank_sum"] += winner_rank
    metrics["average_winner_rank"] = metrics["winner_rank_sum"] / metrics["signals"]


def _promotion_status(summary: Mapping[str, Any], recent: Sequence[Mapping[str, Any]]) -> tuple[str, str]:
    count = int(summary.get("sample_count", 0))
    if count < MINIMUM_SHADOW_SAMPLES:
        return "warming_up", f"Aquecendo: {count}/{MINIMUM_SHADOW_SAMPLES} sinais resolvidos."
    if count < MINIMUM_PROMOTION_SAMPLES:
        return "shadow", f"Modo sombra: {count}/{MINIMUM_PROMOTION_SAMPLES} sinais para avaliar promoção."
    window = recent[-RECENT_EVALUATION_WINDOW:]
    if not window:
        return "shadow", "Ainda não há avaliações recentes suficientes."
    jev_brier = sum(float(row["jev_brier"]) for row in window) / len(window)
    adaptive_brier = sum(float(row["adaptive_brier"]) for row in window) / len(window)
    jev_log = sum(float(row["jev_log_loss"]) for row in window) / len(window)
    adaptive_log = sum(float(row["adaptive_log_loss"]) for row in window) / len(window)
    jev_hits = sum(bool(row["jev_hit"]) for row in window)
    adaptive_hits = sum(bool(row["adaptive_hit"]) for row in window)
    if adaptive_brier < jev_brier and adaptive_log < jev_log and adaptive_hits >= jev_hits:
        return "promotion_eligible", "O desafiante superou Brier e log loss sem reduzir o top-N na janela recente."
    if adaptive_brier > jev_brier and adaptive_log > jev_log and adaptive_hits < jev_hits:
        return "degraded", "O desafiante está pior que o JEV nas três métricas recentes."
    return "shadow", "O resultado ainda é misto; o JEV permanece como campeão."


def record_adaptive_outcome(
    job: dict[str, Any],
    *,
    snapshot: Mapping[str, Any],
    prediction: Mapping[str, Any],
    future_numbers: Sequence[int],
    model: str,
) -> dict[str, Any]:
    if not future_numbers:
        raise JevAdaptiveRankingError("o resultado futuro do próximo giro está ausente")
    actual = int(future_numbers[0])
    top_k = int(prediction["top_k"])
    jev_probabilities = snapshot["jev_probabilities"]
    adaptive_probabilities = prediction["adaptive_probabilities"]
    jev_brier, jev_log = _multiclass_metrics(jev_probabilities, actual)
    adaptive_brier, adaptive_log = _multiclass_metrics(adaptive_probabilities, actual)
    jev_hit_attempt = _first_hit(prediction["jev_selected_numbers"], future_numbers)
    adaptive_hit_attempt = _first_hit(prediction["adaptive_selected_numbers"], future_numbers)
    evaluation = {
        "actual_next_number": actual,
        "jev_hit": jev_hit_attempt is not None,
        "jev_first_hit_attempt": jev_hit_attempt,
        "adaptive_hit": adaptive_hit_attempt is not None,
        "adaptive_first_hit_attempt": adaptive_hit_attempt,
        "jev_brier": _rounded(jev_brier),
        "adaptive_brier": _rounded(adaptive_brier),
        "jev_log_loss": _rounded(jev_log),
        "adaptive_log_loss": _rounded(adaptive_log),
        "jev_winner_rank": _rank_of(prediction["jev_ranking"], actual),
        "adaptive_winner_rank": _rank_of(prediction["adaptive_ranking"], actual),
    }
    summary = job.setdefault(
        "adaptive",
        {
            "schema_version": ADAPTIVE_SCHEMA_VERSION,
            "sample_count": 0,
            "status": "warming_up",
            "reason": f"Aquecendo: 0/{MINIMUM_SHADOW_SAMPLES} sinais resolvidos.",
            "jev": _empty_metrics(),
            "challenger": _empty_metrics(),
            "latest_prediction": None,
        },
    )
    _update_metrics(
        summary["jev"], hit=evaluation["jev_hit"], brier=jev_brier,
        log_loss=jev_log, winner_rank=evaluation["jev_winner_rank"],
    )
    _update_metrics(
        summary["challenger"], hit=evaluation["adaptive_hit"], brier=adaptive_brier,
        log_loss=adaptive_log, winner_rank=evaluation["adaptive_winner_rank"],
    )
    current_state = job.get("adaptive_state")
    job["adaptive_state"] = update_adaptive_state(
        current_state, snapshot, adaptive_probabilities, actual_number=actual
    )
    summary["sample_count"] = int(job["adaptive_state"]["sample_count"])
    summary["latest_prediction"] = {
        "sample_count_before": prediction["sample_count_before"],
        "top_k": top_k,
        "jev_selected_numbers": list(prediction["jev_selected_numbers"]),
        "adaptive_selected_numbers": list(prediction["adaptive_selected_numbers"]),
        "evaluation": evaluation,
    }
    recent = job.setdefault("adaptive_recent_evaluations", [])
    recent.append(evaluation)
    del recent[:-RECENT_EVALUATION_WINDOW]
    summary["status"], summary["reason"] = _promotion_status(summary, recent)
    summary["comparison"] = {
        "brier_improvement": _rounded(summary["jev"]["brier"] - summary["challenger"]["brier"]),
        "log_loss_improvement": _rounded(summary["jev"]["log_loss"] - summary["challenger"]["log_loss"]),
        "accuracy_difference": _rounded(summary["challenger"]["accuracy"] - summary["jev"]["accuracy"]),
    }
    return {
        "prediction": summary["latest_prediction"],
        "sample": build_adaptive_sample(snapshot, model=model, actual_number=actual),
    }


def load_adaptive_samples(
    results_dir: str, *, model: str, roulette_slug: str = ROULETTE_SLUG
) -> list[dict[str, Any]]:
    directory = Path(results_dir).expanduser() / "backtests"
    if not directory.is_dir():
        return []
    samples = []
    seen = set()
    paths = sorted(directory.glob("*.steps.jsonl"), key=lambda path: path.stat().st_mtime)
    for path in paths:
        try:
            handle = path.open(encoding="utf-8")
        except OSError:
            continue
        with handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                sample = record.get("adaptive_sample") if isinstance(record, dict) else None
                if not isinstance(sample, dict) or sample.get("schema_version") != ADAPTIVE_SCHEMA_VERSION:
                    continue
                if sample.get("roulette_slug", ROULETTE_SLUG) != roulette_slug:
                    continue
                if sample.get("model") != model:
                    continue
                key = sample.get("context_sha256")
                if isinstance(key, str) and key:
                    if key in seen:
                        continue
                    seen.add(key)
                samples.append(sample)
    return samples[-MAXIMUM_SAMPLES:]


def replay_adaptive_samples(
    samples: Sequence[Mapping[str, Any]], *, top_k: int = 6
) -> tuple[dict[str, Any], dict[str, Any]]:
    state = new_adaptive_state()
    totals = {
        "sample_count": 0,
        "jev_brier_sum": 0.0,
        "adaptive_brier_sum": 0.0,
        "jev_log_loss_sum": 0.0,
        "adaptive_log_loss_sum": 0.0,
        "jev_top_k_hits": 0,
        "adaptive_top_k_hits": 0,
    }
    for sample in samples[-MAXIMUM_SAMPLES:]:
        try:
            snapshot = {
                "schema_version": ADAPTIVE_SCHEMA_VERSION,
                "context_sha256": sample.get("context_sha256"),
                "jev_probabilities": sample["jev_probabilities"],
                "features": sample["features"],
            }
            actual = int(sample["actual_number"])
            prediction = predict_adaptive_ranking(snapshot, state, top_k=top_k)
            jev_brier, jev_log = _multiclass_metrics(snapshot["jev_probabilities"], actual)
            adaptive_brier, adaptive_log = _multiclass_metrics(prediction["adaptive_probabilities"], actual)
            state = update_adaptive_state(
                state, snapshot, prediction["adaptive_probabilities"], actual_number=actual
            )
        except (KeyError, TypeError, ValueError, JevAdaptiveRankingError):
            continue
        totals["sample_count"] += 1
        totals["jev_brier_sum"] += jev_brier
        totals["adaptive_brier_sum"] += adaptive_brier
        totals["jev_log_loss_sum"] += jev_log
        totals["adaptive_log_loss_sum"] += adaptive_log
        totals["jev_top_k_hits"] += int(actual in prediction["jev_selected_numbers"])
        totals["adaptive_top_k_hits"] += int(actual in prediction["adaptive_selected_numbers"])
    count = totals["sample_count"]
    summary = {
        "sample_count": count,
        "jev_brier": _rounded(totals["jev_brier_sum"] / count) if count else None,
        "adaptive_brier": _rounded(totals["adaptive_brier_sum"] / count) if count else None,
        "jev_log_loss": _rounded(totals["jev_log_loss_sum"] / count) if count else None,
        "adaptive_log_loss": _rounded(totals["adaptive_log_loss_sum"] / count) if count else None,
        "jev_top_k_accuracy": _rounded(totals["jev_top_k_hits"] / count) if count else None,
        "adaptive_top_k_accuracy": _rounded(totals["adaptive_top_k_hits"] / count) if count else None,
    }
    return state, summary


def build_live_adaptive_report(
    prediction: Mapping[str, Any], training: Mapping[str, Any]
) -> dict[str, Any]:
    count = int(training.get("sample_count", 0))
    if count < MINIMUM_SHADOW_SAMPLES:
        status = "warming_up"
        reason = f"Aquecendo: {count}/{MINIMUM_SHADOW_SAMPLES} sinais resolvidos."
    elif count < MINIMUM_PROMOTION_SAMPLES:
        status = "shadow"
        reason = f"Modo sombra: {count}/{MINIMUM_PROMOTION_SAMPLES} sinais para avaliar promoção."
    else:
        jev_brier = training.get("jev_brier")
        adaptive_brier = training.get("adaptive_brier")
        jev_log = training.get("jev_log_loss")
        adaptive_log = training.get("adaptive_log_loss")
        jev_accuracy = training.get("jev_top_k_accuracy")
        adaptive_accuracy = training.get("adaptive_top_k_accuracy")
        if (
            all(isinstance(value, (int, float)) for value in (
                jev_brier, adaptive_brier, jev_log, adaptive_log,
                jev_accuracy, adaptive_accuracy,
            ))
            and adaptive_brier < jev_brier
            and adaptive_log < jev_log
            and adaptive_accuracy >= jev_accuracy
        ):
            status = "promotion_eligible"
            reason = "O desafiante melhorou Brier e log loss sem reduzir o acerto top-N no replay cronológico."
        elif (
            all(isinstance(value, (int, float)) for value in (
                jev_brier, adaptive_brier, jev_log, adaptive_log,
                jev_accuracy, adaptive_accuracy,
            ))
            and adaptive_brier > jev_brier
            and adaptive_log > jev_log
            and adaptive_accuracy < jev_accuracy
        ):
            status = "degraded"
            reason = "O desafiante perdeu para o JEV nas três métricas do replay cronológico."
        else:
            status = "shadow"
            reason = "As métricas ainda são mistas; o JEV permanece como campeão."
    jev_selected = list(prediction["jev_selected_numbers"])
    adaptive_selected = list(prediction["adaptive_selected_numbers"])
    jev_set = set(jev_selected)
    adaptive_set = set(adaptive_selected)
    return {
        "schema_version": ADAPTIVE_SCHEMA_VERSION,
        "status": status,
        "reason": reason,
        "sample_count": count,
        "top_k": int(prediction["top_k"]),
        "jev_selected_numbers": jev_selected,
        "adaptive_selected_numbers": adaptive_selected,
        "maintained_numbers": [number for number in adaptive_selected if number in jev_set],
        "added_numbers": [number for number in adaptive_selected if number not in jev_set],
        "removed_numbers": [number for number in jev_selected if number not in adaptive_set],
        "adaptive_ranking": list(prediction["adaptive_ranking"]),
        "training_metrics": dict(training),
    }
