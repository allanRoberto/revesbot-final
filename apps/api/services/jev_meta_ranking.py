"""Leakage-safe walk-forward evidence and conservative Jev meta-ranking."""
from __future__ import annotations

import math
from collections import deque
from typing import Any, Mapping, Sequence


ROULETTE_NUMBERS = tuple(range(37))
WALK_FORWARD_VERSION = "source_conditioned_v1"
WALK_FORWARD_MIN_TRAINING_SUPPORT = 12
WALK_FORWARD_MAX_SAMPLES = 300
WALK_FORWARD_RECENT_SAMPLES = 50
CALIBRATION_PRIOR_SAMPLES = 37.0
FREQUENCY_WINDOW = 300


def _baseline(horizon: int) -> float:
    return 1 - (36 / 37) ** horizon


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return min(maximum, max(minimum, value))


def _rounded(value: float | None) -> float | None:
    return round(value, 6) if value is not None else None


def _smoothed_rate(hits: int, support: int, baseline: float) -> float:
    return (hits + baseline * CALIBRATION_PRIOR_SAMPLES) / (
        support + CALIBRATION_PRIOR_SAMPLES
    )


def _empty_samples() -> list[deque[tuple[float, int]]]:
    return [deque(maxlen=WALK_FORWARD_MAX_SAMPLES) for _ in ROULETTE_NUMBERS]


def _relation_samples(
    history: Sequence[int],
    *,
    source_number: int,
    horizon: int,
) -> tuple[list[deque[tuple[float, int]]], list[float], int]:
    """Replay source-conditioned estimates using only outcomes known at each anchor."""
    baseline = _baseline(horizon)
    samples = _empty_samples()
    hits = [0] * len(ROULETTE_NUMBERS)
    training_support = 0
    evaluated = 0
    for index, value in enumerate(history):
        completed_anchor = index - horizon
        if completed_anchor >= 0 and history[completed_anchor] == source_number:
            training_support += 1
            for target in set(history[completed_anchor + 1 : index + 1]):
                hits[target] += 1

        if value != source_number or index + horizon >= len(history):
            continue
        if training_support < WALK_FORWARD_MIN_TRAINING_SUPPORT:
            continue
        future = set(history[index + 1 : index + 1 + horizon])
        for target in ROULETTE_NUMBERS:
            prediction = _smoothed_rate(hits[target], training_support, baseline)
            samples[target].append((prediction, int(target in future)))
        evaluated += 1

    current_predictions = [
        _smoothed_rate(hits[target], training_support, baseline)
        for target in ROULETTE_NUMBERS
    ]
    return samples, current_predictions, evaluated


def _pair_samples(
    history: Sequence[int],
    *,
    previous_number: int | None,
    source_number: int,
    horizon: int,
) -> tuple[list[deque[tuple[float, int]]], list[float], int]:
    baseline = _baseline(horizon)
    samples = _empty_samples()
    hits = [0] * len(ROULETTE_NUMBERS)
    training_support = 0
    evaluated = 0
    if previous_number is None:
        return samples, [baseline] * len(ROULETTE_NUMBERS), evaluated

    for index, value in enumerate(history):
        completed_anchor = index - horizon
        if (
            completed_anchor >= 1
            and history[completed_anchor - 1] == previous_number
            and history[completed_anchor] == source_number
        ):
            training_support += 1
            for target in set(history[completed_anchor + 1 : index + 1]):
                hits[target] += 1

        if (
            index < 1
            or history[index - 1] != previous_number
            or value != source_number
            or index + horizon >= len(history)
            or training_support < WALK_FORWARD_MIN_TRAINING_SUPPORT
        ):
            continue
        future = set(history[index + 1 : index + 1 + horizon])
        for target in ROULETTE_NUMBERS:
            prediction = _smoothed_rate(hits[target], training_support, baseline)
            samples[target].append((prediction, int(target in future)))
        evaluated += 1

    current_predictions = [
        _smoothed_rate(hits[target], training_support, baseline)
        for target in ROULETTE_NUMBERS
    ]
    return samples, current_predictions, evaluated


def _frequency_samples(
    history: Sequence[int],
    *,
    source_number: int,
    horizon: int,
) -> tuple[list[deque[tuple[float, int]]], list[float], int]:
    samples = _empty_samples()
    counts = [0] * len(ROULETTE_NUMBERS)
    evaluated = 0
    for index, value in enumerate(history):
        counts[value] += 1
        expired_index = index - FREQUENCY_WINDOW
        if expired_index >= 0:
            counts[history[expired_index]] -= 1
        window_size = min(FREQUENCY_WINDOW, index + 1)
        if (
            value != source_number
            or index + horizon >= len(history)
            or window_size < WALK_FORWARD_MIN_TRAINING_SUPPORT
        ):
            continue
        future = set(history[index + 1 : index + 1 + horizon])
        denominator = window_size + len(ROULETTE_NUMBERS)
        for target in ROULETTE_NUMBERS:
            per_spin = (counts[target] + 1) / denominator
            prediction = 1 - (1 - per_spin) ** horizon
            samples[target].append((prediction, int(target in future)))
        evaluated += 1

    current_window = history[-FREQUENCY_WINDOW:]
    current_counts = [current_window.count(target) for target in ROULETTE_NUMBERS]
    denominator = len(current_window) + len(ROULETTE_NUMBERS)
    current_predictions = [
        1 - (1 - (current_counts[target] + 1) / denominator) ** horizon
        for target in ROULETTE_NUMBERS
    ]
    return samples, current_predictions, evaluated


def _sample_metrics(
    values: Sequence[tuple[float, int]],
    *,
    current_prediction: float,
    baseline: float,
    total_evaluated: int,
) -> dict[str, Any]:
    sample_count = len(values)
    if sample_count == 0:
        return {
            "sample_count": 0,
            "total_evaluated": total_evaluated,
            "mean_prediction": None,
            "observed_rate": None,
            "brier": None,
            "fair_brier": None,
            "brier_improvement": None,
            "calibration_gap": None,
            "recent_brier_delta": None,
            "current_prediction": _rounded(current_prediction),
            "calibrated_probability": _rounded(baseline),
            "reliability": 0.0,
            "status": "insufficient",
        }

    mean_prediction = sum(prediction for prediction, _ in values) / sample_count
    observed_rate = sum(outcome for _, outcome in values) / sample_count
    brier = sum((prediction - outcome) ** 2 for prediction, outcome in values) / sample_count
    fair_brier = sum((baseline - outcome) ** 2 for _, outcome in values) / sample_count
    improvement = (fair_brier - brier) / fair_brier if fair_brier else 0.0
    calibration_gap = abs(mean_prediction - observed_rate)
    recent_values = values[-WALK_FORWARD_RECENT_SAMPLES:]
    recent_brier = sum(
        (prediction - outcome) ** 2 for prediction, outcome in recent_values
    ) / len(recent_values)
    recent_brier_delta = recent_brier - brier
    shrinkage = sample_count / (sample_count + CALIBRATION_PRIOR_SAMPLES)
    calibrated = _clamp(current_prediction + (observed_rate - mean_prediction) * shrinkage)
    sample_factor = min(1.0, sample_count / 100)
    performance_factor = _clamp(0.50 + improvement)
    calibration_factor = _clamp(1 - calibration_gap / 0.75, 0.25, 1.0)
    reliability = sample_factor * performance_factor * calibration_factor

    if sample_count < 30:
        status = "insufficient"
    elif improvement >= 0.02 and calibration_gap <= 0.60 and recent_brier_delta <= 0.02:
        status = "validated"
    elif improvement < -0.10 or recent_brier_delta > 0.05:
        status = "degraded"
    else:
        status = "inconclusive"
    return {
        "sample_count": sample_count,
        "total_evaluated": total_evaluated,
        "mean_prediction": _rounded(mean_prediction),
        "observed_rate": _rounded(observed_rate),
        "brier": _rounded(brier),
        "fair_brier": _rounded(fair_brier),
        "brier_improvement": _rounded(improvement),
        "calibration_gap": _rounded(calibration_gap),
        "recent_brier_delta": _rounded(recent_brier_delta),
        "current_prediction": _rounded(current_prediction),
        "calibrated_probability": _rounded(calibrated),
        "reliability": _rounded(reliability),
        "status": status,
    }


def _combine_models(models: Mapping[str, Mapping[str, Any]], baseline: float) -> dict[str, Any]:
    weighted_probability = 0.0
    total_weight = 0.0
    for model in models.values():
        reliability = float(model["reliability"])
        if reliability <= 0:
            continue
        weighted_probability += float(model["calibrated_probability"]) * reliability
        total_weight += reliability
    calibrated = weighted_probability / total_weight if total_weight else baseline
    max_samples = max(int(model["sample_count"]) for model in models.values())
    statuses = {str(model["status"]) for model in models.values()}
    reliability = min(1.0, total_weight / max(1, len(models)))
    if "validated" in statuses and reliability >= 0.35:
        status = "validated"
    elif max_samples < 30:
        status = "insufficient"
    elif statuses == {"degraded"}:
        status = "degraded"
    else:
        status = "inconclusive"
    return {
        "calibrated_probability": _rounded(calibrated),
        "reliability": _rounded(reliability),
        "status": status,
        "max_sample_count": max_samples,
    }


def build_walk_forward_catalog(
    history: Sequence[int], catalog: Mapping[str, Any]
) -> dict[str, Any]:
    source_number = int(catalog["source_number"])
    previous_number = catalog.get("previous_number")
    numbers: dict[int, dict[str, Any]] = {
        number: {"number": number} for number in ROULETTE_NUMBERS
    }
    for horizon in (1, 3):
        baseline = _baseline(horizon)
        relation_samples, relation_current, relation_total = _relation_samples(
            history,
            source_number=source_number,
            horizon=horizon,
        )
        frequency_samples, frequency_current, frequency_total = _frequency_samples(
            history,
            source_number=source_number,
            horizon=horizon,
        )
        pair_samples, pair_current, pair_total = _pair_samples(
            history,
            previous_number=previous_number,
            source_number=source_number,
            horizon=horizon,
        )
        for number in ROULETTE_NUMBERS:
            models = {
                "relation": _sample_metrics(
                    list(relation_samples[number]),
                    current_prediction=relation_current[number],
                    baseline=baseline,
                    total_evaluated=relation_total,
                ),
                "frequency": _sample_metrics(
                    list(frequency_samples[number]),
                    current_prediction=frequency_current[number],
                    baseline=baseline,
                    total_evaluated=frequency_total,
                ),
                "pair": _sample_metrics(
                    list(pair_samples[number]),
                    current_prediction=pair_current[number],
                    baseline=baseline,
                    total_evaluated=pair_total,
                ),
            }
            numbers[number][f"horizon_{horizon}"] = {
                "fair_baseline": _rounded(baseline),
                "models": models,
                "combined": _combine_models(models, baseline),
            }
    return {
        "version": WALK_FORWARD_VERSION,
        "method": "chronological_source_conditioned_no_future_leakage",
        "source_number": source_number,
        "previous_number": previous_number,
        "minimum_training_support": WALK_FORWARD_MIN_TRAINING_SUPPORT,
        "maximum_recent_samples_per_model": WALK_FORWARD_MAX_SAMPLES,
        "frequency_window_spins": FREQUENCY_WINDOW,
        "numbers": numbers,
    }


def walk_forward_state_table(walk_forward: Mapping[str, Any]) -> dict[str, Any]:
    columns = ["number"]
    for horizon in (1, 3):
        prefix = f"h{horizon}"
        for model in ("relation", "frequency", "pair"):
            columns.extend(
                (
                    f"{prefix}_{model}_samples",
                    f"{prefix}_{model}_brier_improvement",
                    f"{prefix}_{model}_calibrated_probability",
                    f"{prefix}_{model}_reliability",
                    f"{prefix}_{model}_status",
                )
            )
        columns.extend(
            (
                f"{prefix}_combined_calibrated_probability",
                f"{prefix}_combined_reliability",
                f"{prefix}_combined_status",
            )
        )

    rows: list[list[Any]] = []
    numbers = walk_forward["numbers"]
    for number in ROULETTE_NUMBERS:
        row: list[Any] = [number]
        evidence = numbers[number]
        for horizon in (1, 3):
            horizon_evidence = evidence[f"horizon_{horizon}"]
            for model in ("relation", "frequency", "pair"):
                metrics = horizon_evidence["models"][model]
                row.extend(
                    (
                        metrics["sample_count"],
                        metrics["brier_improvement"],
                        metrics["calibrated_probability"],
                        metrics["reliability"],
                        metrics["status"],
                    )
                )
            combined = horizon_evidence["combined"]
            row.extend(
                (
                    combined["calibrated_probability"],
                    combined["reliability"],
                    combined["status"],
                )
            )
        rows.append(row)
    return {"columns": columns, "rows": rows}


def _pattern_quality(
    number: int, pattern_quality_by_target: Mapping[int, Mapping[str, Any]]
) -> float:
    quality = pattern_quality_by_target.get(number)
    if quality is None:
        return 0.55
    score = _clamp(float(quality.get("score_normalizado", 0.0)))
    confidence = _clamp(float(quality.get("confidence", 0.0)))
    return 0.5 + 0.5 * score * confidence


def _meta_item(
    *,
    number: int,
    horizon: int,
    jev_probability: float,
    validation: Mapping[str, Any],
    pattern_quality_by_target: Mapping[int, Mapping[str, Any]],
    regime: str,
) -> dict[str, Any]:
    evidence = validation[f"horizon_{horizon}"]
    combined = evidence["combined"]
    baseline = float(evidence["fair_baseline"])
    deterministic = float(combined["calibrated_probability"])
    regime_factor = {
        "transition_driven": 1.0,
        "frequency_concentration": 0.9,
        "gap_driven": 0.65,
        "neutral": 0.75,
        "unstable": 0.4,
    }.get(regime, 0.6)
    reliability = float(combined["reliability"])
    trust = min(0.90, reliability * regime_factor * _pattern_quality(number, pattern_quality_by_target))
    evidence_mix = 0.60 * jev_probability + 0.40 * deterministic
    probability = _clamp(baseline + trust * (evidence_mix - baseline))
    status = str(combined["status"])
    if status == "validated" and trust >= 0.30:
        label = "validated"
    elif status == "degraded":
        label = "degraded"
    elif int(combined["max_sample_count"]) >= 15:
        label = "experimental"
    else:
        label = "no_evidence"
    return {
        "numero": number,
        "probabilidade_meta": probability,
        "probabilidade_jev": jev_probability,
        "probabilidade_calibrada_deterministica": deterministic,
        "probabilidade_base": baseline,
        "diferenca_da_base": probability - baseline,
        "lift_sobre_base": probability / baseline,
        "confiabilidade_meta": trust,
        "status_validacao": label,
        "amostras_walk_forward": int(combined["max_sample_count"]),
        "modelos_walk_forward": {
            name: {
                "amostras": metrics["sample_count"],
                "ganho_brier": metrics["brier_improvement"],
                "status": metrics["status"],
            }
            for name, metrics in evidence["models"].items()
        },
    }


def build_meta_rankings(
    *,
    walk_forward: Mapping[str, Any],
    jev_three_spin_probabilities: Mapping[int, float],
    jev_next_spin_probabilities: Mapping[int, float],
    pattern_quality_by_target: Mapping[int, Mapping[str, Any]],
    regime: str,
) -> dict[str, Any]:
    numbers = walk_forward["numbers"]
    three_spin = [
        _meta_item(
            number=number,
            horizon=3,
            jev_probability=float(jev_three_spin_probabilities[number]),
            validation=numbers[number],
            pattern_quality_by_target=pattern_quality_by_target,
            regime=regime,
        )
        for number in ROULETTE_NUMBERS
    ]
    three_spin.sort(key=lambda item: (-item["probabilidade_meta"], item["numero"]))
    for position, item in enumerate(three_spin, start=1):
        item["posicao"] = position

    next_spin = [
        _meta_item(
            number=number,
            horizon=1,
            jev_probability=float(jev_next_spin_probabilities[number]),
            validation=numbers[number],
            pattern_quality_by_target=pattern_quality_by_target,
            regime=regime,
        )
        for number in ROULETTE_NUMBERS
    ]
    total_probability = sum(item["probabilidade_meta"] for item in next_spin)
    if not math.isfinite(total_probability) or total_probability <= 0:
        total_probability = 1.0
    for item in next_spin:
        probability = item["probabilidade_meta"] / total_probability
        item["probabilidade_meta"] = probability
        item["diferenca_da_base"] = probability - item["probabilidade_base"]
        item["lift_sobre_base"] = probability / item["probabilidade_base"]
    next_spin.sort(key=lambda item: (-item["probabilidade_meta"], item["numero"]))
    for position, item in enumerate(next_spin, start=1):
        item["posicao"] = position

    validated_positive = [
        item
        for item in three_spin
        if item["status_validacao"] == "validated" and item["diferenca_da_base"] > 0
    ]
    experimental_positive = [
        item
        for item in three_spin
        if item["status_validacao"] == "experimental" and item["diferenca_da_base"] > 0
    ]
    if regime == "unstable":
        status = "no_reliable_signal"
        reason = "O regime foi classificado como instável; as estimativas foram mantidas apenas para inspeção."
    elif validated_positive:
        status = "validated"
        reason = "Há candidatos acima da base com validação walk-forward e suporte suficiente."
    elif experimental_positive:
        status = "experimental"
        reason = "Há evidência acima da base, mas ela ainda não atingiu os critérios de validação."
    else:
        status = "no_reliable_signal"
        reason = "Nenhum candidato combinou vantagem estimada, suporte e validação suficientes."
    selected = validated_positive[:10] if validated_positive else []
    return {
        "ranking_tres_rodadas": three_spin,
        "ranking_proxima_rodada": next_spin,
        "signal": {
            "status": status,
            "available": status == "validated",
            "reason": reason,
            "validated_numbers": [item["numero"] for item in selected],
            "coverage": len(validated_positive) / len(ROULETTE_NUMBERS),
            "regime": regime,
        },
    }
