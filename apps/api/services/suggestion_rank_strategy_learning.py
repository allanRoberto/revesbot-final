from __future__ import annotations

import heapq
import math
from collections import Counter
from typing import Any, Dict, List, Mapping

from api.core.db import suggestion_snapshots_coll
from api.services.suggestion_snapshot_service import (
    STRATEGY_OUTSIDE_RANK,
    _extract_snapshot_ranking,
    build_suggestion_snapshot_rank_timeline,
    build_suggestion_snapshot_config_key,
    get_or_create_global_suggestion_snapshot_config,
)


RANK_STRATEGY_ACTIONS = ("normal", "inv_5", "inv_8", "inv_10")
RANK_STRATEGY_FEATURE_MODES = ("movement_only", "contextual")
MOVEMENT_RANGE_DEFAULT_LOOKBACK = 12
MOVEMENT_RANGE_DEFAULT_SIZE = 18
MOVEMENT_RANGE_DEFAULT_ATTEMPTS = 3
MOVEMENT_RANGE_DEFAULT_NEIGHBORS = 15
MOVEMENT_RANGE_DEFAULT_MIN_TRAIN = 120


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


def _sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _count_direction_changes(deltas: List[float]) -> int:
    last_sign = 0
    changes = 0
    for delta in deltas:
        sign = _sign(delta)
        if sign == 0:
            continue
        if last_sign and sign != last_sign:
            changes += 1
        last_sign = sign
    return changes


def _build_movement_range_feature_payload(previous_ranks: List[int]) -> Dict[str, float]:
    safe_ranks = [int(rank) for rank in previous_ranks]
    lookback = len(safe_ranks)
    latest_rank = safe_ranks[0] if safe_ranks else STRATEGY_OUTSIDE_RANK
    deltas: List[float] = []
    features: Dict[str, float] = {}

    for idx, rank in enumerate(safe_ranks, start=1):
        features[f"prev_{idx}"] = float(rank)

    for idx in range(lookback - 1):
        delta = float(safe_ranks[idx] - safe_ranks[idx + 1])
        deltas.append(delta)
        features[f"delta_{idx + 1}"] = delta

    avg_prev = (sum(safe_ranks) / len(safe_ranks)) if safe_ranks else 0.0
    recent3 = safe_ranks[:3] if len(safe_ranks) >= 3 else safe_ranks[:]
    features["avg_prev"] = round(avg_prev, 4)
    features["avg_prev_3"] = round(sum(recent3) / len(recent3), 4) if recent3 else 0.0
    features["min_prev"] = float(min(safe_ranks)) if safe_ranks else 0.0
    features["max_prev"] = float(max(safe_ranks)) if safe_ranks else 0.0
    features["amplitude_prev"] = features["max_prev"] - features["min_prev"]
    features["momentum_short"] = float(safe_ranks[0] - safe_ranks[1]) if len(safe_ranks) >= 2 else 0.0
    features["momentum_long"] = float(safe_ranks[0] - safe_ranks[-1]) if safe_ranks else 0.0
    features["zigzag_energy"] = round(sum(abs(delta) for delta in deltas), 4)
    features["volatility_prev"] = round(
        math.sqrt(sum((rank - avg_prev) ** 2 for rank in safe_ranks) / len(safe_ranks)),
        4,
    ) if safe_ranks else 0.0
    features["direction_changes"] = float(_count_direction_changes(deltas))
    features["distance_to_top"] = float(max(0, latest_rank - 1))
    features["distance_to_bottom"] = float(max(0, 37 - min(37, latest_rank)))
    return features


def _movement_range_feature_keys(lookback: int) -> List[str]:
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
            "direction_changes",
            "distance_to_top",
            "distance_to_bottom",
        ]
    )
    return keys


def _coarse_rank_bucket(rank: int) -> str:
    safe_rank = int(rank)
    if safe_rank <= 12:
        return "top"
    if safe_rank <= 24:
        return "middle"
    return "bottom"


def _amplitude_bucket(amplitude: float) -> str:
    safe_amplitude = float(amplitude or 0.0)
    if safe_amplitude >= 24:
        return "high"
    if safe_amplitude >= 12:
        return "medium"
    return "low"


def _movement_similarity_signature(previous_ranks: List[int]) -> Dict[str, str]:
    safe = [int(rank) for rank in previous_ranks]
    deltas = [int(safe[idx] - safe[idx + 1]) for idx in range(min(len(safe) - 1, 3))]
    while len(deltas) < 3:
        deltas.append(0)
    latest_bucket = _coarse_rank_bucket(safe[0] if safe else STRATEGY_OUTSIDE_RANK)
    amp_bucket = _amplitude_bucket((max(safe) - min(safe)) if safe else 0.0)
    delta_tokens = [str(_sign(delta)) for delta in deltas]
    return {
        "full": f"{latest_bucket}|{'|'.join(delta_tokens)}|{amp_bucket}",
        "coarse": f"{latest_bucket}|{delta_tokens[0]}|{delta_tokens[1]}",
    }


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


def _feature_keys_for_mode(lookback: int, feature_mode: str) -> List[str]:
    base_keys: List[str] = [f"prev_{idx}" for idx in range(1, lookback + 1)]
    base_keys.extend(f"delta_{idx}" for idx in range(1, lookback))
    base_keys.extend(
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
        ]
    )
    if str(feature_mode or "movement_only") != "contextual":
        return base_keys
    return _feature_keys_for_lookback(lookback)


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
    feature_mode: str = "movement_only",
) -> Dict[str, Any]:
    safe_limit = max(100, min(5000, int(limit or 1000)))
    safe_lookback = max(3, min(12, int(lookback or 6)))
    safe_top_target = max(1, min(37, int(top_target or 12)))
    safe_feature_mode = (
        str(feature_mode or "movement_only")
        if str(feature_mode or "movement_only") in RANK_STRATEGY_FEATURE_MODES
        else "movement_only"
    )
    feature_keys = _feature_keys_for_mode(safe_lookback, safe_feature_mode)

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
        snapshot_context = item.get("context") if isinstance(item.get("context"), Mapping) else {}
        base_features = _build_feature_payload(previous_ranks)
        features = (
            _augment_features_with_snapshot_context(base_features, snapshot_context)
            if safe_feature_mode == "contextual"
            else base_features
        )
        base_regime_state = _build_regime_state(previous_ranks)
        regime_state = (
            _augment_regime_state_with_context(base_regime_state, snapshot_context)
            if safe_feature_mode == "contextual"
            else base_regime_state
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
        "feature_mode": safe_feature_mode,
        "include_all_configs": bool(include_all_configs),
        "summary": {
            "rows": len(rows),
            "best_action_distribution": dict(best_action_distribution),
            "feature_count": len(feature_keys),
            "feature_mode": safe_feature_mode,
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
    feature_mode: str = "movement_only",
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
        feature_mode=feature_mode,
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
        "feature_mode": str(dataset.get("feature_mode") or feature_mode),
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
    feature_mode: str = "movement_only",
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
        feature_mode=feature_mode,
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
        "feature_mode": str(dataset.get("feature_mode") or feature_mode),
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


async def compare_rank_strategy_models(
    *,
    roulette_id: str,
    limit: int = 300,
    lookback: int = 6,
    top_target: int = 12,
    include_all_configs: bool = False,
    feature_mode: str = "movement_only",
    min_train_size: int = 80,
    k_neighbors: int = 15,
    regime_min_support: int = 8,
    knn_confidence_margin_to_second: float = 3.0,
    knn_confidence_margin_vs_normal: float = 1.0,
    knn_confidence_share_min: float = 0.29,
    regime_confidence_margin_to_second: float = 2.0,
    regime_confidence_margin_vs_normal: float = 0.5,
    regime_confidence_share_min: float = 0.24,
) -> Dict[str, Any]:
    dataset = await build_rank_strategy_dataset(
        roulette_id=roulette_id,
        limit=limit,
        lookback=lookback,
        top_target=top_target,
        include_all_configs=include_all_configs,
        feature_mode=feature_mode,
    )
    rows = list(dataset.get("rows") or [])
    safe_min_train = max(30, min(500, int(min_train_size or 80)))
    if len(rows) <= safe_min_train:
        raise LookupError("Dataset insuficiente para comparar os modelos.")

    baseline_ranks: Dict[str, List[int]] = {action: [] for action in RANK_STRATEGY_ACTIONS}

    knn_ranks: List[int] = []
    knn_actions: List[str] = []
    knn_fallback = 0

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

    regime_ranks: List[int] = []
    regime_actions: List[str] = []
    regime_fallback = 0

    for index in range(safe_min_train, len(rows)):
        current_row = rows[index]
        current_action_ranks = dict(current_row.get("action_ranks") or {})

        knn_prediction = _predict_action_knn(
            train_rows=rows[:index],
            current_vector=list(current_row.get("feature_vector") or []),
            k_neighbors=k_neighbors,
        )
        knn_resolved = _resolve_action_with_confidence_fallback(
            predicted_action=str(knn_prediction["predicted_action"]),
            neighbor_meta=knn_prediction,
            min_margin_to_second=float(knn_confidence_margin_to_second),
            min_margin_vs_normal=float(knn_confidence_margin_vs_normal),
            min_share=float(knn_confidence_share_min),
        )
        knn_action = str(knn_resolved["resolved_action"])
        if bool(knn_resolved["used_fallback"]):
            knn_fallback += 1
        knn_actions.append(knn_action)
        knn_ranks.append(int(current_action_ranks.get(knn_action, STRATEGY_OUTSIDE_RANK)))

        regime_state = dict(current_row.get("regime_state") or {})
        regime_prediction = _predict_action_regime_model(
            full_table=full_table,
            simple_table=simple_table,
            bucket_table=bucket_table,
            global_stats=global_stats,
            regime_state=regime_state,
            min_support=regime_min_support,
        )
        regime_resolved = _resolve_action_with_confidence_fallback(
            predicted_action=str(regime_prediction["predicted_action"]),
            neighbor_meta=regime_prediction,
            min_margin_to_second=float(regime_confidence_margin_to_second),
            min_margin_vs_normal=float(regime_confidence_margin_vs_normal),
            min_share=float(regime_confidence_share_min),
        )
        regime_action = str(regime_resolved["resolved_action"])
        if bool(regime_resolved["used_fallback"]):
            regime_fallback += 1
        regime_actions.append(regime_action)
        regime_ranks.append(int(current_action_ranks.get(regime_action, STRATEGY_OUTSIDE_RANK)))

        for action in RANK_STRATEGY_ACTIONS:
            baseline_ranks[action].append(int(current_action_ranks.get(action, STRATEGY_OUTSIDE_RANK)))

        action_scores = dict(current_row.get("action_scores") or {})
        _update_regime_stats(full_table, str(regime_state.get("full") or ""), action_scores=action_scores, action_ranks=current_action_ranks)
        _update_regime_stats(simple_table, str(regime_state.get("simple") or ""), action_scores=action_scores, action_ranks=current_action_ranks)
        _update_regime_stats(bucket_table, str(regime_state.get("bucket_only") or ""), action_scores=action_scores, action_ranks=current_action_ranks)
        _update_regime_stats({"global": global_stats}, "global", action_scores=action_scores, action_ranks=current_action_ranks)

    baseline_metrics = {
        action: _rank_metrics_from_ranks(ranks, top_target=top_target)
        for action, ranks in baseline_ranks.items()
    }
    normal_metrics = dict(baseline_metrics.get("normal") or {})
    knn_metrics = {
        **_rank_metrics_from_ranks(knn_ranks, top_target=top_target),
        "predicted_action_distribution": dict(Counter(knn_actions)),
        "fallback_to_normal_count": knn_fallback,
    }
    regime_metrics = {
        **_rank_metrics_from_ranks(regime_ranks, top_target=top_target),
        "predicted_action_distribution": dict(Counter(regime_actions)),
        "fallback_to_normal_count": regime_fallback,
    }

    candidates = [
        ("normal", normal_metrics),
        ("knn_context", knn_metrics),
        ("regime", regime_metrics),
    ]
    recommended_name, recommended_metrics = max(
        candidates,
        key=lambda item: (
            float(item[1].get("hit_rate_percent") or 0.0),
            -float(item[1].get("avg_rank") or 999.0),
            1 if item[0] == "normal" else 0,
        ),
    )

    return {
        "available": True,
        "roulette_id": roulette_id,
        "limit": int(limit),
        "lookback": int(lookback),
        "top_target": int(top_target),
        "feature_mode": str(dataset.get("feature_mode") or feature_mode),
        "min_train_size": safe_min_train,
        "dataset_summary": dataset.get("summary") or {},
        "baseline_normal": normal_metrics,
        "knn_context": knn_metrics,
        "regime": regime_metrics,
        "baseline_metrics": baseline_metrics,
        "recommendation": {
            "name": recommended_name,
            "hit_rate_percent": float(recommended_metrics.get("hit_rate_percent") or 0.0),
            "avg_rank": recommended_metrics.get("avg_rank"),
        },
        "policies": {
            "knn_context": {
                "k_neighbors": int(k_neighbors),
                "margin_to_second_min": float(knn_confidence_margin_to_second),
                "margin_vs_normal_min": float(knn_confidence_margin_vs_normal),
                "share_min": float(knn_confidence_share_min),
            },
            "regime": {
                "min_support": int(regime_min_support),
                "margin_to_second_min": float(regime_confidence_margin_to_second),
                "margin_vs_normal_min": float(regime_confidence_margin_vs_normal),
                "share_min": float(regime_confidence_share_min),
            },
        },
    }


async def _load_full_rank_series_for_learning(
    *,
    roulette_id: str,
    include_all_configs: bool,
) -> List[Dict[str, Any]]:
    config_doc = await get_or_create_global_suggestion_snapshot_config()
    current_config_key = build_suggestion_snapshot_config_key(config_doc)

    snapshot_query: Dict[str, Any] = {"roulette_id": roulette_id}
    if not include_all_configs:
        snapshot_query["config_key"] = current_config_key

    projection = {
        "_id": 1,
        "snapshot_id": 1,
        "anchor_history_id": 1,
        "anchor_number": 1,
        "anchor_timestamp_utc": 1,
        "config_key": 1,
        "source": 1,
        "payload.suggestion": 1,
        "payload.list": 1,
        "payload.ordered_suggestion": 1,
        "payload.base_suggestion": 1,
        "payload.simple_suggestion": 1,
    }
    cursor = (
        suggestion_snapshots_coll.find(snapshot_query, projection)
        .sort("anchor_timestamp_utc", 1)
        .batch_size(1000)
    )
    snapshot_docs = [dict(doc) async for doc in cursor]
    if not snapshot_docs:
        raise LookupError("Nenhum snapshot encontrado para a roleta informada.")
    series: List[Dict[str, Any]] = []

    for idx, snapshot_doc in enumerate(snapshot_docs[:-1]):
        if not isinstance(snapshot_doc, Mapping):
            continue
        next_snapshot = snapshot_docs[idx + 1]
        if not isinstance(next_snapshot, Mapping):
            continue
        ranking = _extract_snapshot_ranking(snapshot_doc)
        if not ranking:
            continue
        next_number_raw = next_snapshot.get("anchor_number")
        try:
            next_number = int(next_number_raw)
        except Exception:
            continue

        hit_rank = (ranking.index(next_number) + 1) if next_number in ranking else None
        observed_rank = int(hit_rank) if isinstance(hit_rank, int) else STRATEGY_OUTSIDE_RANK
        series.append(
            {
                "snapshot_id": str(snapshot_doc.get("snapshot_id") or snapshot_doc.get("_id") or ""),
                "anchor_history_id": str(snapshot_doc.get("anchor_history_id") or ""),
                "anchor_number": snapshot_doc.get("anchor_number"),
                "anchor_timestamp_utc": snapshot_doc.get("anchor_timestamp_utc"),
                "next_number": next_number,
                "observed_rank": observed_rank,
                "hit_rank": hit_rank,
                "config_key": str(snapshot_doc.get("config_key") or ""),
                "source": str(snapshot_doc.get("source") or ""),
            }
        )

    if len(series) <= MOVEMENT_RANGE_DEFAULT_LOOKBACK + MOVEMENT_RANGE_DEFAULT_ATTEMPTS:
        raise LookupError("Série insuficiente para treinar o modelo de faixa.")
    return series


def _resolve_best_neighbor_window(
    nearest_rows: List[tuple[float, Dict[str, Any]]],
    *,
    range_size: int,
) -> Dict[str, Any]:
    safe_range_size = max(1, min(37, int(range_size or MOVEMENT_RANGE_DEFAULT_SIZE)))
    max_start = max(1, 37 - safe_range_size + 1)
    total_weight = 0.0
    direction_weights = {-1: 0.0, 0: 0.0, 1: 0.0}
    weighted_neighbors: List[Dict[str, Any]] = []

    for distance, row in nearest_rows:
        weight = 1.0 / (float(distance) + 0.001)
        total_weight += weight
        latest_rank = int((row.get("previous_ranks") or [STRATEGY_OUTSIDE_RANK])[0])
        first_future_rank = int((row.get("future_ranks") or [STRATEGY_OUTSIDE_RANK])[0])
        direction_weights[_sign(first_future_rank - latest_rank)] += weight
        weighted_neighbors.append(
            {
                "weight": weight,
                "future_ranks": [int(rank) for rank in (row.get("future_ranks") or [])],
            }
        )

    dominant_direction = max(direction_weights.items(), key=lambda item: item[1])[0]
    direction_consistency = (direction_weights[dominant_direction] / total_weight) if total_weight else 0.0

    best_payload = {
        "start": 1,
        "end": safe_range_size,
        "center": round((1 + safe_range_size) / 2.0, 2),
        "coverage_ratio": 0.0,
        "concentration_score": 0.0,
        "confidence": 0.0,
    }

    for start in range(1, max_start + 1):
        end = start + safe_range_size - 1
        center = (start + end) / 2.0
        covered_weight = 0.0
        covered_distance = 0.0

        for neighbor in weighted_neighbors:
            future_hits = [rank for rank in neighbor["future_ranks"] if start <= rank <= end]
            if not future_hits:
                continue
            covered_weight += float(neighbor["weight"])
            covered_distance += float(neighbor["weight"]) * min(abs(rank - center) for rank in future_hits)

        coverage_ratio = (covered_weight / total_weight) if total_weight else 0.0
        if covered_weight > 0:
            avg_distance = covered_distance / covered_weight
            concentration_score = 1.0 - min(1.0, avg_distance / max(1.0, (safe_range_size - 1) / 2.0))
        else:
            concentration_score = 0.0

        confidence = (
            (coverage_ratio * 0.5)
            + (concentration_score * 0.3)
            + (direction_consistency * 0.2)
        )

        current_payload = {
            "start": start,
            "end": end,
            "center": round(center, 2),
            "coverage_ratio": round(coverage_ratio, 4),
            "concentration_score": round(concentration_score, 4),
            "confidence": round(confidence, 4),
        }
        if (
            current_payload["coverage_ratio"] > best_payload["coverage_ratio"]
            or (
                abs(current_payload["coverage_ratio"] - best_payload["coverage_ratio"]) < 1e-9
                and current_payload["concentration_score"] > best_payload["concentration_score"]
            )
            or (
                abs(current_payload["coverage_ratio"] - best_payload["coverage_ratio"]) < 1e-9
                and abs(current_payload["concentration_score"] - best_payload["concentration_score"]) < 1e-9
                and current_payload["confidence"] > best_payload["confidence"]
            )
        ):
            best_payload = current_payload

    best_payload.update(
        {
            "range_size": safe_range_size,
            "support": len(nearest_rows),
            "direction_consistency": round(direction_consistency, 4),
            "expected_direction": (
                "subida" if dominant_direction < 0 else "queda" if dominant_direction > 0 else "indefinida"
            ),
        }
    )
    return best_payload


def _predict_next_range_from_movement(
    *,
    train_rows: List[Dict[str, Any]],
    current_row: Dict[str, Any],
    range_size: int,
    k_neighbors: int,
    confidence_threshold: float,
    coverage_threshold: float,
    support_threshold: int,
) -> Dict[str, Any]:
    current_vector = list(current_row.get("feature_vector") or [])
    current_signature = dict(current_row.get("similarity_signature") or {})
    candidate_rows = train_rows
    if current_signature:
        full_matches = [
            row for row in train_rows
            if dict(row.get("similarity_signature") or {}).get("full") == current_signature.get("full")
        ]
        coarse_matches = [
            row for row in train_rows
            if dict(row.get("similarity_signature") or {}).get("coarse") == current_signature.get("coarse")
        ]
        safe_min_candidates = max(40, int(k_neighbors or MOVEMENT_RANGE_DEFAULT_NEIGHBORS) * 3)
        if len(full_matches) >= safe_min_candidates:
            candidate_rows = full_matches
        elif len(coarse_matches) >= safe_min_candidates:
            candidate_rows = coarse_matches

    distances: List[tuple[float, Dict[str, Any]]] = []
    for row in candidate_rows:
        row_vector = list(row.get("feature_vector") or [])
        squared = 0.0
        for current_value, train_value in zip(current_vector, row_vector):
            diff = current_value - train_value
            squared += diff * diff
        distances.append((math.sqrt(squared), row))

    nearest = heapq.nsmallest(
        max(1, min(int(k_neighbors or MOVEMENT_RANGE_DEFAULT_NEIGHBORS), len(distances))),
        distances,
        key=lambda item: item[0],
    )
    range_payload = _resolve_best_neighbor_window(nearest, range_size=range_size)
    bettable = (
        float(range_payload["confidence"]) >= float(confidence_threshold)
        and float(range_payload["coverage_ratio"]) >= float(coverage_threshold)
        and int(range_payload["support"]) >= int(support_threshold)
    )
    return {
        **range_payload,
        "bettable": bool(bettable),
        "neighbors": len(nearest),
        "candidate_pool_size": len(candidate_rows),
    }


async def build_movement_range_dataset(
    *,
    roulette_id: str,
    lookback: int = MOVEMENT_RANGE_DEFAULT_LOOKBACK,
    future_attempts: int = MOVEMENT_RANGE_DEFAULT_ATTEMPTS,
    include_all_configs: bool = True,
) -> Dict[str, Any]:
    safe_lookback = max(4, min(20, int(lookback or MOVEMENT_RANGE_DEFAULT_LOOKBACK)))
    safe_future_attempts = max(1, min(5, int(future_attempts or MOVEMENT_RANGE_DEFAULT_ATTEMPTS)))
    feature_keys = _movement_range_feature_keys(safe_lookback)
    series = await _load_full_rank_series_for_learning(
        roulette_id=roulette_id,
        include_all_configs=bool(include_all_configs),
    )

    rows: List[Dict[str, Any]] = []
    for end_index in range(safe_lookback - 1, len(series) - safe_future_attempts):
        previous_ranks = [int(series[end_index - step]["observed_rank"]) for step in range(0, safe_lookback)]
        future_ranks = [int(series[end_index + step]["observed_rank"]) for step in range(1, safe_future_attempts + 1)]
        features = _build_movement_range_feature_payload(previous_ranks)
        feature_vector = [float(features.get(key, 0.0)) for key in feature_keys]
        base_row = dict(series[end_index])
        rows.append(
            {
                "row_index": len(rows),
                "series_index": end_index,
                "snapshot_id": base_row.get("snapshot_id"),
                "anchor_history_id": base_row.get("anchor_history_id"),
                "anchor_number": base_row.get("anchor_number"),
                "anchor_timestamp_utc": base_row.get("anchor_timestamp_utc"),
                "next_number": base_row.get("next_number"),
                "current_rank": int(base_row.get("observed_rank")),
                "previous_ranks": previous_ranks,
                "future_ranks": future_ranks,
                "similarity_signature": _movement_similarity_signature(previous_ranks),
                "features": features,
                "feature_vector": feature_vector,
            }
        )

    if len(rows) <= safe_lookback:
        raise LookupError("Dataset insuficiente para o modelo de faixa.")

    return {
        "available": True,
        "roulette_id": roulette_id,
        "lookback": safe_lookback,
        "future_attempts": safe_future_attempts,
        "include_all_configs": bool(include_all_configs),
        "summary": {
            "rows": len(rows),
            "feature_count": len(feature_keys),
            "series_points": len(series),
        },
        "rows": rows,
    }


async def simulate_movement_range_walkforward(
    *,
    roulette_id: str,
    lookback: int = MOVEMENT_RANGE_DEFAULT_LOOKBACK,
    range_size: int = MOVEMENT_RANGE_DEFAULT_SIZE,
    future_attempts: int = MOVEMENT_RANGE_DEFAULT_ATTEMPTS,
    include_all_configs: bool = True,
    k_neighbors: int = MOVEMENT_RANGE_DEFAULT_NEIGHBORS,
    min_train_size: int = MOVEMENT_RANGE_DEFAULT_MIN_TRAIN,
    confidence_threshold: float = 0.62,
    coverage_threshold: float = 0.58,
    concentration_threshold: float = 0.0,
    direction_consistency_threshold: float = 0.0,
    middle_overlap_max: float = 1.0,
    support_threshold: int = 12,
    sample_predictions: int = 25,
) -> Dict[str, Any]:
    dataset = await build_movement_range_dataset(
        roulette_id=roulette_id,
        lookback=lookback,
        future_attempts=future_attempts,
        include_all_configs=include_all_configs,
    )
    rows = list(dataset.get("rows") or [])
    safe_min_train = max(40, min(1000, int(min_train_size or MOVEMENT_RANGE_DEFAULT_MIN_TRAIN)))
    if len(rows) <= safe_min_train:
        raise LookupError("Dataset insuficiente para treinar o modelo de faixa.")

    prediction_rows = _build_movement_range_prediction_rows(
        rows=rows,
        range_size=range_size,
        k_neighbors=k_neighbors,
        min_train_size=safe_min_train,
    )
    metrics = _evaluate_movement_range_policy(
        prediction_rows=prediction_rows,
        confidence_threshold=confidence_threshold,
        coverage_threshold=coverage_threshold,
        concentration_threshold=concentration_threshold,
        direction_consistency_threshold=direction_consistency_threshold,
        middle_overlap_max=middle_overlap_max,
        support_threshold=support_threshold,
    )

    return {
        "available": True,
        "model_type": "movement_range_knn_v1",
        "roulette_id": roulette_id,
        "lookback": int(lookback),
        "range_size": int(range_size),
        "future_attempts": int(future_attempts),
        "include_all_configs": bool(include_all_configs),
        "k_neighbors": int(k_neighbors),
        "min_train_size": safe_min_train,
        "dataset_summary": dataset.get("summary") or {},
        "model_metrics": {
            **metrics,
            "policy": {
                "confidence_threshold": float(confidence_threshold),
                "coverage_threshold": float(coverage_threshold),
                "concentration_threshold": float(concentration_threshold),
                "direction_consistency_threshold": float(direction_consistency_threshold),
                "middle_overlap_max": float(middle_overlap_max),
                "support_threshold": int(support_threshold),
            },
        },
        "recent_predictions": prediction_rows[-max(1, int(sample_predictions or 25)):],
    }


def _build_movement_range_prediction_rows(
    *,
    rows: List[Dict[str, Any]],
    range_size: int,
    k_neighbors: int,
    min_train_size: int,
) -> List[Dict[str, Any]]:
    prediction_rows: List[Dict[str, Any]] = []
    safe_min_train = max(40, int(min_train_size or MOVEMENT_RANGE_DEFAULT_MIN_TRAIN))
    for index in range(safe_min_train, len(rows)):
        current_row = rows[index]
        prediction = _predict_next_range_from_movement(
            train_rows=rows[:index],
            current_row=current_row,
            range_size=range_size,
            k_neighbors=k_neighbors,
            confidence_threshold=0.0,
            coverage_threshold=0.0,
            support_threshold=1,
        )
        future_ranks = [int(rank) for rank in (current_row.get("future_ranks") or [])]
        hit_in_3_attempts = any(
            int(prediction["start"]) <= rank <= int(prediction["end"])
            for rank in future_ranks
        )
        prediction_rows.append(
            {
                "row_index": current_row.get("row_index"),
                "anchor_number": current_row.get("anchor_number"),
                "anchor_timestamp_utc": current_row.get("anchor_timestamp_utc"),
                "current_rank": current_row.get("current_rank"),
                "previous_ranks": current_row.get("previous_ranks"),
                "future_ranks": future_ranks,
                "predicted_range": {
                    "start": int(prediction["start"]),
                    "end": int(prediction["end"]),
                    "size": int(prediction["range_size"]),
                },
                "range_center": round((int(prediction["start"]) + int(prediction["end"])) / 2.0, 2),
                "confidence": float(prediction["confidence"]),
                "support": int(prediction["support"]),
                "candidate_pool_size": int(prediction.get("candidate_pool_size") or 0),
                "coverage_ratio": float(prediction["coverage_ratio"]),
                "concentration_score": float(prediction["concentration_score"]),
                "direction_consistency": float(prediction["direction_consistency"]),
                "middle_overlap_ratio": round(
                    max(0, min(int(prediction["end"]), 25) - max(int(prediction["start"]), 13) + 1)
                    / max(1, int(prediction["range_size"])),
                    4,
                ),
                "expected_direction": str(prediction["expected_direction"]),
                "bettable": True,
                "hit_in_3_attempts": bool(hit_in_3_attempts),
            }
        )
    return prediction_rows


def _evaluate_movement_range_policy(
    *,
    prediction_rows: List[Dict[str, Any]],
    confidence_threshold: float,
    coverage_threshold: float,
    concentration_threshold: float,
    direction_consistency_threshold: float,
    middle_overlap_max: float,
    support_threshold: int,
) -> Dict[str, Any]:
    total_signals = len(prediction_rows)
    total_hits = sum(1 for row in prediction_rows if bool(row.get("hit_in_3_attempts")))
    bettable_signals = 0
    bettable_hits = 0
    no_bet_signals = 0
    confidence_hits: List[float] = []
    confidence_misses: List[float] = []
    direction_distribution: Counter[str] = Counter()

    for row in prediction_rows:
        bettable = (
            float(row.get("confidence") or 0.0) >= float(confidence_threshold)
            and float(row.get("coverage_ratio") or 0.0) >= float(coverage_threshold)
            and float(row.get("concentration_score") or 0.0) >= float(concentration_threshold)
            and float(row.get("direction_consistency") or 0.0) >= float(direction_consistency_threshold)
            and float(row.get("middle_overlap_ratio") or 0.0) <= float(middle_overlap_max)
            and int(row.get("support") or 0) >= int(support_threshold)
        )
        row["bettable"] = bool(bettable)
        if bool(row.get("hit_in_3_attempts")):
            confidence_hits.append(float(row.get("confidence") or 0.0))
        else:
            confidence_misses.append(float(row.get("confidence") or 0.0))

        if bettable:
            bettable_signals += 1
            if bool(row.get("hit_in_3_attempts")):
                bettable_hits += 1
            direction_distribution[str(row.get("expected_direction") or "indefinida")] += 1
        else:
            no_bet_signals += 1

    return {
        "signals": total_signals,
        "hits_in_3_attempts_all": total_hits,
        "hit_rate_all_percent": round((total_hits / total_signals) * 100.0, 2) if total_signals else 0.0,
        "bettable_signals": bettable_signals,
        "hits_in_3_attempts_bettable": bettable_hits,
        "hit_rate_bettable_percent": round((bettable_hits / bettable_signals) * 100.0, 2) if bettable_signals else 0.0,
        "no_bet_signals": no_bet_signals,
        "no_bet_rate_percent": round((no_bet_signals / total_signals) * 100.0, 2) if total_signals else 0.0,
        "avg_confidence_hit": round(sum(confidence_hits) / len(confidence_hits), 4) if confidence_hits else None,
        "avg_confidence_miss": round(sum(confidence_misses) / len(confidence_misses), 4) if confidence_misses else None,
        "direction_distribution": dict(direction_distribution),
    }


async def train_movement_range_bet_policy(
    *,
    roulette_id: str,
    lookback: int = MOVEMENT_RANGE_DEFAULT_LOOKBACK,
    range_size: int = MOVEMENT_RANGE_DEFAULT_SIZE,
    future_attempts: int = MOVEMENT_RANGE_DEFAULT_ATTEMPTS,
    include_all_configs: bool = True,
    k_neighbors: int = MOVEMENT_RANGE_DEFAULT_NEIGHBORS,
    min_train_size: int = MOVEMENT_RANGE_DEFAULT_MIN_TRAIN,
    train_split_ratio: float = 0.7,
    min_active_rate: float = 0.08,
    sample_predictions: int = 25,
) -> Dict[str, Any]:
    dataset = await build_movement_range_dataset(
        roulette_id=roulette_id,
        lookback=lookback,
        future_attempts=future_attempts,
        include_all_configs=include_all_configs,
    )
    rows = list(dataset.get("rows") or [])
    safe_min_train = max(40, min(1000, int(min_train_size or MOVEMENT_RANGE_DEFAULT_MIN_TRAIN)))
    if len(rows) <= safe_min_train:
        raise LookupError("Dataset insuficiente para treinar a política de aposta.")

    prediction_rows = _build_movement_range_prediction_rows(
        rows=rows,
        range_size=range_size,
        k_neighbors=k_neighbors,
        min_train_size=safe_min_train,
    )
    if len(prediction_rows) < 200:
        raise LookupError("Predições insuficientes para treinar a política de aposta.")

    safe_split_ratio = max(0.55, min(0.9, float(train_split_ratio or 0.7)))
    split_index = max(100, min(len(prediction_rows) - 50, int(len(prediction_rows) * safe_split_ratio)))
    train_rows = [dict(row) for row in prediction_rows[:split_index]]
    validation_rows = [dict(row) for row in prediction_rows[split_index:]]
    if not validation_rows:
        raise LookupError("Conjunto de validação insuficiente para a política de aposta.")

    confidence_options = [0.72, 0.76, 0.8, 0.84, 0.88, 0.9]
    coverage_options = [0.76, 0.8, 0.84, 0.88, 0.92]
    concentration_options = [0.2, 0.28, 0.36, 0.44, 0.52, 0.6]
    direction_options = [0.5, 0.6, 0.7, 0.8, 0.9]
    middle_overlap_options = [0.72, 0.66, 0.61, 0.55, 0.5, 0.44]
    support_options = [10, 12, 15, 18, 22]
    safe_min_active_rate = max(0.05, min(0.8, float(min_active_rate or 0.2)))

    best_policy: Dict[str, Any] | None = None
    best_train_metrics: Dict[str, Any] | None = None
    best_score = -1.0

    for confidence_threshold in confidence_options:
        for coverage_threshold in coverage_options:
            for concentration_threshold in concentration_options:
                for direction_consistency_threshold in direction_options:
                    for middle_overlap_max in middle_overlap_options:
                        for support_threshold in support_options:
                            trial_rows = [dict(row) for row in train_rows]
                            metrics = _evaluate_movement_range_policy(
                                prediction_rows=trial_rows,
                                confidence_threshold=confidence_threshold,
                                coverage_threshold=coverage_threshold,
                                concentration_threshold=concentration_threshold,
                                direction_consistency_threshold=direction_consistency_threshold,
                                middle_overlap_max=middle_overlap_max,
                                support_threshold=support_threshold,
                            )
                            active_rate = (metrics["bettable_signals"] / metrics["signals"]) if metrics["signals"] else 0.0
                            if active_rate < safe_min_active_rate or metrics["bettable_signals"] < 50:
                                continue
                            score = (
                                float(metrics["hit_rate_bettable_percent"])
                                + (active_rate * 4.0)
                                - (float(metrics["no_bet_rate_percent"]) * 0.01)
                            )
                            if (
                                score > best_score
                                or (
                                    abs(score - best_score) < 1e-9
                                    and metrics["hit_rate_bettable_percent"] > (best_train_metrics or {}).get("hit_rate_bettable_percent", -1.0)
                                )
                            ):
                                best_score = score
                                best_policy = {
                                    "confidence_threshold": confidence_threshold,
                                    "coverage_threshold": coverage_threshold,
                                    "concentration_threshold": concentration_threshold,
                                    "direction_consistency_threshold": direction_consistency_threshold,
                                    "middle_overlap_max": middle_overlap_max,
                                    "support_threshold": support_threshold,
                                }
                                best_train_metrics = metrics

    if not best_policy or not best_train_metrics:
        raise LookupError("Não foi possível encontrar uma política de aposta válida com os dados atuais.")

    validation_eval_rows = [dict(row) for row in validation_rows]
    validation_metrics = _evaluate_movement_range_policy(
        prediction_rows=validation_eval_rows,
        confidence_threshold=float(best_policy["confidence_threshold"]),
        coverage_threshold=float(best_policy["coverage_threshold"]),
        concentration_threshold=float(best_policy["concentration_threshold"]),
        direction_consistency_threshold=float(best_policy["direction_consistency_threshold"]),
        middle_overlap_max=float(best_policy["middle_overlap_max"]),
        support_threshold=int(best_policy["support_threshold"]),
    )

    return {
        "available": True,
        "model_type": "movement_range_knn_v1_policy",
        "roulette_id": roulette_id,
        "lookback": int(lookback),
        "range_size": int(range_size),
        "future_attempts": int(future_attempts),
        "include_all_configs": bool(include_all_configs),
        "k_neighbors": int(k_neighbors),
        "min_train_size": safe_min_train,
        "dataset_summary": dataset.get("summary") or {},
        "policy_training": {
            "train_split_ratio": safe_split_ratio,
            "min_active_rate": safe_min_active_rate,
            "best_score": round(best_score, 4),
            "policy": best_policy,
        },
        "train_metrics": best_train_metrics,
        "validation_metrics": validation_metrics,
        "recent_validation_predictions": validation_eval_rows[-max(1, int(sample_predictions or 25)):],
    }
