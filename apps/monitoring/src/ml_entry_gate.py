from __future__ import annotations

from datetime import datetime, timezone
from math import exp
from typing import Any, Dict, Iterable, List, Mapping


ML_ENTRY_GATE_VERSION = 1
ML_ENTRY_GATE_FEATURE_NAMES = [
    "top12_mean_final_score",
    "top12_mean_model_probability",
    "top12_max_model_probability",
    "top12_min_model_probability",
    "top12_probability_spread",
    "top4_mean_model_probability",
    "top12_mean_heuristic_score",
    "top12_mean_time_region_prior",
    "top12_mean_history_region_density",
    "top12_mean_top26_rank_score",
    "top12_mean_dynamic_weight",
    "top12_positive_pattern_share",
    "top12_negative_pattern_share",
    "top12_mean_base_rank_score",
    "confidence_score",
    "confidence_delta",
    "latest_rank_top_flag",
    "latest_rank_middle_flag",
    "latest_rank_bottom_flag",
    "rank_context_avg_ratio",
    "rank_context_zigzag_rate",
    "rank_context_worsening",
    "rank_context_improvement",
    "rank_context_top_share",
    "rank_context_bottom_share",
]


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, float(value)))


def _sigmoid(value: float) -> float:
    bounded = _clamp(value, -18.0, 18.0)
    return 1.0 / (1.0 + exp(-bounded))


def _top_weight_features(weights: Mapping[str, float], *, limit: int = 8) -> List[Dict[str, Any]]:
    return [
        {
            "feature": feature_name,
            "weight": round(_safe_float(weight), 6),
        }
        for feature_name, weight in sorted(
            dict(weights).items(),
            key=lambda item: (-abs(_safe_float(item[1])), item[0]),
        )[: max(1, int(limit))]
    ]


def build_default_ml_entry_gate_state(
    *,
    roulette_id: str,
    config_key: str,
    learning_rate: float = 0.05,
    positive_class_weight: float = 5.5,
    negative_class_weight: float = 1.0,
    l2_decay: float = 0.001,
    warmup_events: int = 20,
    threshold: float = 0.58,
) -> Dict[str, Any]:
    return {
        "model_name": "ml_entry_gate_v1",
        "model_version": ML_ENTRY_GATE_VERSION,
        "roulette_id": str(roulette_id or "").strip(),
        "config_key": str(config_key or "").strip(),
        "feature_names": list(ML_ENTRY_GATE_FEATURE_NAMES),
        "weights": {name: 0.0 for name in ML_ENTRY_GATE_FEATURE_NAMES},
        "bias": 0.0,
        "trained_events": 0,
        "trained_rows": 0,
        "learning_rate": float(learning_rate),
        "positive_class_weight": float(positive_class_weight),
        "negative_class_weight": float(negative_class_weight),
        "l2_decay": float(l2_decay),
        "warmup_events": int(max(8, warmup_events)),
        "threshold": float(threshold),
        "last_train_event_id": "",
        "last_label": None,
        "top_weight_features": [],
        "updated_at": datetime.now(timezone.utc),
    }


def _normalize_state(model_state: Mapping[str, Any] | None, *, roulette_id: str, config_key: str) -> Dict[str, Any]:
    base = build_default_ml_entry_gate_state(roulette_id=roulette_id, config_key=config_key)
    if not isinstance(model_state, Mapping):
        return base
    weights = {
        name: _safe_float(dict(model_state.get("weights") or {}).get(name), 0.0)
        for name in ML_ENTRY_GATE_FEATURE_NAMES
    }
    base.update(
        {
            "weights": weights,
            "bias": _safe_float(model_state.get("bias"), 0.0),
            "trained_events": max(0, _safe_int(model_state.get("trained_events"), 0)),
            "trained_rows": max(0, _safe_int(model_state.get("trained_rows"), 0)),
            "learning_rate": max(0.0001, _safe_float(model_state.get("learning_rate"), base["learning_rate"])),
            "positive_class_weight": max(1.0, _safe_float(model_state.get("positive_class_weight"), base["positive_class_weight"])),
            "negative_class_weight": max(0.1, _safe_float(model_state.get("negative_class_weight"), base["negative_class_weight"])),
            "l2_decay": max(0.0, _safe_float(model_state.get("l2_decay"), base["l2_decay"])),
            "warmup_events": max(8, _safe_int(model_state.get("warmup_events"), base["warmup_events"])),
            "threshold": _clamp(_safe_float(model_state.get("threshold"), base["threshold"]), 0.35, 0.9),
            "last_train_event_id": str(model_state.get("last_train_event_id") or "").strip(),
            "last_label": model_state.get("last_label"),
            "updated_at": model_state.get("updated_at") or base["updated_at"],
        }
    )
    return base


def _extract_ordered_suggestion(payload: Mapping[str, Any]) -> List[int]:
    return [
        int(value)
        for value in (
            payload.get("ordered_suggestion")
            or payload.get("suggestion")
            or payload.get("list")
            or []
        )
        if str(value).strip()
    ]


def _extract_selected_details(payload: Mapping[str, Any]) -> List[Dict[str, Any]]:
    raw_details = payload.get("selected_number_details")
    if isinstance(raw_details, list):
        return [dict(item) for item in raw_details if isinstance(item, Mapping)]
    return []


def _extract_ml_candidate_features(payload: Mapping[str, Any]) -> List[Dict[str, Any]]:
    oscillation = dict(payload.get("oscillation") or {}) if isinstance(payload.get("oscillation"), Mapping) else {}
    ml_meta_rank = dict(oscillation.get("ml_meta_rank") or {}) if isinstance(oscillation.get("ml_meta_rank"), Mapping) else {}
    return [
        dict(item)
        for item in (ml_meta_rank.get("candidate_features") or [])
        if isinstance(item, Mapping) and _safe_int(item.get("number"), -1) >= 0
    ]


def build_ml_entry_gate_feature_row(
    ml_payload: Mapping[str, Any],
    *,
    suggestion_size: int = 12,
) -> Dict[str, Any]:
    candidate_features = _extract_ml_candidate_features(ml_payload)
    if not candidate_features:
        return {feature_name: 0.0 for feature_name in ML_ENTRY_GATE_FEATURE_NAMES}

    top_candidates = list(candidate_features[: max(1, int(suggestion_size))])
    count = max(1, len(top_candidates))
    probabilities = [_safe_float(item.get("model_probability"), 0.0) for item in top_candidates]
    heuristic_scores = [_safe_float(item.get("heuristic_score"), 0.0) for item in top_candidates]
    final_scores = [_safe_float(item.get("final_score"), 0.0) for item in top_candidates]
    features_rows = [dict(item.get("features") or {}) for item in top_candidates]

    entry_shadow = dict(ml_payload.get("entry_shadow") or {}) if isinstance(ml_payload.get("entry_shadow"), Mapping) else {}
    entry_confidence = dict(entry_shadow.get("entry_confidence") or {}) if isinstance(entry_shadow.get("entry_confidence"), Mapping) else {}
    rank_context = dict(entry_shadow.get("rank_context_confidence") or {}) if isinstance(entry_shadow.get("rank_context_confidence"), Mapping) else {}
    latest_rank_band = str(rank_context.get("latest_rank_band") or "").strip().lower()

    return {
        "top12_mean_final_score": round(sum(final_scores) / count, 6),
        "top12_mean_model_probability": round(sum(probabilities) / count, 6),
        "top12_max_model_probability": round(max(probabilities) if probabilities else 0.0, 6),
        "top12_min_model_probability": round(min(probabilities) if probabilities else 0.0, 6),
        "top12_probability_spread": round((max(probabilities) - min(probabilities)) if probabilities else 0.0, 6),
        "top4_mean_model_probability": round(sum(probabilities[:4]) / max(1, min(4, len(probabilities))), 6),
        "top12_mean_heuristic_score": round(sum(heuristic_scores) / count, 6),
        "top12_mean_time_region_prior": round(sum(_safe_float(row.get("time_region_prior"), 0.0) for row in features_rows) / count, 6),
        "top12_mean_history_region_density": round(sum(_safe_float(row.get("history_region_density"), 0.0) for row in features_rows) / count, 6),
        "top12_mean_top26_rank_score": round(sum(_safe_float(row.get("top26_rank_score"), 0.0) for row in features_rows) / count, 6),
        "top12_mean_dynamic_weight": round(sum(_safe_float(row.get("base_dynamic_weight_avg_norm"), 0.0) for row in features_rows) / count, 6),
        "top12_positive_pattern_share": round(sum(_safe_float(row.get("base_positive_pattern_share"), 0.0) for row in features_rows) / count, 6),
        "top12_negative_pattern_share": round(sum(_safe_float(row.get("base_negative_pattern_share"), 0.0) for row in features_rows) / count, 6),
        "top12_mean_base_rank_score": round(sum(_safe_float(row.get("base_rank_score"), 0.0) for row in features_rows) / count, 6),
        "confidence_score": round(_clamp(_safe_float(entry_confidence.get("score"), 0.0) / 100.0, 0.0, 1.0), 6),
        "confidence_delta": round(_clamp(_safe_float(rank_context.get("confidence_delta"), 0.0) / 16.0, -1.0, 1.0), 6),
        "latest_rank_top_flag": 1.0 if latest_rank_band == "top" else 0.0,
        "latest_rank_middle_flag": 1.0 if latest_rank_band == "middle" else 0.0,
        "latest_rank_bottom_flag": 1.0 if latest_rank_band == "bottom" else 0.0,
        "rank_context_avg_ratio": round(_clamp(_safe_float(rank_context.get("avg_rank_ratio"), 0.0), 0.0, 1.0), 6),
        "rank_context_zigzag_rate": round(_clamp(_safe_float(rank_context.get("zigzag_rate"), 0.0), 0.0, 1.0), 6),
        "rank_context_worsening": round(_clamp(_safe_float(rank_context.get("worsening_strength"), 0.0), 0.0, 1.0), 6),
        "rank_context_improvement": round(_clamp(_safe_float(rank_context.get("improvement_strength"), 0.0), 0.0, 1.0), 6),
        "rank_context_top_share": round(_clamp(_safe_float(rank_context.get("top_band_share"), 0.0), 0.0, 1.0), 6),
        "rank_context_bottom_share": round(_clamp(_safe_float(rank_context.get("lower_band_share"), 0.0), 0.0, 1.0), 6),
    }


def _predict_probability(model_state: Mapping[str, Any], feature_row: Mapping[str, Any]) -> float:
    feature_names = list(model_state.get("feature_names") or ML_ENTRY_GATE_FEATURE_NAMES)
    weights = dict(model_state.get("weights") or {})
    linear_score = _safe_float(model_state.get("bias"), 0.0)
    for feature_name in feature_names:
        linear_score += _safe_float(weights.get(feature_name), 0.0) * _safe_float(feature_row.get(feature_name), 0.0)
    return _sigmoid(linear_score)


def build_ml_top12_reference_payload_from_ml_meta(
    ml_payload: Mapping[str, Any],
    *,
    suggestion_size: int = 12,
    evaluation_window_attempts: int = 4,
) -> Dict[str, Any] | None:
    suggestion = _extract_ordered_suggestion(ml_payload)
    if not suggestion:
        return None
    selected_details = _extract_selected_details(ml_payload)
    if not selected_details:
        return None
    compact_limit = max(1, min(len(selected_details), int(suggestion_size)))
    top_details = [dict(item) for item in selected_details[:compact_limit]]
    top_suggestion = [int(item["number"]) for item in top_details]
    feature_row = build_ml_entry_gate_feature_row(ml_payload, suggestion_size=compact_limit)
    entry_shadow = dict(ml_payload.get("entry_shadow") or {}) if isinstance(ml_payload.get("entry_shadow"), Mapping) else {}
    entry_shadow["recommendation"] = {
        "action": "enter",
        "label": "Entrar (Ref)",
        "reason": "Estratégia de referência: entra sempre nos 12 primeiros do ML Meta Rank para gerar labels do gate.",
    }
    return {
        "available": True,
        "list": top_suggestion,
        "suggestion": top_suggestion,
        "ordered_suggestion": top_suggestion,
        "pattern_count": int(ml_payload.get("pattern_count") or 0),
        "unique_numbers": int(compact_limit),
        "selected_number_details": top_details,
        "entry_shadow": entry_shadow,
        "evaluation_window_attempts": int(max(1, evaluation_window_attempts)),
        "explanation": "Referência operacional do ML Meta Rank: top 12 fixos em janela de 4 tentativas.",
        "oscillation": {
            "profile": "ml_top12_reference_12x4_v1",
            "ml_entry_gate": {
                "mode": "reference",
                "gate_features": feature_row,
                "top12_suggestion": top_suggestion,
                "suggestion_size": int(compact_limit),
                "evaluation_window_attempts": int(max(1, evaluation_window_attempts)),
            },
        },
    }


def build_ml_entry_gate_payload_from_ml_meta(
    ml_payload: Mapping[str, Any],
    model_state: Mapping[str, Any] | None,
    *,
    roulette_id: str,
    config_key: str,
    suggestion_size: int = 12,
    evaluation_window_attempts: int = 4,
) -> Dict[str, Any] | None:
    suggestion = _extract_ordered_suggestion(ml_payload)
    if not suggestion:
        return None
    selected_details = _extract_selected_details(ml_payload)
    if not selected_details:
        return None
    normalized_state = _normalize_state(model_state, roulette_id=roulette_id, config_key=config_key)
    compact_limit = max(1, min(len(selected_details), int(suggestion_size)))
    top_details = [dict(item) for item in selected_details[:compact_limit]]
    top_suggestion = [int(item["number"]) for item in top_details]
    feature_row = build_ml_entry_gate_feature_row(ml_payload, suggestion_size=compact_limit)
    probability = _predict_probability(normalized_state, feature_row)
    threshold = _clamp(_safe_float(normalized_state.get("threshold"), 0.58), 0.35, 0.9)
    trained_events = _safe_int(normalized_state.get("trained_events"), 0)
    warmup_events = max(8, _safe_int(normalized_state.get("warmup_events"), 20))
    warmup_ready = trained_events >= max(6, round(warmup_events * 0.35))
    should_enter = bool(warmup_ready and probability >= threshold)

    entry_shadow = dict(ml_payload.get("entry_shadow") or {}) if isinstance(ml_payload.get("entry_shadow"), Mapping) else {}
    entry_shadow["recommendation"] = {
        "action": "enter" if should_enter else "wait",
        "label": "Entrar" if should_enter else "Aguardar",
        "reason": (
            f"Gate ML {probability:.3f} >= {threshold:.3f}; entrada autorizada."
            if should_enter
            else f"Gate ML {probability:.3f} < {threshold:.3f} ou aquecimento insuficiente; entrada bloqueada."
        ),
    }

    return {
        "available": bool(should_enter),
        "list": top_suggestion,
        "suggestion": top_suggestion,
        "ordered_suggestion": top_suggestion,
        "pattern_count": int(ml_payload.get("pattern_count") or 0),
        "unique_numbers": int(compact_limit),
        "selected_number_details": top_details,
        "entry_shadow": entry_shadow,
        "evaluation_window_attempts": int(max(1, evaluation_window_attempts)),
        "explanation": (
            "Gate operacional do ML Meta Rank. "
            f"probability={probability:.3f} threshold={threshold:.3f} trained_events={trained_events} warmup_ready={str(warmup_ready).lower()}."
        ),
        "oscillation": {
            "profile": "ml_entry_gate_12x4_v1",
            "ml_entry_gate": {
                "mode": "gated",
                "gate_features": feature_row,
                "probability": round(probability, 6),
                "threshold": round(threshold, 6),
                "should_enter": bool(should_enter),
                "trained_events": int(trained_events),
                "warmup_events": int(warmup_events),
                "warmup_ready": bool(warmup_ready),
                "top12_suggestion": top_suggestion,
                "suggestion_size": int(compact_limit),
                "evaluation_window_attempts": int(max(1, evaluation_window_attempts)),
                "top_weight_features": _top_weight_features(dict(normalized_state.get("weights") or {})),
            },
        },
    }


def train_ml_entry_gate_state_from_labeled_features(
    model_state: Mapping[str, Any] | None,
    feature_row: Mapping[str, Any],
    *,
    label: bool,
    roulette_id: str,
    config_key: str,
    source_event_id: str = "",
    epochs: int = 2,
) -> Dict[str, Any]:
    normalized_state = _normalize_state(model_state, roulette_id=roulette_id, config_key=config_key)
    feature_names = list(normalized_state["feature_names"])
    weights = dict(normalized_state["weights"])
    bias = _safe_float(normalized_state.get("bias"), 0.0)
    learning_rate = max(0.0001, _safe_float(normalized_state.get("learning_rate"), 0.05))
    positive_class_weight = max(1.0, _safe_float(normalized_state.get("positive_class_weight"), 5.5))
    negative_class_weight = max(0.1, _safe_float(normalized_state.get("negative_class_weight"), 1.0))
    l2_decay = max(0.0, _safe_float(normalized_state.get("l2_decay"), 0.001))
    y = 1.0 if bool(label) else 0.0
    sample_weight = positive_class_weight if y > 0.5 else negative_class_weight
    trained_rows = 0

    for _ in range(max(1, int(epochs))):
        linear_score = bias + sum(_safe_float(weights.get(name), 0.0) * _safe_float(feature_row.get(name), 0.0) for name in feature_names)
        probability = _sigmoid(linear_score)
        error = y - probability
        bias = _clamp(bias + (learning_rate * sample_weight * error), -6.0, 6.0)
        for feature_name in feature_names:
            value = _safe_float(feature_row.get(feature_name), 0.0)
            current_weight = _safe_float(weights.get(feature_name), 0.0)
            current_weight *= max(0.0, 1.0 - (learning_rate * l2_decay))
            current_weight += learning_rate * sample_weight * error * value
            weights[feature_name] = _clamp(current_weight, -6.0, 6.0)
        trained_rows += 1

    updated = dict(normalized_state)
    updated["weights"] = {name: round(_safe_float(weights.get(name), 0.0), 6) for name in feature_names}
    updated["bias"] = round(_safe_float(bias, 0.0), 6)
    updated["trained_events"] = int(normalized_state.get("trained_events") or 0) + 1
    updated["trained_rows"] = int(normalized_state.get("trained_rows") or 0) + trained_rows
    updated["last_train_event_id"] = str(source_event_id or "").strip()
    updated["last_label"] = bool(label)
    updated["top_weight_features"] = _top_weight_features(updated["weights"])
    updated["updated_at"] = datetime.now(timezone.utc)
    return updated


def train_ml_entry_gate_state_from_reference_event(
    model_state: Mapping[str, Any] | None,
    reference_event_doc: Mapping[str, Any],
    *,
    roulette_id: str,
    config_key: str,
) -> Dict[str, Any]:
    oscillation = dict(reference_event_doc.get("oscillation") or {}) if isinstance(reference_event_doc.get("oscillation"), Mapping) else {}
    gate_payload = dict(oscillation.get("ml_entry_gate") or {}) if isinstance(oscillation.get("ml_entry_gate"), Mapping) else {}
    feature_row = dict(gate_payload.get("gate_features") or {}) if isinstance(gate_payload.get("gate_features"), Mapping) else {}
    if not feature_row:
        return _normalize_state(model_state, roulette_id=roulette_id, config_key=config_key)
    label = bool(reference_event_doc.get("window_result_hit"))
    return train_ml_entry_gate_state_from_labeled_features(
        model_state,
        feature_row,
        label=label,
        roulette_id=roulette_id,
        config_key=config_key,
        source_event_id=str(reference_event_doc.get("_id") or ""),
    )


def train_ml_entry_gate_state_from_ml_meta_event(
    model_state: Mapping[str, Any] | None,
    ml_meta_event_doc: Mapping[str, Any],
    future_results: Iterable[Mapping[str, Any]],
    *,
    roulette_id: str,
    config_key: str,
    suggestion_size: int = 12,
    evaluation_window_attempts: int = 4,
) -> Dict[str, Any]:
    suggestion = _extract_ordered_suggestion(ml_meta_event_doc)[: max(1, int(suggestion_size))]
    if not suggestion:
        return _normalize_state(model_state, roulette_id=roulette_id, config_key=config_key)
    feature_row = build_ml_entry_gate_feature_row(ml_meta_event_doc, suggestion_size=min(len(suggestion), int(suggestion_size)))
    future_values = [
        _safe_int(doc.get("value"), -1)
        for doc in list(future_results or [])[: max(1, int(evaluation_window_attempts))]
        if isinstance(doc, Mapping)
    ]
    label = any(value in suggestion for value in future_values)
    return train_ml_entry_gate_state_from_labeled_features(
        model_state,
        feature_row,
        label=label,
        roulette_id=roulette_id,
        config_key=config_key,
        source_event_id=str(ml_meta_event_doc.get("_id") or ""),
    )
