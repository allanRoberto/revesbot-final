"""Chronological calibration for a Jev top-N roulette selection.

The Jev probabilities are model outputs, not calibrated betting confidence.  This
module turns a complete 0-36 Choice distribution and deterministic walk-forward
evidence into a small feature vector, then evaluates it with a regularised
logistic model trained only on already resolved signals.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from api.services.jev_history_service import ROULETTE_SLUG


CONFIDENCE_SCHEMA_VERSION = "jev-top-k-confidence-v1"
FEATURE_NAMES = (
    "jev_top_k_mass",
    "cutoff_margin",
    "top_probability",
    "top_k_spread",
    "distribution_concentration",
    "mean_walk_forward_reliability",
    "minimum_walk_forward_reliability",
    "validated_fraction",
    "mean_deterministic_lift",
)
MINIMUM_TRAINING_SAMPLES = 30
MINIMUM_VALIDATION_SAMPLES = 8
VALIDATED_SAMPLE_COUNT = 50
MAXIMUM_TRAINING_SAMPLES = 5_000
_EPSILON = 1e-9


class JevConfidenceError(ValueError):
    pass


def fair_top_k_baseline(top_k: int, attempts: int) -> float:
    if not 1 <= top_k <= 36 or attempts < 1:
        raise JevConfidenceError("top_k e attempts devem ser positivos e válidos")
    return 1 - (1 - top_k / 37) ** attempts


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return min(maximum, max(minimum, value))


def _rounded(value: float | None) -> float | None:
    return round(value, 6) if value is not None else None


def _validated_distribution(probabilities: Mapping[str, float]) -> list[tuple[int, float]]:
    expected = {str(number) for number in range(37)}
    if set(probabilities) != expected:
        raise JevConfidenceError("a distribuição deve conter exatamente os números 0 a 36")
    rows = []
    for number in range(37):
        value = probabilities[str(number)]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise JevConfidenceError("a distribuição contém probabilidade inválida")
        probability = float(value)
        if not math.isfinite(probability) or probability < 0:
            raise JevConfidenceError("a distribuição contém probabilidade inválida")
        rows.append((number, probability))
    total = sum(probability for _number, probability in rows)
    if total <= 0:
        raise JevConfidenceError("a distribuição não possui massa positiva")
    return sorted(
        ((number, probability / total) for number, probability in rows),
        key=lambda row: (-row[1], row[0]),
    )


def extract_top_k_features(
    probabilities: Mapping[str, float],
    walk_forward: Mapping[str, Any],
    *,
    top_k: int,
) -> dict[str, Any]:
    """Build features known before the future outcome is observed."""
    if not 1 <= top_k <= 36:
        raise JevConfidenceError("top_k deve estar entre 1 e 36")
    ranked = _validated_distribution(probabilities)
    selected = ranked[:top_k]
    cutoff_next = ranked[top_k][1] if top_k < len(ranked) else 0.0
    probability_values = [probability for _number, probability in ranked]
    entropy = -sum(
        probability * math.log(probability)
        for probability in probability_values
        if probability > 0
    )
    concentration = 1 - entropy / math.log(37)

    numbers = walk_forward.get("numbers")
    if not isinstance(numbers, Mapping):
        raise JevConfidenceError("a validação walk-forward está incompleta")
    reliabilities = []
    statuses = []
    deterministic_lifts = []
    one_spin_baseline = 1 / 37
    for number, _probability in selected:
        number_evidence = numbers.get(number, numbers.get(str(number)))
        if not isinstance(number_evidence, Mapping):
            raise JevConfidenceError("faltam evidências walk-forward para o top-N")
        horizon = number_evidence.get("horizon_1")
        combined = horizon.get("combined") if isinstance(horizon, Mapping) else None
        if not isinstance(combined, Mapping):
            raise JevConfidenceError("a evidência walk-forward do próximo giro é inválida")
        reliability = _clamp(float(combined.get("reliability", 0.0)))
        deterministic = _clamp(float(combined.get("calibrated_probability", one_spin_baseline)))
        reliabilities.append(reliability)
        statuses.append(str(combined.get("status", "insufficient")))
        deterministic_lifts.append(deterministic / one_spin_baseline)

    selected_probabilities = [probability for _number, probability in selected]
    feature_values = {
        "jev_top_k_mass": sum(selected_probabilities),
        "cutoff_margin": selected_probabilities[-1] - cutoff_next,
        "top_probability": selected_probabilities[0],
        "top_k_spread": selected_probabilities[0] - selected_probabilities[-1],
        "distribution_concentration": concentration,
        "mean_walk_forward_reliability": sum(reliabilities) / len(reliabilities),
        "minimum_walk_forward_reliability": min(reliabilities),
        "validated_fraction": sum(status == "validated" for status in statuses) / top_k,
        "mean_deterministic_lift": sum(deterministic_lifts) / len(deterministic_lifts),
    }
    return {
        "schema_version": CONFIDENCE_SCHEMA_VERSION,
        "top_k": top_k,
        "selected_numbers": [number for number, _probability in selected],
        "values": {name: _rounded(feature_values[name]) for name in FEATURE_NAMES},
    }


def _sample_vector(sample: Mapping[str, Any]) -> tuple[list[float], int] | None:
    if sample.get("schema_version") != CONFIDENCE_SCHEMA_VERSION:
        return None
    values = sample.get("features")
    outcome = sample.get("outcome")
    if not isinstance(values, Mapping) or outcome not in (0, 1):
        return None
    try:
        vector = [float(values[name]) for name in FEATURE_NAMES]
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in vector):
        return None
    return vector, int(outcome)


def compatible_samples(
    samples: Sequence[Mapping[str, Any]],
    *,
    top_k: int,
    attempts: int,
    model: str | None = None,
    roulette_slug: str = ROULETTE_SLUG,
) -> list[Mapping[str, Any]]:
    compatible = []
    seen_sample_keys: set[str] = set()
    for sample in samples:
        if sample.get("roulette_slug", ROULETTE_SLUG) != roulette_slug:
            continue
        if sample.get("schema_version") != CONFIDENCE_SCHEMA_VERSION:
            continue
        if sample.get("top_k") != top_k or sample.get("attempts") != attempts:
            continue
        if model and sample.get("model") != model:
            continue
        if _sample_vector(sample) is not None:
            sample_key = sample.get("sample_key")
            if isinstance(sample_key, str) and sample_key:
                if sample_key in seen_sample_keys:
                    continue
                seen_sample_keys.add(sample_key)
            compatible.append(sample)
    return compatible[-MAXIMUM_TRAINING_SAMPLES:]


def _fit_logistic(
    rows: Sequence[tuple[list[float], int]],
) -> tuple[list[float], list[float], list[float]]:
    width = len(FEATURE_NAMES)
    means = [sum(row[0][column] for row in rows) / len(rows) for column in range(width)]
    scales = []
    for column in range(width):
        variance = sum((row[0][column] - means[column]) ** 2 for row in rows) / len(rows)
        scales.append(max(math.sqrt(variance), 1e-6))
    standardized = [
        [(value - means[index]) / scales[index] for index, value in enumerate(vector)]
        for vector, _outcome in rows
    ]
    event_rate = (sum(outcome for _vector, outcome in rows) + 1) / (len(rows) + 2)
    weights = [math.log(event_rate / (1 - event_rate))] + [0.0] * width
    learning_rate = 0.08
    regularization = 0.02
    for iteration in range(700):
        gradient = [0.0] * len(weights)
        for values, (_vector, outcome) in zip(standardized, rows):
            linear = weights[0] + sum(weight * value for weight, value in zip(weights[1:], values))
            probability = 1 / (1 + math.exp(-max(-35.0, min(35.0, linear))))
            error = probability - outcome
            gradient[0] += error
            for index, value in enumerate(values, start=1):
                gradient[index] += error * value
        count = len(rows)
        weights[0] -= learning_rate * gradient[0] / count
        for index in range(1, len(weights)):
            weights[index] -= learning_rate * (
                gradient[index] / count + regularization * weights[index]
            )
        if iteration in (250, 500):
            learning_rate *= 0.5
    return weights, means, scales


def _predict_logistic(
    vector: Sequence[float], weights: Sequence[float], means: Sequence[float], scales: Sequence[float]
) -> float:
    standardized = [
        (value - means[index]) / scales[index] for index, value in enumerate(vector)
    ]
    linear = weights[0] + sum(weight * value for weight, value in zip(weights[1:], standardized))
    return 1 / (1 + math.exp(-max(-35.0, min(35.0, linear))))


def assess_top_k_confidence(
    feature_record: Mapping[str, Any],
    samples: Sequence[Mapping[str, Any]],
    *,
    top_k: int,
    attempts: int,
    model: str | None = None,
    roulette_slug: str = ROULETTE_SLUG,
) -> dict[str, Any]:
    baseline = fair_top_k_baseline(top_k, attempts)
    compatible = compatible_samples(
        samples, top_k=top_k, attempts=attempts, model=model, roulette_slug=roulette_slug
    )
    values = feature_record.get("values")
    if not isinstance(values, Mapping):
        raise JevConfidenceError("as características de confiança são inválidas")
    current = [float(values[name]) for name in FEATURE_NAMES]
    jev_mass = _clamp(float(values["jev_top_k_mass"]))
    uncalibrated = 1 - (1 - jev_mass) ** attempts
    common = {
        "schema_version": CONFIDENCE_SCHEMA_VERSION,
        "roulette_slug": roulette_slug,
        "top_k": top_k,
        "attempts": attempts,
        "selected_numbers": list(feature_record["selected_numbers"]),
        "sample_count": len(compatible),
        "fair_baseline": _rounded(baseline),
        "uncalibrated_estimate": _rounded(uncalibrated),
    }
    if len(compatible) < MINIMUM_TRAINING_SAMPLES:
        return {
            **common,
            "status": "insufficient",
            "decision": "no_entry",
            "calibrated_probability": None,
            "conservative_lower_bound": None,
            "validation_brier": None,
            "baseline_brier": None,
            "brier_improvement": None,
            "validation_calibration_gap": None,
            "reason": (
                f"Amostra insuficiente: {len(compatible)}/{MINIMUM_TRAINING_SAMPLES} "
                "sinais compatíveis resolvidos."
            ),
        }

    rows = [_sample_vector(sample) for sample in compatible]
    clean_rows = [row for row in rows if row is not None]
    split = max(len(clean_rows) - max(MINIMUM_VALIDATION_SAMPLES, len(clean_rows) // 5), 1)
    training = clean_rows[:split]
    validation = clean_rows[split:]
    if len(training) < 20 or len(validation) < MINIMUM_VALIDATION_SAMPLES:
        return {
            **common,
            "status": "insufficient",
            "decision": "no_entry",
            "calibrated_probability": None,
            "conservative_lower_bound": None,
            "validation_brier": None,
            "baseline_brier": None,
            "brier_improvement": None,
            "validation_calibration_gap": None,
            "reason": "A divisão cronológica ainda não possui validação suficiente.",
        }

    weights, means, scales = _fit_logistic(training)
    validation_predictions = [
        _predict_logistic(vector, weights, means, scales) for vector, _outcome in validation
    ]
    outcomes = [outcome for _vector, outcome in validation]
    validation_brier = sum(
        (prediction - outcome) ** 2
        for prediction, outcome in zip(validation_predictions, outcomes)
    ) / len(validation)
    baseline_brier = sum((baseline - outcome) ** 2 for outcome in outcomes) / len(outcomes)
    improvement = (
        (baseline_brier - validation_brier) / baseline_brier if baseline_brier > 0 else 0.0
    )
    calibration_gap = abs(
        sum(validation_predictions) / len(validation_predictions) - sum(outcomes) / len(outcomes)
    )

    full_weights, full_means, full_scales = _fit_logistic(clean_rows)
    raw_probability = _predict_logistic(current, full_weights, full_means, full_scales)
    sample_factor = min(1.0, len(clean_rows) / 300)
    performance_factor = _clamp(improvement / 0.10) if improvement > 0 else 0.0
    reliability = sample_factor * performance_factor * _clamp(1 - calibration_gap / 0.20)
    calibrated = baseline + reliability * (raw_probability - baseline)
    standard_error = math.sqrt(max(_EPSILON, calibrated * (1 - calibrated)) / len(clean_rows))
    lower_bound = _clamp(calibrated - 1.645 * standard_error)

    if improvement <= 0 or calibration_gap > 0.15:
        status = "degraded"
    elif len(clean_rows) >= VALIDATED_SAMPLE_COUNT and improvement >= 0.02 and calibration_gap <= 0.08:
        status = "validated"
    else:
        status = "experimental"
    if status == "validated" and lower_bound > baseline:
        decision = "enter"
        reason = "A vantagem permanece acima da base no limite conservador e foi validada cronologicamente."
    elif status in {"validated", "experimental"} and calibrated > baseline:
        decision = "observe"
        reason = "A estimativa supera a base, mas a evidência ainda não autoriza uma entrada conservadora."
    else:
        decision = "no_entry"
        reason = "O calibrador não demonstrou vantagem estável sobre a referência aleatória."
    return {
        **common,
        "status": status,
        "decision": decision,
        "calibrated_probability": _rounded(calibrated),
        "conservative_lower_bound": _rounded(lower_bound),
        "reliability": _rounded(reliability),
        "validation_brier": _rounded(validation_brier),
        "baseline_brier": _rounded(baseline_brier),
        "brier_improvement": _rounded(improvement),
        "validation_calibration_gap": _rounded(calibration_gap),
        "reason": reason,
    }


def build_confidence_sample(
    feature_record: Mapping[str, Any],
    *,
    top_k: int,
    attempts: int,
    model: str,
    outcome: bool,
    roulette_slug: str = ROULETTE_SLUG,
) -> dict[str, Any]:
    return {
        "schema_version": CONFIDENCE_SCHEMA_VERSION,
        "roulette_slug": roulette_slug,
        "top_k": top_k,
        "attempts": attempts,
        "model": model,
        "sample_key": feature_record.get("context_sha256"),
        "selected_numbers": list(feature_record["selected_numbers"]),
        "features": dict(feature_record["values"]),
        "outcome": int(outcome),
    }


def load_persisted_confidence_samples(
    results_dir: str,
    *,
    top_k: int,
    attempts: int,
    model: str,
    roulette_slug: str = ROULETTE_SLUG,
) -> list[dict[str, Any]]:
    """Load only resolved samples written by completed backtest steps."""
    directory = Path(results_dir).expanduser() / "backtests"
    if not directory.is_dir():
        return []
    samples: list[dict[str, Any]] = []
    for source in sorted(directory.glob("*.steps.jsonl"), key=lambda path: path.stat().st_mtime):
        try:
            with source.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    sample = record.get("confidence_sample") if isinstance(record, dict) else None
                    if isinstance(sample, dict):
                        samples.append(sample)
        except OSError:
            continue
    return [
        dict(sample)
        for sample in compatible_samples(
            samples, top_k=top_k, attempts=attempts, model=model, roulette_slug=roulette_slug
        )
    ]
