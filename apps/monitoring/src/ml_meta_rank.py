from __future__ import annotations

from datetime import datetime, timezone
from math import exp
from typing import Any, Dict, Iterable, List, Mapping

from src.time_window_prior import WHEEL_INDEX


ML_META_RANK_VERSION = 1
ML_META_RANK_FEATURE_NAMES = [
    "base_rank_score",
    "base_weighted_support_norm",
    "base_support_norm",
    "base_pattern_count_norm",
    "base_dynamic_weight_avg_norm",
    "base_dynamic_weight_max_norm",
    "base_positive_pattern_share",
    "base_negative_pattern_share",
    "top26_rank_score",
    "top26_candidate_flag",
    "top26_rerank_score_norm",
    "top26_suggestion_memory",
    "top26_result_memory",
    "top26_regional_persistence",
    "top26_persistence",
    "top26_volatility_penalty",
    "time_rank_score",
    "time_exact_prior",
    "time_region_prior",
    "time_final_score_norm",
    "history_similarity_1",
    "history_similarity_2",
    "history_similarity_3",
    "history_region_density",
    "history_exact_recent_flag",
    "confidence_score",
    "confidence_delta",
    "confidence_top_flag",
    "confidence_middle_flag",
    "confidence_bottom_flag",
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


def _normalize_score_map(raw_scores: Mapping[int, float]) -> Dict[int, float]:
    cleaned = {int(number): float(score) for number, score in dict(raw_scores).items()}
    if not cleaned:
        return {}
    min_score = min(cleaned.values())
    max_score = max(cleaned.values())
    if max_score - min_score <= 1e-9:
        if max_score <= 0.0:
            return {number: 0.0 for number in cleaned}
        return {number: 1.0 for number in cleaned}
    return {
        int(number): round((float(score) - min_score) / (max_score - min_score), 6)
        for number, score in cleaned.items()
    }


def _extract_suggestion(payload: Mapping[str, Any]) -> List[int]:
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


def _extract_selected_number_details(payload: Mapping[str, Any]) -> List[Dict[str, Any]]:
    raw_details = payload.get("selected_number_details")
    if isinstance(raw_details, list) and raw_details:
        return [dict(item) for item in raw_details if isinstance(item, Mapping)]
    raw_number_details = payload.get("number_details")
    if isinstance(raw_number_details, list):
        return [dict(item) for item in raw_number_details if isinstance(item, Mapping)]
    return []


def _position_score(position: int, total: int) -> float:
    safe_total = max(1, int(total))
    safe_position = max(1, int(position))
    if safe_total <= 1:
        return 1.0
    return _clamp(1.0 - ((safe_position - 1.0) / max(1.0, safe_total - 1.0)), 0.0, 1.0)


def _region_similarity(number: int, other: int, sigma: float = 2.0) -> float:
    if number not in WHEEL_INDEX or other not in WHEEL_INDEX:
        return 0.0
    index = WHEEL_INDEX[number]
    other_index = WHEEL_INDEX[other]
    wheel_size = max(1, len(WHEEL_INDEX))
    distance = abs(index - other_index)
    wheel_distance = min(distance, wheel_size - distance)
    return exp(-(wheel_distance / max(0.35, float(sigma))))


def build_default_ml_meta_rank_state(
    *,
    roulette_id: str,
    config_key: str,
    learning_rate: float = 0.045,
    positive_class_weight: float = 9.0,
    negative_class_weight: float = 0.75,
    l2_decay: float = 0.0008,
    warmup_events: int = 18,
) -> Dict[str, Any]:
    return {
        "model_name": "ml_meta_rank_v1",
        "model_version": ML_META_RANK_VERSION,
        "roulette_id": str(roulette_id or "").strip(),
        "config_key": str(config_key or "").strip(),
        "feature_names": list(ML_META_RANK_FEATURE_NAMES),
        "weights": {name: 0.0 for name in ML_META_RANK_FEATURE_NAMES},
        "bias": 0.0,
        "trained_events": 0,
        "trained_rows": 0,
        "learning_rate": float(learning_rate),
        "positive_class_weight": float(positive_class_weight),
        "negative_class_weight": float(negative_class_weight),
        "l2_decay": float(l2_decay),
        "warmup_events": int(max(6, warmup_events)),
        "last_train_event_id": "",
        "last_resolved_number": None,
        "last_winner_rank_before_update": None,
        "top_weight_features": [],
        "updated_at": datetime.now(timezone.utc),
    }


def _normalize_model_state(model_state: Mapping[str, Any] | None, *, roulette_id: str, config_key: str) -> Dict[str, Any]:
    base = build_default_ml_meta_rank_state(roulette_id=roulette_id, config_key=config_key)
    if not isinstance(model_state, Mapping):
        return base
    weights = {
        name: _safe_float(dict(model_state.get("weights") or {}).get(name), 0.0)
        for name in ML_META_RANK_FEATURE_NAMES
    }
    base.update(
        {
            "bias": _safe_float(model_state.get("bias"), 0.0),
            "weights": weights,
            "trained_events": max(0, _safe_int(model_state.get("trained_events"), 0)),
            "trained_rows": max(0, _safe_int(model_state.get("trained_rows"), 0)),
            "learning_rate": max(0.0001, _safe_float(model_state.get("learning_rate"), base["learning_rate"])),
            "positive_class_weight": max(1.0, _safe_float(model_state.get("positive_class_weight"), base["positive_class_weight"])),
            "negative_class_weight": max(0.1, _safe_float(model_state.get("negative_class_weight"), base["negative_class_weight"])),
            "l2_decay": max(0.0, _safe_float(model_state.get("l2_decay"), base["l2_decay"])),
            "warmup_events": max(6, _safe_int(model_state.get("warmup_events"), base["warmup_events"])),
            "last_train_event_id": str(model_state.get("last_train_event_id") or "").strip(),
            "last_resolved_number": model_state.get("last_resolved_number"),
            "last_winner_rank_before_update": model_state.get("last_winner_rank_before_update"),
            "updated_at": model_state.get("updated_at") or base["updated_at"],
        }
    )
    return base


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


def build_ml_meta_rank_payload_from_context(
    *,
    base_payload: Mapping[str, Any],
    top26_payload: Mapping[str, Any] | None,
    time_window_prior_payload: Mapping[str, Any] | None,
    history_values: List[int] | None,
    model_state: Mapping[str, Any] | None,
    roulette_id: str,
    config_key: str,
) -> Dict[str, Any] | None:
    suggestion = _extract_suggestion(base_payload)
    if not suggestion:
        return None

    base_details = _extract_selected_number_details(base_payload)
    if not base_details:
        return None

    normalized_state = _normalize_model_state(model_state, roulette_id=roulette_id, config_key=config_key)
    feature_names = list(normalized_state["feature_names"])
    weights = dict(normalized_state["weights"])
    bias = _safe_float(normalized_state.get("bias"), 0.0)

    top26_details = _extract_selected_number_details(top26_payload or {})
    time_window_details = _extract_selected_number_details(time_window_prior_payload or {})
    top26_map = {_safe_int(item.get("number"), -1): dict(item) for item in top26_details if _safe_int(item.get("number"), -1) >= 0}
    time_map = {_safe_int(item.get("number"), -1): dict(item) for item in time_window_details if _safe_int(item.get("number"), -1) >= 0}
    base_map = {_safe_int(item.get("number"), -1): dict(item) for item in base_details if _safe_int(item.get("number"), -1) >= 0}

    ordered_base_numbers = [_safe_int(item.get("number"), -1) for item in base_details if _safe_int(item.get("number"), -1) >= 0]
    if len(ordered_base_numbers) != len(suggestion):
        ordered_base_numbers = list(suggestion)
    suggestion_size = max(1, len(ordered_base_numbers))
    base_rank_map = {number: index + 1 for index, number in enumerate(ordered_base_numbers)}

    weighted_support_norm = _normalize_score_map({
        int(item["number"]): _safe_float(item.get("weighted_support_score"), 0.0)
        for item in base_details
    })
    support_norm = _normalize_score_map({
        int(item["number"]): _safe_float(item.get("support_score"), 0.0)
        for item in base_details
    })
    pattern_count_raw = {
        int(item["number"]): len([pattern for pattern in (item.get("supporting_patterns") or []) if isinstance(pattern, Mapping)])
        for item in base_details
    }
    pattern_count_norm = _normalize_score_map(pattern_count_raw)

    dynamic_weights = {
        str(pattern_id).strip(): _safe_float(weight, 1.0)
        for pattern_id, weight in dict((base_payload.get("dynamic_weighting") or {}).get("weights") or {}).items()
        if str(pattern_id).strip()
    }

    dynamic_weight_sum_raw: Dict[int, float] = {}
    dynamic_weight_avg_raw: Dict[int, float] = {}
    dynamic_weight_max_raw: Dict[int, float] = {}
    positive_pattern_share_raw: Dict[int, float] = {}
    negative_pattern_share_raw: Dict[int, float] = {}
    for item in base_details:
        number = int(item["number"])
        supporting_patterns = [dict(pattern) for pattern in (item.get("supporting_patterns") or []) if isinstance(pattern, Mapping)]
        runtime_values: List[float] = []
        positive_count = 0
        negative_count = 0
        for pattern in supporting_patterns:
            pattern_id = str(pattern.get("base_pattern_id") or pattern.get("pattern_id") or "").strip()
            runtime_weight = _safe_float(dynamic_weights.get(pattern_id), _safe_float(pattern.get("applied_weight"), 1.0))
            runtime_values.append(runtime_weight)
            if runtime_weight > 1.0:
                positive_count += 1
            elif runtime_weight < 1.0:
                negative_count += 1
        if runtime_values:
            dynamic_weight_sum_raw[number] = sum(runtime_values)
            dynamic_weight_avg_raw[number] = sum(runtime_values) / len(runtime_values)
            dynamic_weight_max_raw[number] = max(runtime_values)
            positive_pattern_share_raw[number] = positive_count / len(runtime_values)
            negative_pattern_share_raw[number] = negative_count / len(runtime_values)
        else:
            dynamic_weight_sum_raw[number] = 0.0
            dynamic_weight_avg_raw[number] = 1.0
            dynamic_weight_max_raw[number] = 1.0
            positive_pattern_share_raw[number] = 0.0
            negative_pattern_share_raw[number] = 0.0

    dynamic_weight_avg_norm = _normalize_score_map(dynamic_weight_avg_raw)
    dynamic_weight_max_norm = _normalize_score_map(dynamic_weight_max_raw)

    top26_rerank_score_norm = _normalize_score_map({
        int(item["number"]): _safe_float(item.get("top26_rerank_score"), 0.0)
        for item in top26_details
    })
    time_final_score_norm = _normalize_score_map({
        int(item["number"]): _safe_float(item.get("time_window_final_score"), 0.0)
        for item in time_window_details
    })

    history_numbers = [int(value) for value in list(history_values or [])[:8] if 0 <= int(value) <= 36]
    entry_shadow = dict(base_payload.get("entry_shadow") or {}) if isinstance(base_payload.get("entry_shadow"), Mapping) else {}
    entry_confidence = dict(entry_shadow.get("entry_confidence") or {}) if isinstance(entry_shadow.get("entry_confidence"), Mapping) else {}
    rank_context = dict(entry_shadow.get("rank_context_confidence") or {}) if isinstance(entry_shadow.get("rank_context_confidence"), Mapping) else {}
    confidence_score = _clamp(_safe_float(entry_confidence.get("score"), 50.0) / 100.0, 0.0, 1.0)
    confidence_delta = _clamp(_safe_float(rank_context.get("confidence_delta"), 0.0) / 16.0, -1.0, 1.0)
    latest_rank_band = str(rank_context.get("latest_rank_band") or "").strip().lower()

    candidate_features: List[Dict[str, Any]] = []
    for number in ordered_base_numbers:
        base_rank_position = int(base_rank_map.get(number) or 1)
        top26_detail = top26_map.get(number, {})
        time_detail = time_map.get(number, {})
        feature_row = {
            "base_rank_score": round(_position_score(base_rank_position, suggestion_size), 6),
            "base_weighted_support_norm": round(weighted_support_norm.get(number, 0.0), 6),
            "base_support_norm": round(support_norm.get(number, 0.0), 6),
            "base_pattern_count_norm": round(pattern_count_norm.get(number, 0.0), 6),
            "base_dynamic_weight_avg_norm": round(dynamic_weight_avg_norm.get(number, 0.0), 6),
            "base_dynamic_weight_max_norm": round(dynamic_weight_max_norm.get(number, 0.0), 6),
            "base_positive_pattern_share": round(positive_pattern_share_raw.get(number, 0.0), 6),
            "base_negative_pattern_share": round(negative_pattern_share_raw.get(number, 0.0), 6),
            "top26_rank_score": round(
                _position_score(_safe_int(top26_detail.get("top26_reranked_position"), suggestion_size), suggestion_size),
                6,
            ),
            "top26_candidate_flag": 1.0 if bool(top26_detail.get("top26_candidate")) else 0.0,
            "top26_rerank_score_norm": round(top26_rerank_score_norm.get(number, 0.0), 6),
            "top26_suggestion_memory": round(_clamp(_safe_float(top26_detail.get("top26_suggestion_memory"), 0.0), 0.0, 1.5), 6),
            "top26_result_memory": round(_clamp(_safe_float(top26_detail.get("top26_result_memory"), 0.0), 0.0, 1.5), 6),
            "top26_regional_persistence": round(_clamp(_safe_float(top26_detail.get("top26_regional_persistence"), 0.0), 0.0, 1.5), 6),
            "top26_persistence": round(_clamp(_safe_float(top26_detail.get("top26_persistence"), 0.0), 0.0, 1.0), 6),
            "top26_volatility_penalty": round(_clamp(_safe_float(top26_detail.get("top26_volatility_penalty"), 0.0), 0.0, 1.0), 6),
            "time_rank_score": round(
                _position_score(_safe_int(time_detail.get("time_window_reranked_position"), suggestion_size), suggestion_size),
                6,
            ),
            "time_exact_prior": round(_clamp(_safe_float(time_detail.get("time_window_exact_prior"), 0.0), 0.0, 1.0), 6),
            "time_region_prior": round(_clamp(_safe_float(time_detail.get("time_window_region_prior"), 0.0), 0.0, 1.0), 6),
            "time_final_score_norm": round(time_final_score_norm.get(number, 0.0), 6),
            "history_similarity_1": round(_region_similarity(number, history_numbers[0], sigma=1.6), 6) if len(history_numbers) >= 1 else 0.0,
            "history_similarity_2": round(_region_similarity(number, history_numbers[1], sigma=1.85), 6) if len(history_numbers) >= 2 else 0.0,
            "history_similarity_3": round(_region_similarity(number, history_numbers[2], sigma=2.1), 6) if len(history_numbers) >= 3 else 0.0,
            "history_region_density": round(
                sum(_region_similarity(number, result_number, sigma=1.9) for result_number in history_numbers[:5]) / max(1, len(history_numbers[:5])),
                6,
            ) if history_numbers else 0.0,
            "history_exact_recent_flag": 1.0 if number in history_numbers[:5] else 0.0,
            "confidence_score": round(confidence_score, 6),
            "confidence_delta": round(confidence_delta, 6),
            "confidence_top_flag": 1.0 if latest_rank_band == "top" else 0.0,
            "confidence_middle_flag": 1.0 if latest_rank_band == "middle" else 0.0,
            "confidence_bottom_flag": 1.0 if latest_rank_band == "bottom" else 0.0,
            "rank_context_avg_ratio": round(_clamp(_safe_float(rank_context.get("avg_rank_ratio"), 0.0), 0.0, 1.0), 6),
            "rank_context_zigzag_rate": round(_clamp(_safe_float(rank_context.get("zigzag_rate"), 0.0), 0.0, 1.0), 6),
            "rank_context_worsening": round(_clamp(_safe_float(rank_context.get("worsening_strength"), 0.0), 0.0, 1.0), 6),
            "rank_context_improvement": round(_clamp(_safe_float(rank_context.get("improvement_strength"), 0.0), 0.0, 1.0), 6),
            "rank_context_top_share": round(_clamp(_safe_float(rank_context.get("top_band_share"), 0.0), 0.0, 1.0), 6),
            "rank_context_bottom_share": round(_clamp(_safe_float(rank_context.get("lower_band_share"), 0.0), 0.0, 1.0), 6),
        }

        heuristic_score = (
            (0.18 * feature_row["base_weighted_support_norm"])
            + (0.14 * feature_row["top26_rank_score"])
            + (0.14 * feature_row["top26_rerank_score_norm"])
            + (0.10 * feature_row["time_final_score_norm"])
            + (0.08 * feature_row["time_region_prior"])
            + (0.08 * feature_row["history_region_density"])
            + (0.07 * feature_row["base_dynamic_weight_avg_norm"])
            + (0.06 * feature_row["base_positive_pattern_share"])
            + (0.05 * feature_row["confidence_score"])
            + (0.05 * feature_row["confidence_bottom_flag"])
            + (0.03 * max(0.0, feature_row["confidence_delta"]))
            - (0.02 * feature_row["base_negative_pattern_share"])
            - (0.02 * feature_row["top26_volatility_penalty"])
        )
        heuristic_score = _clamp(heuristic_score, 0.0, 1.0)
        linear_score = bias + sum(_safe_float(weights.get(name), 0.0) * _safe_float(feature_row.get(name), 0.0) for name in feature_names)
        model_probability = _sigmoid(linear_score)
        warmup_factor = _clamp(
            _safe_float(normalized_state.get("trained_events"), 0.0) / max(1.0, _safe_float(normalized_state.get("warmup_events"), 18)),
            0.0,
            1.0,
        )
        model_blend = 0.25 + (0.5 * warmup_factor)
        final_score = (model_blend * model_probability) + ((1.0 - model_blend) * heuristic_score)
        candidate_features.append(
            {
                "number": int(number),
                "original_position": int(base_rank_position),
                "features": feature_row,
                "heuristic_score": round(heuristic_score, 6),
                "model_probability": round(model_probability, 6),
                "linear_score": round(linear_score, 6),
                "model_blend": round(model_blend, 6),
                "final_score": round(final_score, 6),
            }
        )

    candidate_features.sort(
        key=lambda item: (
            -_safe_float(item.get("final_score"), 0.0),
            -_safe_float(item.get("model_probability"), 0.0),
            -_safe_float(item.get("heuristic_score"), 0.0),
            _safe_int(item.get("original_position"), 999),
        )
    )

    reordered_details: List[Dict[str, Any]] = []
    for reranked_position, item in enumerate(candidate_features, start=1):
        number = int(item["number"])
        base_detail = dict(base_map.get(number) or {"number": number, "supporting_patterns": []})
        base_detail["original_rank_position"] = int(item["original_position"])
        base_detail["ml_meta_reranked_position"] = int(reranked_position)
        base_detail["ml_meta_probability"] = round(_safe_float(item.get("model_probability"), 0.0), 6)
        base_detail["ml_meta_linear_score"] = round(_safe_float(item.get("linear_score"), 0.0), 6)
        base_detail["ml_meta_heuristic_score"] = round(_safe_float(item.get("heuristic_score"), 0.0), 6)
        base_detail["ml_meta_model_blend"] = round(_safe_float(item.get("model_blend"), 0.0), 6)
        base_detail["ml_meta_final_score"] = round(_safe_float(item.get("final_score"), 0.0), 6)
        reordered_details.append(base_detail)

    reordered_suggestion = [int(item["number"]) for item in candidate_features]
    return {
        "available": bool(base_payload.get("available", False)),
        "list": reordered_suggestion,
        "suggestion": reordered_suggestion,
        "ordered_suggestion": reordered_suggestion,
        "pattern_count": int(base_payload.get("pattern_count") or 0),
        "unique_numbers": int(base_payload.get("unique_numbers") or len(reordered_suggestion)),
        "selected_number_details": reordered_details,
        "entry_shadow": dict(entry_shadow),
        "explanation": (
            "ML meta-ranker online aplicado em shadow. "
            f"trained_events={int(normalized_state.get('trained_events') or 0)} "
            f"warmup_events={int(normalized_state.get('warmup_events') or 0)} "
            f"feature_count={len(feature_names)}."
        ),
        "oscillation": {
            "profile": "ml_meta_rank_v1",
            "ml_meta_rank": {
                "model_name": "ml_meta_rank_v1",
                "model_version": ML_META_RANK_VERSION,
                "feature_names": feature_names,
                "candidate_features": candidate_features,
                "trained_events": int(normalized_state.get("trained_events") or 0),
                "trained_rows": int(normalized_state.get("trained_rows") or 0),
                "warmup_events": int(normalized_state.get("warmup_events") or 0),
                "learning_rate": round(_safe_float(normalized_state.get("learning_rate"), 0.0), 6),
                "positive_class_weight": round(_safe_float(normalized_state.get("positive_class_weight"), 0.0), 6),
                "negative_class_weight": round(_safe_float(normalized_state.get("negative_class_weight"), 0.0), 6),
                "l2_decay": round(_safe_float(normalized_state.get("l2_decay"), 0.0), 8),
                "top_weight_features": _top_weight_features(weights),
            },
        },
    }


def train_ml_meta_rank_state_from_resolved_event(
    model_state: Mapping[str, Any] | None,
    resolved_event_doc: Mapping[str, Any],
    *,
    roulette_id: str,
    config_key: str,
    epochs: int = 2,
) -> Dict[str, Any]:
    normalized_state = _normalize_model_state(model_state, roulette_id=roulette_id, config_key=config_key)
    oscillation = dict(resolved_event_doc.get("oscillation") or {}) if isinstance(resolved_event_doc.get("oscillation"), Mapping) else {}
    ml_meta_rank = dict(oscillation.get("ml_meta_rank") or {}) if isinstance(oscillation.get("ml_meta_rank"), Mapping) else {}
    candidate_features = [
        dict(item)
        for item in (ml_meta_rank.get("candidate_features") or [])
        if isinstance(item, Mapping) and _safe_int(item.get("number"), -1) >= 0
    ]
    resolved_number = _safe_int(resolved_event_doc.get("resolved_number"), -1)
    if resolved_number < 0 or not candidate_features:
        return normalized_state

    if not any(_safe_int(item.get("number"), -1) == resolved_number for item in candidate_features):
        return normalized_state

    weights = dict(normalized_state["weights"])
    bias = _safe_float(normalized_state.get("bias"), 0.0)
    learning_rate = max(0.0001, _safe_float(normalized_state.get("learning_rate"), 0.045))
    positive_class_weight = max(1.0, _safe_float(normalized_state.get("positive_class_weight"), 9.0))
    negative_class_weight = max(0.1, _safe_float(normalized_state.get("negative_class_weight"), 0.75))
    l2_decay = max(0.0, _safe_float(normalized_state.get("l2_decay"), 0.0008))
    feature_names = list(normalized_state["feature_names"])
    winner_first = sorted(
        candidate_features,
        key=lambda item: 0 if _safe_int(item.get("number"), -1) == resolved_number else 1,
    )

    trained_rows = 0
    for _ in range(max(1, int(epochs))):
        for candidate in winner_first:
            number = _safe_int(candidate.get("number"), -1)
            features = dict(candidate.get("features") or {})
            label = 1.0 if number == resolved_number else 0.0
            sample_weight = positive_class_weight if label > 0.5 else negative_class_weight
            linear_score = bias + sum(_safe_float(weights.get(name), 0.0) * _safe_float(features.get(name), 0.0) for name in feature_names)
            probability = _sigmoid(linear_score)
            error = label - probability
            bias = _clamp(bias + (learning_rate * sample_weight * error), -6.0, 6.0)
            for feature_name in feature_names:
                value = _safe_float(features.get(feature_name), 0.0)
                current_weight = _safe_float(weights.get(feature_name), 0.0)
                current_weight *= max(0.0, 1.0 - (learning_rate * l2_decay))
                current_weight += learning_rate * sample_weight * error * value
                weights[feature_name] = _clamp(current_weight, -6.0, 6.0)
            trained_rows += 1

    updated_state = dict(normalized_state)
    updated_state["weights"] = {name: round(_safe_float(weights.get(name), 0.0), 6) for name in feature_names}
    updated_state["bias"] = round(_safe_float(bias, 0.0), 6)
    updated_state["trained_events"] = int(normalized_state.get("trained_events") or 0) + 1
    updated_state["trained_rows"] = int(normalized_state.get("trained_rows") or 0) + trained_rows
    updated_state["last_train_event_id"] = str(resolved_event_doc.get("_id") or "").strip()
    updated_state["last_resolved_number"] = int(resolved_number)
    updated_state["last_winner_rank_before_update"] = _safe_int(resolved_event_doc.get("resolved_rank_position"), 0) or None
    updated_state["top_weight_features"] = _top_weight_features(updated_state["weights"])
    updated_state["updated_at"] = datetime.now(timezone.utc)
    return updated_state
