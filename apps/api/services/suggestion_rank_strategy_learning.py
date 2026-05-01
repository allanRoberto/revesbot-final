from __future__ import annotations

import heapq
import math
from collections import Counter
from typing import Any, Dict, List, Mapping

from api.services.suggestion_snapshot_service import (
    STRATEGY_OUTSIDE_RANK,
    build_suggestion_snapshot_rank_timeline,
)


RANK_STRATEGY_ACTIONS = ("normal", "inv_5", "inv_8", "inv_10")


def _invert_rank(rank: int | None, edge_size: int) -> int:
    if not isinstance(rank, int) or not (1 <= rank <= 37):
        return STRATEGY_OUTSIDE_RANK
    if edge_size <= 0:
        return int(rank)
    safe_edge_size = max(1, min(18, int(edge_size)))
    bottom_start = 38 - safe_edge_size
    if rank <= safe_edge_size or rank >= bottom_start:
        return 38 - rank
    return int(rank)


def _apply_action_to_rank(rank: int | None, action: str) -> int:
    if action == "inv_5":
        return _invert_rank(rank, 5)
    if action == "inv_8":
        return _invert_rank(rank, 8)
    if action == "inv_10":
        return _invert_rank(rank, 10)
    return int(rank) if isinstance(rank, int) and 1 <= rank <= 37 else STRATEGY_OUTSIDE_RANK


def _score_rank(rank: int, *, top_target: int) -> float:
    safe_rank = max(1, min(STRATEGY_OUTSIDE_RANK, int(rank)))
    inside_bonus = max(0, top_target + 1 - safe_rank) * 4.0
    position_score = float(39 - safe_rank)
    return inside_bonus + position_score


def _build_feature_payload(previous_ranks: List[int]) -> Dict[str, float]:
    lookback = len(previous_ranks)
    features: Dict[str, float] = {}
    for idx, rank in enumerate(previous_ranks, start=1):
        features[f"prev_{idx}"] = float(rank)

    deltas = []
    for idx in range(lookback - 1):
        delta = float(previous_ranks[idx] - previous_ranks[idx + 1])
        deltas.append(delta)
        features[f"delta_{idx + 1}"] = delta

    recent3 = previous_ranks[:3] if len(previous_ranks) >= 3 else previous_ranks[:]
    features["avg_prev"] = round(sum(previous_ranks) / len(previous_ranks), 4)
    features["avg_prev_3"] = round(sum(recent3) / len(recent3), 4) if recent3 else 0.0
    features["min_prev"] = float(min(previous_ranks)) if previous_ranks else 0.0
    features["max_prev"] = float(max(previous_ranks)) if previous_ranks else 0.0
    features["amplitude_prev"] = features["max_prev"] - features["min_prev"]
    features["momentum_short"] = float(previous_ranks[0] - previous_ranks[1]) if len(previous_ranks) >= 2 else 0.0
    features["momentum_long"] = float(previous_ranks[0] - previous_ranks[-1]) if previous_ranks else 0.0
    features["zigzag_energy"] = round(sum(abs(delta) for delta in deltas), 4)
    features["volatility_prev"] = round(
        math.sqrt(sum((rank - features["avg_prev"]) ** 2 for rank in previous_ranks) / len(previous_ranks)),
        4,
    ) if previous_ranks else 0.0
    return features


def _augment_features_with_snapshot_context(
    features: Dict[str, float],
    snapshot_context: Mapping[str, Any],
) -> Dict[str, float]:
    enriched = dict(features)
    context = dict(snapshot_context or {})
    enriched["ctx_confidence_score"] = float(context.get("confidence_score") or 0.0)
    enriched["ctx_optimized_confidence_score"] = float(context.get("optimized_confidence_score") or 0.0)
    enriched["ctx_signal_quality_score"] = float(context.get("signal_quality_score") or 0.0)
    enriched["ctx_simple_signal_quality_score"] = float(context.get("simple_signal_quality_score") or 0.0)
    enriched["ctx_simple_pattern_count"] = float(context.get("simple_pattern_count") or 0.0)
    enriched["ctx_simple_top_support_count"] = float(context.get("simple_top_support_count") or 0.0)
    enriched["ctx_simple_avg_support_count"] = float(context.get("simple_avg_support_count") or 0.0)
    enriched["ctx_simple_unique_numbers"] = float(context.get("simple_unique_numbers") or 0.0)
    enriched["ctx_occurrence_overlap_count"] = float(context.get("occurrence_overlap_count") or 0.0)
    enriched["ctx_occurrence_inverted_detected"] = 1.0 if bool(context.get("occurrence_inverted_detected")) else 0.0
    enriched["ctx_ranking_locked"] = 1.0 if bool(context.get("ranking_locked")) else 0.0
    enriched["ctx_top12_simple_overlap"] = float(context.get("top12_simple_overlap") or 0.0)
    enriched["ctx_top18_simple_overlap"] = float(context.get("top18_simple_overlap") or 0.0)
    enriched["ctx_top12_simple_overlap_ratio"] = float(context.get("top12_simple_overlap_ratio") or 0.0)
    enriched["ctx_top18_simple_overlap_ratio"] = float(context.get("top18_simple_overlap_ratio") or 0.0)
    enriched["ctx_confidence_gap"] = enriched["ctx_optimized_confidence_score"] - enriched["ctx_confidence_score"]
    enriched["ctx_quality_gap"] = enriched["ctx_signal_quality_score"] - enriched["ctx_simple_signal_quality_score"]
    return enriched


def _rank_bucket(rank: int) -> str:
    if rank >= STRATEGY_OUTSIDE_RANK:
        return "outside"
    if rank <= 5:
        return "top"
    if rank <= 12:
        return "upper"
    if rank <= 24:
        return "middle"
    if rank <= 31:
        return "lower"
    return "bottom"


def _delta_bucket(delta: int) -> str:
    if delta <= -10:
        return "jump_up"
    if delta <= -4:
        return "up"
    if delta >= 10:
        return "drop_down"
    if delta >= 4:
        return "down"
    return "flat"


def _volatility_bucket(previous_ranks: List[int]) -> str:
    if not previous_ranks:
        return "quiet"
    amplitude = max(previous_ranks) - min(previous_ranks)
    if amplitude >= 24:
        return "high"
    if amplitude >= 12:
        return "medium"
    return "low"


def _movement_phase(previous_ranks: List[int]) -> str:
    if len(previous_ranks) < 3:
        return "unknown"
    latest = int(previous_ranks[0])
    mid = int(previous_ranks[1])
    older = int(previous_ranks[2])
    d_recent = latest - mid
    d_previous = mid - older

    if d_previous <= -8 and d_recent >= 6:
        return "correction_after_spike"
    if d_previous >= 8 and d_recent >= 4:
        return "falling_continuation"
    if d_previous >= 6 and d_recent <= -6:
        return "rebound_after_fall"
    if d_previous <= -6 and d_recent <= -4:
        return "rising_continuation"
    if abs(d_previous) <= 3 and abs(d_recent) <= 3:
        return "flat"
    if d_previous * d_recent < 0:
        return "zigzag_reversal"
    return "drift"


def _build_regime_state(previous_ranks: List[int]) -> Dict[str, Any]:
    padded = list(previous_ranks[:3])
    while len(padded) < 3:
        padded.append(padded[-1] if padded else STRATEGY_OUTSIDE_RANK)
    latest = int(padded[0])
    mid = int(padded[1])
    older = int(padded[2])
    d_recent = latest - mid
    d_previous = mid - older
    latest_bucket = _rank_bucket(latest)
    recent_bucket = _delta_bucket(d_recent)
    previous_bucket = _delta_bucket(d_previous)
    volatility_bucket = _volatility_bucket(previous_ranks[:5])
    phase = _movement_phase(previous_ranks[:3])
    return {
        "latest_bucket": latest_bucket,
        "phase": phase,
        "recent_bucket": recent_bucket,
        "previous_bucket": previous_bucket,
        "volatility_bucket": volatility_bucket,
        "full": f"{latest_bucket}|{phase}|{recent_bucket}|{previous_bucket}|{volatility_bucket}",
        "simple": f"{latest_bucket}|{phase}|{recent_bucket}",
        "bucket_only": latest_bucket,
    }


def _score_bucket(score: float) -> str:
    safe_score = float(score or 0.0)
    if safe_score >= 80:
        return "high"
    if safe_score >= 65:
        return "mid"
    if safe_score >= 50:
        return "low"
    return "weak"


def _count_bucket(value: float, *, low: int, medium: int, high: int) -> str:
    safe_value = float(value or 0.0)
    if safe_value >= high:
        return "high"
    if safe_value >= medium:
        return "mid"
    if safe_value >= low:
        return "low"
    return "weak"


def _augment_regime_state_with_context(
    regime_state: Dict[str, Any],
    snapshot_context: Mapping[str, Any],
) -> Dict[str, Any]:
    enriched = dict(regime_state)
    context = dict(snapshot_context or {})
    quality_bucket = _score_bucket(float(context.get("signal_quality_score") or 0.0))
    confidence_bucket = _score_bucket(float(context.get("optimized_confidence_score") or 0.0))
    overlap_bucket = _count_bucket(float(context.get("occurrence_overlap_count") or 0.0), low=3, medium=8, high=14)
    support_bucket = _count_bucket(float(context.get("simple_top_support_count") or 0.0), low=5, medium=10, high=15)
    agreement_bucket = _count_bucket(float(context.get("top12_simple_overlap") or 0.0), low=3, medium=6, high=9)
    inversion_flag = "inv" if bool(context.get("occurrence_inverted_detected")) else "clean"

    enriched.update(
        {
            "quality_bucket": quality_bucket,
            "confidence_bucket": confidence_bucket,
            "overlap_bucket": overlap_bucket,
            "support_bucket": support_bucket,
            "agreement_bucket": agreement_bucket,
            "occurrence_flag": inversion_flag,
        }
    )
    enriched["full"] = (
        f"{regime_state['latest_bucket']}|{regime_state['phase']}|{regime_state['recent_bucket']}"
        f"|{regime_state['previous_bucket']}|{regime_state['volatility_bucket']}"
        f"|q:{quality_bucket}|c:{confidence_bucket}|o:{overlap_bucket}|s:{support_bucket}|a:{agreement_bucket}|{inversion_flag}"
    )
    enriched["simple"] = (
        f"{regime_state['latest_bucket']}|{regime_state['phase']}|{regime_state['recent_bucket']}"
        f"|q:{quality_bucket}|o:{overlap_bucket}|a:{agreement_bucket}"
    )
    return enriched


def _feature_keys_for_lookback(lookback: int) -> List[str]:
    keys: List[str] = [f"prev_{idx}" for idx in range(1, lookback + 1)]
    keys.extend(f"delta_{idx}" for idx in range(1, lookback))
    keys.extend(
        [
            "avg_prev",
            "avg_prev_3",
            "min_prev",
            "max_prev",
            "amplitude_prev",
            "momentum_short",
            "momentum_long",
            "zigzag_energy",
            "volatility_prev",
            "ctx_confidence_score",
            "ctx_optimized_confidence_score",
            "ctx_signal_quality_score",
            "ctx_simple_signal_quality_score",
            "ctx_simple_pattern_count",
            "ctx_simple_top_support_count",
            "ctx_simple_avg_support_count",
            "ctx_simple_unique_numbers",
            "ctx_occurrence_overlap_count",
            "ctx_occurrence_inverted_detected",
            "ctx_ranking_locked",
            "ctx_top12_simple_overlap",
            "ctx_top18_simple_overlap",
            "ctx_top12_simple_overlap_ratio",
            "ctx_top18_simple_overlap_ratio",
            "ctx_confidence_gap",
            "ctx_quality_gap",
        ]
    )
    return keys


def _build_feature_vector(features: Mapping[str, float], feature_keys: List[str]) -> List[float]:
    return [float(features.get(key, 0.0)) for key in feature_keys]


def _choose_best_action(action_ranks: Mapping[str, int], *, top_target: int) -> tuple[str, Dict[str, float]]:
    action_scores = {
        action: _score_rank(rank, top_target=top_target)
        for action, rank in action_ranks.items()
    }
    action_priority = {name: idx for idx, name in enumerate(RANK_STRATEGY_ACTIONS)}
    best_action = max(
        RANK_STRATEGY_ACTIONS,
        key=lambda action: (
            action_scores[action],
            -int(action_ranks[action]),
            -action_priority[action],
        ),
    )
    return best_action, action_scores


def _rank_metrics_from_ranks(ranks: List[int], *, top_target: int) -> Dict[str, Any]:
    signals = len(ranks)
    top_1 = sum(1 for rank in ranks if rank <= 1)
    top_5 = sum(1 for rank in ranks if rank <= 5)
    top_10 = sum(1 for rank in ranks if rank <= 10)
    top_target_hits = sum(1 for rank in ranks if rank <= top_target)
    outside = sum(1 for rank in ranks if rank >= STRATEGY_OUTSIDE_RANK)
    return {
        "signals": signals,
        "top_1_hits": top_1,
        "top_5_hits": top_5,
        "top_10_hits": top_10,
        f"top_{top_target}_hits": top_target_hits,
        "outside_ranking": outside,
        "hit_rate_percent": round((top_target_hits / signals) * 100.0, 2) if signals else 0.0,
        "avg_rank": round(sum(ranks) / signals, 2) if signals else None,
    }


def _new_regime_stats() -> Dict[str, Any]:
    return {
        "count": 0,
        "action_score_sums": {action: 0.0 for action in RANK_STRATEGY_ACTIONS},
        "action_rank_sums": {action: 0.0 for action in RANK_STRATEGY_ACTIONS},
    }


def _update_regime_stats(
    table: Dict[str, Dict[str, Any]],
    key: str,
    *,
    action_scores: Mapping[str, float],
    action_ranks: Mapping[str, int],
) -> None:
    stats = table.setdefault(key, _new_regime_stats())
    stats["count"] += 1
    for action in RANK_STRATEGY_ACTIONS:
        stats["action_score_sums"][action] += float(action_scores.get(action, 0.0))
        stats["action_rank_sums"][action] += float(action_ranks.get(action, STRATEGY_OUTSIDE_RANK))


def _predict_action_regime_model(
    *,
    full_table: Dict[str, Dict[str, Any]],
    simple_table: Dict[str, Dict[str, Any]],
    bucket_table: Dict[str, Dict[str, Any]],
    global_stats: Dict[str, Any],
    regime_state: Mapping[str, Any],
    min_support: int,
) -> Dict[str, Any]:
    candidates = [
        ("full", str(regime_state.get("full") or "")),
        ("simple", str(regime_state.get("simple") or "")),
        ("bucket_only", str(regime_state.get("bucket_only") or "")),
    ]
    selected_level = "global"
    selected_key = "global"
    selected_stats = global_stats
    threshold = max(1, int(min_support or 8))

    for level, key in candidates:
        source = (
            full_table if level == "full"
            else simple_table if level == "simple"
            else bucket_table
        )
        stats = source.get(key)
        if stats and int(stats.get("count") or 0) >= threshold:
            selected_level = level
            selected_key = key
            selected_stats = stats
            break

    count = max(1, int(selected_stats.get("count") or 0))
    expected_scores = {
        action: float(selected_stats["action_score_sums"][action]) / count
        for action in RANK_STRATEGY_ACTIONS
    }
    expected_ranks = {
        action: float(selected_stats["action_rank_sums"][action]) / count
        for action in RANK_STRATEGY_ACTIONS
    }
    action_priority = {name: idx for idx, name in enumerate(RANK_STRATEGY_ACTIONS)}
    predicted_action = max(
        RANK_STRATEGY_ACTIONS,
        key=lambda action: (
            expected_scores[action],
            -expected_ranks[action],
            -action_priority[action],
        ),
    )
    sorted_scores = sorted(
        ((action, expected_scores[action]) for action in RANK_STRATEGY_ACTIONS),
        key=lambda item: item[1],
        reverse=True,
    )
    best_action, best_score = sorted_scores[0]
    second_action, second_score = sorted_scores[1]
    normal_score = float(expected_scores["normal"])
    total_score = sum(max(0.0, float(score)) for _, score in sorted_scores)
    share = (best_score / total_score) if total_score > 0 else 0.0
    return {
        "predicted_action": predicted_action,
        "state_level": selected_level,
        "state_key": selected_key,
        "support": count,
        "expected_scores": {
            action: round(expected_scores[action], 4)
            for action in RANK_STRATEGY_ACTIONS
        },
        "expected_ranks": {
            action: round(expected_ranks[action], 4)
            for action in RANK_STRATEGY_ACTIONS
        },
        "confidence": {
            "best_action": best_action,
            "second_action": second_action,
            "best_score": round(best_score, 4),
            "second_score": round(second_score, 4),
            "normal_score": round(normal_score, 4),
            "margin_to_second": round(best_score - second_score, 4),
            "margin_vs_normal": round(best_score - normal_score, 4),
            "share": round(share, 4),
        },
    }


async def build_rank_strategy_dataset(
    *,
    roulette_id: str,
    limit: int = 1000,
    lookback: int = 6,
    top_target: int = 12,
    include_all_configs: bool = False,
) -> Dict[str, Any]:
    safe_limit = max(100, min(5000, int(limit or 1000)))
    safe_lookback = max(3, min(12, int(lookback or 6)))
    safe_top_target = max(1, min(37, int(top_target or 12)))
    feature_keys = _feature_keys_for_lookback(safe_lookback)

    timeline_payload = await build_suggestion_snapshot_rank_timeline(
        roulette_id=roulette_id,
        limit=safe_limit + safe_lookback + 5,
        include_all_configs=include_all_configs,
    )
    timeline_items = list(timeline_payload.get("items") or [])
    if len(timeline_items) <= safe_lookback:
        raise LookupError("Histórico insuficiente para montar dataset da estratégia.")

    observed_ranks = [
        int(item.get("hit_rank")) if isinstance(item.get("hit_rank"), int) else STRATEGY_OUTSIDE_RANK
        for item in timeline_items
    ]

    rows: List[Dict[str, Any]] = []
    best_action_distribution: Counter[str] = Counter()

    for index in range(safe_lookback, len(timeline_items)):
        item = timeline_items[index]
        previous_ranks = [int(observed_ranks[index - step]) for step in range(1, safe_lookback + 1)]
        current_rank = observed_ranks[index]
        features = _augment_features_with_snapshot_context(
            _build_feature_payload(previous_ranks),
            item.get("context") if isinstance(item.get("context"), Mapping) else {},
        )
        regime_state = _augment_regime_state_with_context(
            _build_regime_state(previous_ranks),
            item.get("context") if isinstance(item.get("context"), Mapping) else {},
        )
        action_ranks = {
            action: _apply_action_to_rank(current_rank, action)
            for action in RANK_STRATEGY_ACTIONS
        }
        best_action, action_scores = _choose_best_action(action_ranks, top_target=safe_top_target)
        best_action_distribution[best_action] += 1
        rows.append(
            {
                "row_index": len(rows),
                "timeline_index": index,
                "snapshot_id": str(item.get("snapshot_id") or ""),
                "anchor_history_id": str(item.get("anchor_history_id") or ""),
                "anchor_number": item.get("anchor_number"),
                "anchor_timestamp_utc": item.get("anchor_timestamp_utc"),
                "next_number": item.get("next_number"),
                "hit_rank": current_rank,
                "features": features,
                "feature_vector": _build_feature_vector(features, feature_keys),
                "regime_state": regime_state,
                "action_ranks": action_ranks,
                "action_scores": action_scores,
                "best_action": best_action,
            }
        )

    return {
        "available": True,
        "roulette_id": roulette_id,
        "limit": safe_limit,
        "lookback": safe_lookback,
        "top_target": safe_top_target,
        "include_all_configs": bool(include_all_configs),
        "summary": {
            "rows": len(rows),
            "best_action_distribution": dict(best_action_distribution),
            "feature_count": len(feature_keys),
        },
        "rows": rows,
    }


def _predict_action_knn(
    *,
    train_rows: List[Dict[str, Any]],
    current_vector: List[float],
    k_neighbors: int,
) -> Dict[str, Any]:
    distances: List[tuple[float, Dict[str, Any]]] = []
    for row in train_rows:
        row_vector = list(row.get("feature_vector") or [])
        squared = 0.0
        for current_value, train_value in zip(current_vector, row_vector):
            diff = current_value - train_value
            squared += diff * diff
        distance = math.sqrt(squared)
        distances.append((distance, row))

    nearest = heapq.nsmallest(
        max(1, min(int(k_neighbors or 15), len(distances))),
        distances,
        key=lambda item: item[0],
    )

    weighted_scores = {action: 0.0 for action in RANK_STRATEGY_ACTIONS}
    weighted_ranks = {action: 0.0 for action in RANK_STRATEGY_ACTIONS}
    total_weight = 0.0

    for distance, row in nearest:
        weight = 1.0 / (distance + 0.001)
        total_weight += weight
        action_scores = row.get("action_scores") or {}
        action_ranks = row.get("action_ranks") or {}
        for action in RANK_STRATEGY_ACTIONS:
            weighted_scores[action] += weight * float(action_scores.get(action, 0.0))
            weighted_ranks[action] += weight * float(action_ranks.get(action, STRATEGY_OUTSIDE_RANK))

    action_priority = {name: idx for idx, name in enumerate(RANK_STRATEGY_ACTIONS)}
    predicted_action = max(
        RANK_STRATEGY_ACTIONS,
        key=lambda action: (
            weighted_scores[action],
            -(weighted_ranks[action] / total_weight if total_weight else STRATEGY_OUTSIDE_RANK),
            -action_priority[action],
        ),
    )
    sorted_scores = sorted(
        ((action, weighted_scores[action]) for action in RANK_STRATEGY_ACTIONS),
        key=lambda item: item[1],
        reverse=True,
    )
    best_action, best_score = sorted_scores[0]
    second_action, second_score = sorted_scores[1]
    normal_score = float(weighted_scores["normal"])
    total_score = sum(max(0.0, float(score)) for _, score in sorted_scores)
    confidence_share = (best_score / total_score) if total_score > 0 else 0.0
    return {
        "predicted_action": predicted_action,
        "nearest_neighbors": len(nearest),
        "weighted_scores": {
            action: round(weighted_scores[action], 4)
            for action in RANK_STRATEGY_ACTIONS
        },
        "confidence": {
            "best_action": best_action,
            "second_action": second_action,
            "best_score": round(best_score, 4),
            "second_score": round(second_score, 4),
            "normal_score": round(normal_score, 4),
            "margin_to_second": round(best_score - second_score, 4),
            "margin_vs_normal": round(best_score - normal_score, 4),
            "share": round(confidence_share, 4),
        },
    }


def _resolve_action_with_confidence_fallback(
    *,
    predicted_action: str,
    neighbor_meta: Mapping[str, Any],
    min_margin_to_second: float,
    min_margin_vs_normal: float,
    min_share: float,
) -> Dict[str, Any]:
    confidence = dict(neighbor_meta.get("confidence") or {})
    best_action = str(confidence.get("best_action") or predicted_action)
    second_action = str(confidence.get("second_action") or "normal")
    margin_to_second = float(confidence.get("margin_to_second") or 0.0)
    margin_vs_normal = float(confidence.get("margin_vs_normal") or 0.0)
    share = float(confidence.get("share") or 0.0)

    resolved_action = predicted_action
    used_fallback = False
    fallback_reasons: List[str] = []

    if predicted_action != "normal":
        if margin_to_second < min_margin_to_second:
            used_fallback = True
            fallback_reasons.append(f"margin_to_second<{min_margin_to_second}")
        if margin_vs_normal < min_margin_vs_normal:
            used_fallback = True
            fallback_reasons.append(f"margin_vs_normal<{min_margin_vs_normal}")
        if share < min_share:
            used_fallback = True
            fallback_reasons.append(f"share<{min_share}")
        if used_fallback:
            resolved_action = "normal"

    return {
        "resolved_action": resolved_action,
        "used_fallback": used_fallback,
        "fallback_reason": ", ".join(fallback_reasons),
        "confidence_snapshot": {
            "best_action": best_action,
            "second_action": second_action,
            "margin_to_second": round(margin_to_second, 4),
            "margin_vs_normal": round(margin_vs_normal, 4),
            "share": round(share, 4),
        },
    }


async def simulate_rank_strategy_walkforward(
    *,
    roulette_id: str,
    limit: int = 1000,
    lookback: int = 6,
    top_target: int = 12,
    include_all_configs: bool = False,
    k_neighbors: int = 15,
    min_train_size: int = 80,
    sample_predictions: int = 25,
    confidence_margin_to_second: float = 3.0,
    confidence_margin_vs_normal: float = 1.0,
    confidence_share_min: float = 0.29,
) -> Dict[str, Any]:
    dataset = await build_rank_strategy_dataset(
        roulette_id=roulette_id,
        limit=limit,
        lookback=lookback,
        top_target=top_target,
        include_all_configs=include_all_configs,
    )
    rows = list(dataset.get("rows") or [])
    safe_min_train = max(30, min(500, int(min_train_size or 80)))
    if len(rows) <= safe_min_train:
        raise LookupError("Dataset insuficiente para simulação walk-forward.")

    predicted_ranks: List[int] = []
    predicted_actions: List[str] = []
    raw_predicted_actions: List[str] = []
    prediction_rows: List[Dict[str, Any]] = []
    fallback_count = 0

    baseline_ranks: Dict[str, List[int]] = {action: [] for action in RANK_STRATEGY_ACTIONS}

    for index in range(safe_min_train, len(rows)):
        train_rows = rows[:index]
        current_row = rows[index]
        prediction = _predict_action_knn(
            train_rows=train_rows,
            current_vector=list(current_row.get("feature_vector") or []),
            k_neighbors=k_neighbors,
        )
        raw_predicted_action = str(prediction["predicted_action"])
        resolved_prediction = _resolve_action_with_confidence_fallback(
            predicted_action=raw_predicted_action,
            neighbor_meta=prediction,
            min_margin_to_second=float(confidence_margin_to_second),
            min_margin_vs_normal=float(confidence_margin_vs_normal),
            min_share=float(confidence_share_min),
        )
        predicted_action = str(resolved_prediction["resolved_action"])
        raw_predicted_actions.append(raw_predicted_action)
        actual_rank = int((current_row.get("action_ranks") or {}).get(predicted_action, STRATEGY_OUTSIDE_RANK))
        if bool(resolved_prediction["used_fallback"]):
            fallback_count += 1
        predicted_actions.append(predicted_action)
        predicted_ranks.append(actual_rank)

        for action in RANK_STRATEGY_ACTIONS:
            baseline_ranks[action].append(
                int((current_row.get("action_ranks") or {}).get(action, STRATEGY_OUTSIDE_RANK))
            )

        prediction_rows.append(
            {
                "row_index": current_row.get("row_index"),
                "anchor_number": current_row.get("anchor_number"),
                "anchor_timestamp_utc": current_row.get("anchor_timestamp_utc"),
                "next_number": current_row.get("next_number"),
                "hit_rank": current_row.get("hit_rank"),
                "raw_predicted_action": raw_predicted_action,
                "predicted_action": predicted_action,
                "predicted_rank": actual_rank,
                "best_action": current_row.get("best_action"),
                "best_rank": int((current_row.get("action_ranks") or {}).get(current_row.get("best_action"), STRATEGY_OUTSIDE_RANK)),
                "neighbor_meta": prediction,
                "fallback_meta": resolved_prediction,
            }
        )

    action_distribution = dict(Counter(predicted_actions))
    raw_action_distribution = dict(Counter(raw_predicted_actions))
    baseline_metrics = {
        action: _rank_metrics_from_ranks(ranks, top_target=top_target)
        for action, ranks in baseline_ranks.items()
    }

    return {
        "available": True,
        "roulette_id": roulette_id,
        "limit": int(limit),
        "lookback": int(lookback),
        "top_target": int(top_target),
        "k_neighbors": int(k_neighbors),
        "min_train_size": safe_min_train,
        "dataset_summary": dataset.get("summary") or {},
        "model_metrics": {
            **_rank_metrics_from_ranks(predicted_ranks, top_target=top_target),
            "predicted_action_distribution": action_distribution,
            "raw_predicted_action_distribution": raw_action_distribution,
            "fallback_to_normal_count": fallback_count,
            "confidence_policy": {
                "margin_to_second_min": float(confidence_margin_to_second),
                "margin_vs_normal_min": float(confidence_margin_vs_normal),
                "share_min": float(confidence_share_min),
            },
        },
        "baseline_metrics": baseline_metrics,
        "recent_predictions": prediction_rows[-max(1, int(sample_predictions or 25)):],
    }


async def simulate_rank_strategy_regime_walkforward(
    *,
    roulette_id: str,
    limit: int = 1000,
    lookback: int = 6,
    top_target: int = 12,
    include_all_configs: bool = False,
    min_train_size: int = 80,
    sample_predictions: int = 25,
    regime_min_support: int = 8,
    confidence_margin_to_second: float = 2.0,
    confidence_margin_vs_normal: float = 0.5,
    confidence_share_min: float = 0.24,
) -> Dict[str, Any]:
    dataset = await build_rank_strategy_dataset(
        roulette_id=roulette_id,
        limit=limit,
        lookback=lookback,
        top_target=top_target,
        include_all_configs=include_all_configs,
    )
    rows = list(dataset.get("rows") or [])
    safe_min_train = max(30, min(500, int(min_train_size or 80)))
    if len(rows) <= safe_min_train:
        raise LookupError("Dataset insuficiente para simulação walk-forward por regimes.")

    full_table: Dict[str, Dict[str, Any]] = {}
    simple_table: Dict[str, Dict[str, Any]] = {}
    bucket_table: Dict[str, Dict[str, Any]] = {}
    global_stats = _new_regime_stats()

    for row in rows[:safe_min_train]:
        regime_state = dict(row.get("regime_state") or {})
        action_scores = dict(row.get("action_scores") or {})
        action_ranks = dict(row.get("action_ranks") or {})
        _update_regime_stats(full_table, str(regime_state.get("full") or ""), action_scores=action_scores, action_ranks=action_ranks)
        _update_regime_stats(simple_table, str(regime_state.get("simple") or ""), action_scores=action_scores, action_ranks=action_ranks)
        _update_regime_stats(bucket_table, str(regime_state.get("bucket_only") or ""), action_scores=action_scores, action_ranks=action_ranks)
        _update_regime_stats({"global": global_stats}, "global", action_scores=action_scores, action_ranks=action_ranks)

    predicted_ranks: List[int] = []
    predicted_actions: List[str] = []
    raw_predicted_actions: List[str] = []
    prediction_rows: List[Dict[str, Any]] = []
    fallback_count = 0

    baseline_ranks: Dict[str, List[int]] = {action: [] for action in RANK_STRATEGY_ACTIONS}
    state_level_distribution: Counter[str] = Counter()

    for index in range(safe_min_train, len(rows)):
        current_row = rows[index]
        regime_state = dict(current_row.get("regime_state") or {})
        prediction = _predict_action_regime_model(
            full_table=full_table,
            simple_table=simple_table,
            bucket_table=bucket_table,
            global_stats=global_stats,
            regime_state=regime_state,
            min_support=regime_min_support,
        )
        raw_predicted_action = str(prediction["predicted_action"])
        resolved_prediction = _resolve_action_with_confidence_fallback(
            predicted_action=raw_predicted_action,
            neighbor_meta=prediction,
            min_margin_to_second=float(confidence_margin_to_second),
            min_margin_vs_normal=float(confidence_margin_vs_normal),
            min_share=float(confidence_share_min),
        )
        predicted_action = str(resolved_prediction["resolved_action"])
        actual_rank = int((current_row.get("action_ranks") or {}).get(predicted_action, STRATEGY_OUTSIDE_RANK))

        raw_predicted_actions.append(raw_predicted_action)
        predicted_actions.append(predicted_action)
        predicted_ranks.append(actual_rank)
        state_level_distribution[str(prediction.get("state_level") or "global")] += 1
        if bool(resolved_prediction["used_fallback"]):
            fallback_count += 1

        for action in RANK_STRATEGY_ACTIONS:
            baseline_ranks[action].append(
                int((current_row.get("action_ranks") or {}).get(action, STRATEGY_OUTSIDE_RANK))
            )

        prediction_rows.append(
            {
                "row_index": current_row.get("row_index"),
                "anchor_number": current_row.get("anchor_number"),
                "anchor_timestamp_utc": current_row.get("anchor_timestamp_utc"),
                "next_number": current_row.get("next_number"),
                "hit_rank": current_row.get("hit_rank"),
                "regime_state": regime_state,
                "raw_predicted_action": raw_predicted_action,
                "predicted_action": predicted_action,
                "predicted_rank": actual_rank,
                "best_action": current_row.get("best_action"),
                "best_rank": int((current_row.get("action_ranks") or {}).get(current_row.get("best_action"), STRATEGY_OUTSIDE_RANK)),
                "regime_meta": prediction,
                "fallback_meta": resolved_prediction,
            }
        )

        action_scores = dict(current_row.get("action_scores") or {})
        action_ranks = dict(current_row.get("action_ranks") or {})
        _update_regime_stats(full_table, str(regime_state.get("full") or ""), action_scores=action_scores, action_ranks=action_ranks)
        _update_regime_stats(simple_table, str(regime_state.get("simple") or ""), action_scores=action_scores, action_ranks=action_ranks)
        _update_regime_stats(bucket_table, str(regime_state.get("bucket_only") or ""), action_scores=action_scores, action_ranks=action_ranks)
        _update_regime_stats({"global": global_stats}, "global", action_scores=action_scores, action_ranks=action_ranks)

    action_distribution = dict(Counter(predicted_actions))
    raw_action_distribution = dict(Counter(raw_predicted_actions))
    baseline_metrics = {
        action: _rank_metrics_from_ranks(ranks, top_target=top_target)
        for action, ranks in baseline_ranks.items()
    }

    return {
        "available": True,
        "model_type": "regime_transition_v1",
        "roulette_id": roulette_id,
        "limit": int(limit),
        "lookback": int(lookback),
        "top_target": int(top_target),
        "min_train_size": safe_min_train,
        "regime_min_support": int(regime_min_support),
        "dataset_summary": dataset.get("summary") or {},
        "model_metrics": {
            **_rank_metrics_from_ranks(predicted_ranks, top_target=top_target),
            "predicted_action_distribution": action_distribution,
            "raw_predicted_action_distribution": raw_action_distribution,
            "fallback_to_normal_count": fallback_count,
            "state_level_distribution": dict(state_level_distribution),
            "confidence_policy": {
                "margin_to_second_min": float(confidence_margin_to_second),
                "margin_vs_normal_min": float(confidence_margin_vs_normal),
                "share_min": float(confidence_share_min),
            },
        },
        "baseline_metrics": baseline_metrics,
        "recent_predictions": prediction_rows[-max(1, int(sample_predictions or 25)):],
    }
