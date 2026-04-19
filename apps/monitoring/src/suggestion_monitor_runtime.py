from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha1
from math import exp
from statistics import mean
from typing import Any, Dict, Iterable, List, Mapping
from zoneinfo import ZoneInfo

from api.services.base_suggestion import WHEEL_INDEX, WHEEL_ORDER


BR_TZ = ZoneInfo("America/Sao_Paulo")


def ensure_utc_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    raise TypeError(f"timestamp invalido: {type(value)!r}")


def build_time_fields(prefix: str, value: datetime) -> Dict[str, Any]:
    utc_value = ensure_utc_datetime(value)
    br_value = utc_value.astimezone(BR_TZ)
    return {
        f"{prefix}_timestamp_utc": utc_value,
        f"{prefix}_timestamp_br": br_value,
        f"{prefix}_date_br": br_value.strftime("%Y-%m-%d"),
        f"{prefix}_time_br": br_value.strftime("%H:%M:%S"),
        f"{prefix}_hour_br": int(br_value.hour),
        f"{prefix}_minute_br": int(br_value.minute),
        f"{prefix}_weekday_br": br_value.strftime("%A"),
    }


def build_config_key(
    *,
    roulette_id: str,
    suggestion_type: str,
    max_numbers: int,
    history_window_size: int,
) -> str:
    return (
        f"roulette={roulette_id}|type={suggestion_type}|max_numbers={int(max_numbers)}|"
        f"history_window={int(history_window_size)}"
    )


def build_event_id(anchor_history_id: str, config_key: str) -> str:
    digest = sha1(config_key.encode("utf-8")).hexdigest()[:12]
    return f"smonitor:{anchor_history_id}:{digest}"


def normalize_history_doc(doc: Mapping[str, Any]) -> Dict[str, Any]:
    timestamp = ensure_utc_datetime(doc.get("timestamp"))
    history_id = str(doc.get("_id"))
    roulette_id = str(doc.get("roulette_id") or doc.get("slug") or "").strip()
    roulette_name = str(doc.get("roulette_name") or doc.get("slug") or roulette_id).strip() or roulette_id
    value = int(doc.get("value"))
    normalized = {
        "history_id": history_id,
        "roulette_id": roulette_id,
        "roulette_name": roulette_name,
        "value": value,
    }
    normalized.update(build_time_fields("history", timestamp))
    return normalized


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _normalize_suggestion(values: Iterable[Any]) -> List[int]:
    normalized: List[int] = []
    for value in values:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if 0 <= number <= 36:
            normalized.append(number)
    return normalized


def _normalize_number_details(payload: Mapping[str, Any], field_name: str) -> List[Dict[str, Any]]:
    raw_details = payload.get(field_name)
    if not isinstance(raw_details, list):
        return []

    normalized: List[Dict[str, Any]] = []
    for item in raw_details:
        if not isinstance(item, Mapping):
            continue
        try:
            number = int(item.get("number"))
        except (TypeError, ValueError):
            continue
        if not (0 <= number <= 36):
            continue
        supporting_patterns = []
        for raw_pattern in item.get("supporting_patterns") or []:
            if not isinstance(raw_pattern, Mapping):
                continue
            pattern_id = str(raw_pattern.get("pattern_id") or "").strip()
            if not pattern_id:
                continue
            supporting_patterns.append(
                {
                    "pattern_id": pattern_id,
                    "base_pattern_id": str(raw_pattern.get("base_pattern_id") or pattern_id).strip() or pattern_id,
                    "pattern_name": str(raw_pattern.get("pattern_name") or pattern_id).strip() or pattern_id,
                    "applied_weight": round(_safe_float(raw_pattern.get("applied_weight"), 1.0), 6),
                }
            )
        normalized.append(
            {
                "number": number,
                "support_score": _safe_int(item.get("support_score"), 0),
                "support_count": _safe_int(item.get("support_count"), _safe_int(item.get("support_score"), 0)),
                "weighted_support_score": round(_safe_float(item.get("weighted_support_score"), 0.0), 6),
                "supporting_patterns": supporting_patterns,
            }
        )
    return normalized


def _normalize_selected_number_details(payload: Mapping[str, Any]) -> List[Dict[str, Any]]:
    return _normalize_number_details(payload, "selected_number_details")


def _build_support_summary(selected_number_details: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not selected_number_details:
        return {
            "top_support_count": 0,
            "avg_support_count": 0.0,
            "min_support_count": 0,
            "top_weighted_support_score": 0.0,
            "avg_weighted_support_score": 0.0,
            "min_weighted_support_score": 0.0,
        }

    support_scores = [_safe_int(item.get("support_score"), 0) for item in selected_number_details]
    weighted_scores = [_safe_float(item.get("weighted_support_score"), 0.0) for item in selected_number_details]
    return {
        "top_support_count": int(support_scores[0]),
        "avg_support_count": round(sum(support_scores) / len(support_scores), 4),
        "min_support_count": int(support_scores[-1]),
        "top_weighted_support_score": round(float(weighted_scores[0]), 6),
        "avg_weighted_support_score": round(sum(weighted_scores) / len(weighted_scores), 6),
        "min_weighted_support_score": round(float(weighted_scores[-1]), 6),
    }


def _build_shadow_variants(
    *,
    payload: Mapping[str, Any],
    base_suggestion: List[int],
    selected_number_details: List[Dict[str, Any]],
    compare_max_numbers: int,
) -> Dict[str, Any]:
    safe_compare_max_numbers = max(0, min(37, int(compare_max_numbers or 0)))
    if safe_compare_max_numbers <= len(base_suggestion):
        return {}

    full_number_details = _normalize_number_details(payload, "number_details")
    if not full_number_details:
        return {}

    base_numbers = {int(number) for number in base_suggestion}
    extension_needed = safe_compare_max_numbers - len(base_suggestion)
    extension_details: List[Dict[str, Any]] = []
    for detail in full_number_details:
        number = int(detail.get("number"))
        if number in base_numbers:
            continue
        extension_details.append(detail)
        if len(extension_details) >= extension_needed:
            break

    if not extension_details:
        return {}

    variant_details = list(selected_number_details) + extension_details
    variant_suggestion = list(base_suggestion) + [int(item["number"]) for item in extension_details]
    summary = _build_support_summary(variant_details)
    return {
        "max_32": {
            "variant_key": "max_32",
            "label": f"{safe_compare_max_numbers} números",
            "variant_type": "extended_from_base",
            "available": True,
            "status": "pending",
            "explanation": f"Extensão do ranking base para {safe_compare_max_numbers} números.",
            "suggestion": variant_suggestion,
            "ordered_suggestion": variant_suggestion,
            "suggestion_size": len(variant_suggestion),
            "selected_number_details": variant_details,
            **summary,
            "attempts_elapsed": 0,
            "resolved_attempt": None,
            "resolved_history_id": None,
            "resolved_number": None,
            "resolved_rank_position": None,
            "resolved_support_score": None,
            "resolved_weighted_support_score": None,
            "resolved_timestamp_utc": None,
            "resolved_timestamp_br": None,
            "hit_within_1": False,
            "hit_within_4": False,
            "hit_within_8": False,
            "hit_within_16": False,
        }
    }


def _normalize_payload_for_event(payload: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "available": bool(payload.get("available", False)),
        "list": _normalize_suggestion(payload.get("list") or payload.get("suggestion") or []),
        "suggestion": _normalize_suggestion(payload.get("suggestion") or payload.get("list") or []),
        "ordered_suggestion": _normalize_suggestion(payload.get("ordered_suggestion") or payload.get("list") or []),
        "pattern_count": _safe_int(payload.get("pattern_count"), 0),
        "unique_numbers": _safe_int(payload.get("unique_numbers"), 0),
        "selected_number_details": payload.get("selected_number_details") if isinstance(payload.get("selected_number_details"), list) else [],
        "entry_shadow": payload.get("entry_shadow") if isinstance(payload.get("entry_shadow"), Mapping) else {},
        "explanation": str(payload.get("explanation") or "").strip(),
    }


def _build_oscillation_mode(
    *,
    last_base_resolved_rank_position: int | None,
    suggestion_size: int,
) -> Dict[str, Any]:
    size = max(1, int(suggestion_size or 1))
    extreme_band = max(3, round(size * 0.24))
    if last_base_resolved_rank_position is None or last_base_resolved_rank_position <= 0:
        return {
            "mode": "neutral_no_reference",
            "extreme_band": extreme_band,
            "should_reverse": False,
            "reference_rank": None,
        }

    rank = int(last_base_resolved_rank_position)
    top_extreme = rank <= extreme_band
    bottom_extreme = rank >= max(1, size - extreme_band + 1)
    should_reverse = bool(top_extreme or bottom_extreme)
    if top_extreme:
        mode = "reverse_after_top_extreme"
    elif bottom_extreme:
        mode = "reverse_after_bottom_extreme"
    else:
        mode = "neutral_mid_band"
    return {
        "mode": mode,
        "extreme_band": extreme_band,
        "should_reverse": should_reverse,
        "reference_rank": rank,
    }


def _build_rank_blocks(suggestion_size: int) -> List[Dict[str, Any]]:
    size = max(1, int(suggestion_size or 1))
    if size <= 9:
        block_count = 3
    elif size <= 18:
        block_count = 4
    else:
        block_count = 5
    base_size = size // block_count
    remainder = size % block_count
    start = 1
    blocks: List[Dict[str, Any]] = []
    for index in range(block_count):
        block_size = base_size + (1 if index < remainder else 0)
        end = min(size, start + block_size - 1)
        blocks.append(
            {
                "index": index,
                "start": start,
                "end": end,
                "label": f"{start}-{end}" if start != end else str(start),
                "center_rank": (start + end) / 2.0,
            }
        )
        start = end + 1
    return blocks


def _block_index_for_rank(rank: int, blocks: List[Dict[str, Any]]) -> int:
    for block in blocks:
        if int(block["start"]) <= rank <= int(block["end"]):
            return int(block["index"])
    return int(blocks[-1]["index"]) if blocks else 0


def _build_soft_block_context(
    *,
    resolved_ranks: List[int],
    suggestion_size: int,
    aggressive: bool = False,
) -> Dict[str, Any]:
    size = max(1, int(suggestion_size or 1))
    center = (size + 1) / 2.0
    blocks = _build_rank_blocks(size)
    if not resolved_ranks:
        middle_index = len(blocks) // 2 if blocks else 0
        return {
            "mode": "neutral_no_reference_aggressive" if aggressive else "neutral_no_reference",
            "target_rank": round(center),
            "target_block_index": middle_index,
            "target_block_label": blocks[middle_index]["label"] if blocks else "1-1",
            "strength": 0.0,
            "reversal_rate": 0.0,
            "volatility": 0.0,
            "mean_recent_rank": round(center, 4),
            "momentum": 0.0,
            "same_block_run": 0,
            "max_shift": max(4 if aggressive else 3, round(size * (0.22 if aggressive else 0.12))),
            "block_labels": [str(block["label"]) for block in blocks],
            "recent_base_blocks": [],
        }

    ranks = [max(1, min(size, int(rank))) for rank in resolved_ranks[:8]]
    block_indexes = [_block_index_for_rank(rank, blocks) for rank in ranks]
    last_rank = ranks[0]
    previous_rank = ranks[1] if len(ranks) > 1 else center
    mean_recent_rank = mean(ranks[: min(len(ranks), 5)])
    if len(ranks) > 1:
        pair_count = len(ranks) - 1
        reversals = 0
        deltas: List[float] = []
        for current, nxt in zip(ranks, ranks[1:]):
            current_sign = current - center
            next_sign = nxt - center
            if current_sign == 0 or next_sign == 0:
                continue
            if (current_sign > 0) != (next_sign > 0):
                reversals += 1
            deltas.append(abs(current - nxt))
        reversal_rate = reversals / max(1, pair_count)
        volatility = (mean(deltas) / max(1.0, size - 1.0)) if deltas else 0.0
    else:
        reversal_rate = 0.0
        volatility = 0.0

    last_block = block_indexes[0]
    same_block_run = 1
    for block_index in block_indexes[1:]:
        if block_index == last_block:
            same_block_run += 1
        else:
            break

    block_count = len(blocks)
    middle_block_index = (block_count - 1) / 2.0
    mean_block = mean(block_indexes[: min(len(block_indexes), 5)]) if block_indexes else middle_block_index
    top_extreme = last_block == 0
    bottom_extreme = last_block == block_count - 1
    upper_bias = last_block <= 1
    lower_bias = last_block >= max(0, block_count - 2)
    amplitude = abs(last_rank - center) / max(1.0, (size - 1.0) / 2.0)
    strength = min(
        0.88 if aggressive else 0.72,
        max(
            0.24 if aggressive else 0.18,
            (0.26 if aggressive else 0.20)
            + (reversal_rate * (0.32 if aggressive else 0.22))
            + (volatility * (0.22 if aggressive else 0.16))
            + (min(3, same_block_run) * (0.07 if aggressive else 0.05))
            + (amplitude * (0.11 if aggressive else 0.07)),
        ),
    )
    momentum = float(last_rank) - float(previous_rank)
    if top_extreme and same_block_run >= 2:
        mode = "persistent_top_aggressive" if aggressive else "persistent_top_soft"
        target_block_index = min(block_count - 1, 2 if aggressive else 1)
    elif bottom_extreme and same_block_run >= 2:
        mode = "persistent_bottom_aggressive" if aggressive else "persistent_bottom_soft"
        target_block_index = max(0, block_count - (3 if aggressive else 2))
    elif top_extreme and reversal_rate >= 0.45:
        mode = "rebound_from_top_aggressive" if aggressive else "rebound_from_top"
        target_block_index = min(block_count - 1, 3 if aggressive else 2)
    elif bottom_extreme and reversal_rate >= 0.45:
        mode = "rebound_from_bottom_aggressive" if aggressive else "rebound_from_bottom"
        target_block_index = max(0, block_count - (4 if aggressive else 3))
    elif upper_bias:
        mode = "upper_bias_aggressive" if aggressive else "upper_bias_soft"
        target_block_index = min(
            block_count - 1,
            max(1, round((mean_block + (2 if aggressive else 1)) / 2)),
        )
    elif lower_bias:
        mode = "lower_bias_aggressive" if aggressive else "lower_bias_soft"
        target_block_index = max(
            0,
            min(
                block_count - 2,
                round((mean_block + (block_count - (3 if aggressive else 2))) / 2),
            ),
        )
    else:
        mode = "neutral_center_pull_aggressive" if aggressive else "neutral_center_pull"
        target_block_index = max(
            0,
            min(
                block_count - 1,
                round((mean_block + middle_block_index + (0.5 if aggressive else 0.0)) / 2),
            ),
        )

    target_block = blocks[target_block_index]
    target_center_rank = float(target_block["center_rank"])
    predicted = (
        (target_center_rank * ((0.64 + strength * 0.18) if aggressive else (0.52 + strength * 0.14)))
        + (mean_recent_rank * (0.20 if aggressive else 0.28))
        + (((center + last_rank) / 2.0) * (0.12 if aggressive else 0.20))
        - ((0.14 if aggressive else 0.08) * momentum)
    )
    target_rank = max(1, min(size, round(predicted)))
    max_shift = max(
        4 if aggressive else 3,
        min(
            max(7 if aggressive else 4, round(size * (0.40 if aggressive else 0.24))),
            round(size * ((0.22 if aggressive else 0.10) + strength * (0.24 if aggressive else 0.16))),
        ),
    )
    return {
        "mode": mode,
        "target_rank": int(target_rank),
        "strength": round(float(strength), 4),
        "reversal_rate": round(float(reversal_rate), 4),
        "volatility": round(float(volatility), 4),
        "mean_recent_rank": round(float(mean_recent_rank), 4),
        "momentum": round(float(momentum), 4),
        "same_block_run": int(same_block_run),
        "target_block_index": int(target_block_index),
        "target_block_label": str(target_block["label"]),
        "max_shift": int(max_shift),
        "block_labels": [str(block["label"]) for block in blocks],
        "recent_base_blocks": [int(block) for block in block_indexes[:8]],
    }


def _apply_position_guardrails(
    *,
    desired_order: List[Dict[str, Any]],
    suggestion_size: int,
    max_shift: int,
) -> List[Dict[str, Any]]:
    size = max(1, int(suggestion_size or len(desired_order) or 1))
    max_allowed_shift = max(1, int(max_shift or 1))
    available_positions = set(range(1, size + 1))
    assigned_positions: Dict[int, int] = {}

    for desired_position, item in enumerate(desired_order, start=1):
        original_position = max(1, min(size, _safe_int(item.get("original_rank_position"), desired_position)))
        min_position = max(1, original_position - max_allowed_shift)
        max_position = min(size, original_position + max_allowed_shift)
        candidates = [
            position
            for position in available_positions
            if min_position <= position <= max_position
        ]
        if not candidates:
            candidates = list(available_positions)
        chosen_position = min(
            candidates,
            key=lambda position: (
                abs(position - desired_position),
                abs(position - original_position),
                position,
            ),
        )
        assigned_positions[int(item["number"])] = int(chosen_position)
        available_positions.discard(chosen_position)

    return sorted(
        desired_order,
        key=lambda item: (
            assigned_positions.get(int(item["number"]), size),
            _safe_int(item.get("original_rank_position"), size),
        ),
    )


def _build_selective_gate(
    *,
    resolved_ranks: List[int],
    target: Mapping[str, Any],
    suggestion_size: int,
) -> Dict[str, Any]:
    size = max(1, int(suggestion_size or 1))
    center = (size + 1) / 2.0
    extreme_band = max(5, round(size * 0.24))
    ranks = [max(1, min(size, int(rank))) for rank in resolved_ranks[:6] if int(rank) > 0]
    if len(ranks) < 3:
        return {
            "active": False,
            "reason": "amostra curta demais para confirmar tendência",
            "predicted_move": "neutral",
            "edge_pressure": len(ranks),
            "trend_direction": "flat",
            "trend_consistency": 0.0,
        }

    last_rank, previous_rank, third_rank = ranks[0], ranks[1], ranks[2]
    upper_extreme = last_rank <= extreme_band
    lower_extreme = last_rank >= max(1, size - extreme_band + 1)
    trend_direction = "up" if last_rank < previous_rank else "down" if last_rank > previous_rank else "flat"
    previous_direction = "up" if previous_rank < third_rank else "down" if previous_rank > third_rank else "flat"
    trend_consistency = 1.0 if trend_direction != "flat" and trend_direction == previous_direction else 0.0
    edge_pressure = sum(
        1
        for rank in ranks[:4]
        if rank <= extreme_band or rank >= max(1, size - extreme_band + 1)
    )
    amplitude = abs(last_rank - center) / max(1.0, (size - 1.0) / 2.0)
    reversal_rate = _safe_float(target.get("reversal_rate"), 0.0)
    strength = _safe_float(target.get("strength"), 0.0)
    same_block_run = _safe_int(target.get("same_block_run"), 0)

    predicted_move = "neutral"
    active = False
    reason = "sem tendência clara"
    if upper_extreme and trend_direction == "up" and (edge_pressure >= 2) and (
        trend_consistency >= 1.0 or reversal_rate >= 0.42 or same_block_run >= 2
    ):
        predicted_move = "down"
        active = True
        reason = "topo em aceleração sugere descida"
    elif lower_extreme and trend_direction == "down" and (edge_pressure >= 2) and (
        trend_consistency >= 1.0 or reversal_rate >= 0.42 or same_block_run >= 2
    ):
        predicted_move = "up"
        active = True
        reason = "fundo em aceleração sugere subida"
    elif upper_extreme and same_block_run >= 2 and strength >= 0.48 and amplitude >= 0.55:
        predicted_move = "down"
        active = True
        reason = "topo persistente em extremidade"
    elif lower_extreme and same_block_run >= 2 and strength >= 0.48 and amplitude >= 0.55:
        predicted_move = "up"
        active = True
        reason = "fundo persistente em extremidade"
    elif edge_pressure >= 3 and reversal_rate >= 0.58 and amplitude >= 0.62:
        predicted_move = "down" if last_rank < center else "up"
        active = True
        reason = "pêndulo forte nas extremidades"

    return {
        "active": bool(active),
        "reason": str(reason),
        "predicted_move": str(predicted_move),
        "edge_pressure": int(edge_pressure),
        "trend_direction": str(trend_direction),
        "trend_consistency": round(float(trend_consistency), 4),
    }


def _build_compact_selective_gate(
    *,
    resolved_ranks: List[int],
    target: Mapping[str, Any],
    suggestion_size: int,
) -> Dict[str, Any]:
    size = max(1, int(suggestion_size or 1))
    center = (size + 1) / 2.0
    extreme_band = max(6, round(size * 0.20))
    near_band = max(extreme_band + 2, round(size * 0.30))
    lower_extreme_start = max(1, size - extreme_band + 1)
    lower_near_start = max(1, size - near_band + 1)
    ranks = [max(1, min(size, int(rank))) for rank in resolved_ranks[:5] if int(rank) > 0]
    if len(ranks) < 2:
        return {
            "active": False,
            "reason": "amostra curta demais para abrir janela compacta",
            "predicted_move": "neutral",
            "edge_pressure": len(ranks),
            "trend_direction": "flat",
            "trend_consistency": 0.0,
        }

    last_rank, previous_rank = ranks[0], ranks[1]
    third_rank = ranks[2] if len(ranks) >= 3 else previous_rank
    trend_direction = "up" if last_rank < previous_rank else "down" if last_rank > previous_rank else "flat"
    previous_direction = "up" if previous_rank < third_rank else "down" if previous_rank > third_rank else "flat"
    trend_consistency = 1.0 if trend_direction != "flat" and trend_direction == previous_direction else 0.0
    edge_pressure = sum(
        1
        for rank in ranks[:3]
        if rank <= near_band or rank >= lower_near_start
    )
    amplitude = abs(last_rank - center) / max(1.0, (size - 1.0) / 2.0)
    reversal_rate = _safe_float(target.get("reversal_rate"), 0.0)
    strength = _safe_float(target.get("strength"), 0.0)
    same_block_run = _safe_int(target.get("same_block_run"), 0)
    last_is_upper = last_rank <= near_band
    last_is_lower = last_rank >= lower_near_start
    upper_extreme = last_rank <= extreme_band
    lower_extreme = last_rank >= lower_extreme_start

    predicted_move = "neutral"
    active = False
    reason = "sem pêndulo forte o bastante"
    if upper_extreme and trend_direction == "up":
        predicted_move = "down"
        active = True
        reason = "subida entrou no topo extremo"
    elif lower_extreme and trend_direction == "down":
        predicted_move = "up"
        active = True
        reason = "descida entrou no fundo extremo"
    elif last_is_upper and edge_pressure >= 2 and (strength >= 0.30 or reversal_rate >= 0.34):
        predicted_move = "down"
        active = True
        reason = "pressão alta no topo recente"
    elif last_is_lower and edge_pressure >= 2 and (strength >= 0.30 or reversal_rate >= 0.34):
        predicted_move = "up"
        active = True
        reason = "pressão alta no fundo recente"
    elif trend_consistency >= 1.0 and amplitude >= 0.48 and edge_pressure >= 2:
        predicted_move = "down" if last_rank < center else "up"
        active = True
        reason = "movimento consistente em direção à extremidade"
    elif same_block_run >= 2 and amplitude >= 0.44:
        predicted_move = "down" if last_rank < center else "up"
        active = True
        reason = "persistência curta perto da extremidade"

    return {
        "active": bool(active),
        "reason": str(reason),
        "predicted_move": str(predicted_move),
        "edge_pressure": int(edge_pressure),
        "trend_direction": str(trend_direction),
        "trend_consistency": round(float(trend_consistency), 4),
    }


def _build_compact_block_priority(
    *,
    block_count: int,
    target_block_index: int,
) -> List[int]:
    order = [max(0, min(block_count - 1, int(target_block_index)))]
    for distance in range(1, block_count):
        left = target_block_index - distance
        right = target_block_index + distance
        if left >= 0:
            order.append(int(left))
        if right < block_count:
            order.append(int(right))
    deduped: List[int] = []
    for item in order:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _wheel_distance(left: int, right: int) -> int:
    if int(left) not in WHEEL_INDEX or int(right) not in WHEEL_INDEX:
        return 99
    wheel_size = len(WHEEL_ORDER)
    left_index = WHEEL_INDEX[int(left)]
    right_index = WHEEL_INDEX[int(right)]
    distance = abs(left_index - right_index)
    return min(distance, wheel_size - distance)


def _region_similarity(number: int, result_number: int, sigma: float = 2.2) -> float:
    distance = _wheel_distance(int(number), int(result_number))
    if distance >= 99:
        return 0.0
    return float(exp(-float(distance) / max(0.25, float(sigma))))


def _attempt_quality_weight(resolved_attempt: int) -> float:
    attempt = max(1, int(resolved_attempt or 1))
    if attempt == 1:
        return 1.0
    if attempt == 2:
        return 0.45
    if attempt == 3:
        return 0.12
    if attempt <= 5:
        return -0.18
    return -0.40


def _position_weight(rank_position: int, suggestion_size: int) -> float:
    size = max(1, int(suggestion_size or 1))
    rank = max(1, min(size, int(rank_position or size)))
    return max(0.0, 1.0 - ((rank - 1.0) / max(1.0, size - 1.0)))


def build_temporal_blend_payload_from_base(
    *,
    base_payload: Mapping[str, Any],
    recent_resolved_base_events: List[Mapping[str, Any]] | None,
    history_values: List[int] | None,
) -> Dict[str, Any] | None:
    normalized_payload = _normalize_payload_for_event(base_payload)
    suggestion = list(normalized_payload.get("list") or [])
    if not suggestion:
        return None

    selected_number_details = _normalize_selected_number_details(base_payload)
    if not selected_number_details:
        return None

    recent_events = [dict(item) for item in (recent_resolved_base_events or []) if isinstance(item, Mapping)]
    recent_ranks = [
        _safe_int(item.get("resolved_rank_position"), 0)
        for item in recent_events
        if _safe_int(item.get("resolved_rank_position"), 0) > 0
    ]
    recent_results = [int(value) for value in (history_values or []) if 0 <= int(value) <= 36][:6]
    last_event_id = str(recent_events[0].get("_id") or "").strip() if recent_events else None
    weighted_scores = [_safe_float(item.get("weighted_support_score"), 0.0) for item in selected_number_details]
    min_weight = min(weighted_scores) if weighted_scores else 0.0
    max_weight = max(weighted_scores) if weighted_scores else 0.0
    denom = max(0.000001, max_weight - min_weight)
    suggestion_size = len(selected_number_details)
    max_shift = max(6, min(12, round(suggestion_size * 0.32)))

    last_event = recent_events[0] if recent_events else {}
    last_suggestion = _normalize_suggestion(last_event.get("suggestion") or [])
    last_rank_map = {int(number): index + 1 for index, number in enumerate(last_suggestion)}

    scored_details: List[Dict[str, Any]] = []
    for original_rank, detail in enumerate(selected_number_details, start=1):
        number = int(detail["number"])
        support_norm = (_safe_float(detail.get("weighted_support_score"), 0.0) - min_weight) / denom if weighted_scores else 0.0
        current_score = (support_norm * 0.72) + (_position_weight(original_rank, suggestion_size) * 0.28)

        suggestion_memory = 0.0
        suggestion_hits = 0
        suggestion_presence = 0
        past_positions: List[int] = []
        for index, event in enumerate(recent_events[:6]):
            past_suggestion = _normalize_suggestion(event.get("suggestion") or [])
            if number not in past_suggestion:
                continue
            suggestion_presence += 1
            past_rank = past_suggestion.index(number) + 1
            past_positions.append(past_rank)
            outcome_weight = _attempt_quality_weight(_safe_int(event.get("resolved_attempt"), 6))
            rank_weight = _position_weight(past_rank, len(past_suggestion))
            decay = 0.84 ** index
            resolved_number = _safe_int(event.get("resolved_number"), -1)
            exact_bonus = 0.15 if resolved_number == number else 0.0
            suggestion_memory += decay * ((outcome_weight * (0.65 + (rank_weight * 0.35))) + exact_bonus)
            if _safe_int(event.get("resolved_attempt"), 99) == 1:
                suggestion_hits += 1

        if suggestion_presence > 0:
            suggestion_memory = suggestion_memory / suggestion_presence

        result_memory = 0.0
        for index, result_number in enumerate(recent_results[:5]):
            decay = 0.86 ** index
            result_memory += decay * _region_similarity(number, result_number, sigma=2.2)

        persistence = 0.0
        volatility_penalty = 0.0
        if past_positions:
            average_past_rank = sum(past_positions) / len(past_positions)
            persistence = 1.0 - (abs(original_rank - average_past_rank) / max(1.0, suggestion_size - 1.0))
            last_rank = _safe_int(last_rank_map.get(number), 0)
            if last_rank > 0:
                volatility_penalty = abs(original_rank - last_rank) / max(1.0, suggestion_size - 1.0)

        final_score = (
            (current_score * 0.55)
            + (suggestion_memory * 0.20)
            + (result_memory * 0.15)
            + (persistence * 0.10)
            - (volatility_penalty * 0.08)
        )

        enriched = dict(detail)
        enriched["original_rank_position"] = original_rank
        enriched["temporal_current_score"] = round(float(current_score), 6)
        enriched["temporal_suggestion_memory"] = round(float(suggestion_memory), 6)
        enriched["temporal_result_memory"] = round(float(result_memory), 6)
        enriched["temporal_persistence"] = round(float(persistence), 6)
        enriched["temporal_volatility_penalty"] = round(float(volatility_penalty), 6)
        enriched["temporal_presence_count"] = int(suggestion_presence)
        enriched["temporal_first_hit_support"] = int(suggestion_hits)
        enriched["temporal_rerank_score"] = round(float(final_score), 6)
        scored_details.append(enriched)

    desired_order = sorted(
        scored_details,
        key=lambda item: (
            -_safe_float(item.get("temporal_rerank_score"), 0.0),
            -_safe_float(item.get("weighted_support_score"), 0.0),
            _safe_int(item.get("original_rank_position"), 999),
        ),
    )
    reordered_details = _apply_position_guardrails(
        desired_order=desired_order,
        suggestion_size=suggestion_size,
        max_shift=max_shift,
    )
    reordered_suggestion = [int(item["number"]) for item in reordered_details]
    summary = _build_support_summary(reordered_details)
    return {
        "available": bool(normalized_payload["available"]),
        "list": reordered_suggestion,
        "suggestion": reordered_suggestion,
        "ordered_suggestion": reordered_suggestion,
        "pattern_count": int(normalized_payload["pattern_count"]),
        "unique_numbers": int(normalized_payload["unique_numbers"] or len(reordered_suggestion)),
        "selected_number_details": reordered_details,
        "entry_shadow": dict(normalized_payload["entry_shadow"]),
        "explanation": (
            "Temporal blend v1 derivado da sugestão atual da API com memória temporal. "
            f"recent_results={recent_results[:5]} recent_base_ranks={recent_ranks[:6]} max_shift={max_shift}."
        ),
        "oscillation": {
            "profile": "temporal_blend_v1",
            "source_base_event_id": last_event_id,
            "recent_base_ranks": [int(rank) for rank in recent_ranks[:8]],
            "recent_history_numbers": [int(value) for value in recent_results[:6]],
            "memory_components": {
                "current_score_weight": 0.55,
                "suggestion_memory_weight": 0.20,
                "result_memory_weight": 0.15,
                "persistence_weight": 0.10,
                "volatility_penalty_weight": 0.08,
            },
            "max_shift": int(max_shift),
        },
        **summary,
    }


def _build_selective_protection_plan(
    *,
    predicted_move: str,
    suggestion_size: int,
) -> Dict[str, Any] | None:
    move = str(predicted_move or "neutral").strip().lower()
    size = max(1, int(suggestion_size or 1))
    if move not in {"up", "down"}:
        return None

    protection_side = "bottom" if move == "up" else "top"
    band = max(5, min(8, round(size * 0.16)))
    count = max(4, min(6, round(size * 0.14)))
    slots = [2 + (index * 3) for index in range(count)]
    return {
        "enabled": True,
        "predicted_move": move,
        "protection_side": protection_side,
        "band": int(min(size, band)),
        "count": int(count),
        "slots": [int(slot) for slot in slots if slot <= size],
    }


def _compute_protection_closeness(
    *,
    original_rank: int,
    suggestion_size: int,
    protection_side: str,
    protection_band: int,
) -> float:
    size = max(1, int(suggestion_size or 1))
    rank = max(1, min(size, int(original_rank or 1)))
    band = max(1, min(size, int(protection_band or 1)))
    side = str(protection_side or "").strip().lower()
    if side == "top":
        if rank > band:
            return 0.0
        return max(0.0, 1.0 - ((rank - 1.0) / max(1.0, band - 1.0)))
    if side == "bottom":
        start = max(1, size - band + 1)
        if rank < start:
            return 0.0
        return max(0.0, 1.0 - ((size - rank) / max(1.0, band - 1.0)))
    return 0.0


def _merge_protection_candidates(
    *,
    desired_order: List[Dict[str, Any]],
    protection_candidates: List[Dict[str, Any]],
    protection_slots: List[int],
) -> List[Dict[str, Any]]:
    if not desired_order:
        return []

    slots = [int(slot) for slot in protection_slots if int(slot) >= 1]
    if not slots or not protection_candidates:
        return list(desired_order)

    protected_numbers = {int(item["number"]) for item in protection_candidates}
    remaining_core = [item for item in desired_order if int(item["number"]) not in protected_numbers]
    final_order: List[Dict[str, Any]] = []
    protection_index = 0
    core_index = 0
    total_size = len(desired_order)

    for position in range(1, total_size + 1):
        use_protection = position in slots and protection_index < len(protection_candidates)
        if use_protection:
            final_order.append(protection_candidates[protection_index])
            protection_index += 1
            continue
        if core_index < len(remaining_core):
            final_order.append(remaining_core[core_index])
            core_index += 1
            continue
        if protection_index < len(protection_candidates):
            final_order.append(protection_candidates[protection_index])
            protection_index += 1

    seen_numbers = set()
    deduped: List[Dict[str, Any]] = []
    for item in final_order:
        number = int(item["number"])
        if number in seen_numbers:
            continue
        seen_numbers.add(number)
        deduped.append(item)
    for item in desired_order:
        number = int(item["number"])
        if number in seen_numbers:
            continue
        seen_numbers.add(number)
        deduped.append(item)
    return deduped[:total_size]


def build_oscillation_payload_from_base(
    *,
    base_payload: Mapping[str, Any],
    recent_resolved_base_events: List[Mapping[str, Any]] | None,
    profile: str = "soft_blocks_v1",
) -> Dict[str, Any] | None:
    normalized_payload = _normalize_payload_for_event(base_payload)
    suggestion = list(normalized_payload.get("list") or [])
    if not suggestion:
        return None

    selected_number_details = _normalize_selected_number_details(base_payload)
    if not selected_number_details:
        return None

    recent_events = [dict(item) for item in (recent_resolved_base_events or []) if isinstance(item, Mapping)]
    recent_ranks = [
        _safe_int(item.get("resolved_rank_position"), 0)
        for item in recent_events
        if _safe_int(item.get("resolved_rank_position"), 0) > 0
    ]
    last_event_id = str(recent_events[0].get("_id") or "").strip() if recent_events else None
    last_rank = recent_ranks[0] if recent_ranks else None

    normalized_profile = str(profile or "").strip().lower()
    protected = normalized_profile in {
        "protected",
        "oscillation_v3_selective_protected",
        "selective_protected",
        "selective_protection_v3",
    }
    aggressive = normalized_profile in {
        "aggressive",
        "oscillation_v2_aggressive",
        "aggressive_blocks_v2",
        "oscillation_v3_selective",
        "oscillation_v3_selective_protected",
    }
    selective = normalized_profile in {
        "selective",
        "oscillation_v3_selective",
        "selective_gate_v3",
        "oscillation_v3_selective_protected",
        "selective_protected",
        "selective_protection_v3",
    }
    target = _build_soft_block_context(
        resolved_ranks=recent_ranks,
        suggestion_size=len(suggestion),
        aggressive=aggressive,
    )
    selective_gate = _build_selective_gate(
        resolved_ranks=recent_ranks,
        target=target,
        suggestion_size=len(suggestion),
    ) if selective else None
    oscillation = _build_oscillation_mode(
        last_base_resolved_rank_position=last_rank,
        suggestion_size=len(suggestion),
    )
    oscillation["mode"] = str(target["mode"])
    oscillation["should_reverse"] = False
    weighted_scores = [_safe_float(item.get("weighted_support_score"), 0.0) for item in selected_number_details]
    min_weight = min(weighted_scores) if weighted_scores else 0.0
    max_weight = max(weighted_scores) if weighted_scores else 0.0
    denom = max(0.000001, max_weight - min_weight)
    target_rank = int(target["target_rank"])
    target_block_index = int(target["target_block_index"])
    strength = _safe_float(target.get("strength"), 0.0)
    blocks = _build_rank_blocks(len(selected_number_details))
    center = (len(selected_number_details) + 1) / 2.0

    protection_plan = None
    if selective and isinstance(selective_gate, Mapping):
        block_count = len(blocks)
        if str(selective_gate.get("predicted_move") or "") == "up":
            target_block_index = 0
            target_rank = max(1, round(center * 0.38))
        elif str(selective_gate.get("predicted_move") or "") == "down":
            target_block_index = max(0, block_count - 1)
            target_rank = min(len(selected_number_details), round(center * 1.62))
        target["target_block_index"] = int(target_block_index)
        target["target_block_label"] = str(blocks[target_block_index]["label"])
        target["target_rank"] = int(target_rank)
        if not bool(selective_gate.get("active", False)):
            return {
                "available": False,
                "list": [],
                "suggestion": [],
                "ordered_suggestion": [],
                "pattern_count": int(normalized_payload["pattern_count"]),
                "unique_numbers": 0,
                "selected_number_details": [],
                "entry_shadow": dict(normalized_payload["entry_shadow"]),
                "explanation": (
                    "Oscillation selective v3 sem entrada. "
                    f"motivo={selective_gate.get('reason') or '-'} "
                    f"edge_pressure={selective_gate.get('edge_pressure') or 0} "
                    f"trend={selective_gate.get('trend_direction') or '-'}."
                ),
                "oscillation": {
                    **oscillation,
                    **target,
                    "profile": "oscillation_v3_selective_protected" if protected else "oscillation_v3_selective",
                    "selective_gate": dict(selective_gate),
                    "protection": None,
                    "source_base_event_id": last_event_id,
                    "recent_base_ranks": [int(rank) for rank in recent_ranks[:8]],
                },
            }
        if protected:
            protection_plan = _build_selective_protection_plan(
                predicted_move=str(selective_gate.get("predicted_move") or "neutral"),
                suggestion_size=len(selected_number_details),
            )
            if isinstance(protection_plan, Mapping):
                target["max_shift"] = max(
                    int(target["max_shift"]),
                    max(12, round(len(selected_number_details) * 0.75)),
                )

    scored_details: List[Dict[str, Any]] = []
    for original_rank, detail in enumerate(selected_number_details, start=1):
        support_norm = (_safe_float(detail.get("weighted_support_score"), 0.0) - min_weight) / denom if weighted_scores else 0.0
        target_closeness = 1.0 - (abs(original_rank - target_rank) / max(1.0, len(selected_number_details) - 1.0))
        base_rank_bonus = 1.0 - ((original_rank - 1.0) / max(1.0, len(selected_number_details) - 1.0))
        block_index = _block_index_for_rank(original_rank, blocks)
        block_distance = abs(block_index - target_block_index)
        block_bias = max(0.0, 1.0 - (block_distance / max(1.0, len(blocks) - 1.0)))
        movement_penalty = abs(original_rank - target_rank) / max(1.0, len(selected_number_details) - 1.0)
        protection_closeness = _compute_protection_closeness(
            original_rank=original_rank,
            suggestion_size=len(selected_number_details),
            protection_side=((protection_plan or {}).get("protection_side") if isinstance(protection_plan, Mapping) else ""),
            protection_band=_safe_int((protection_plan or {}).get("band"), 0) if isinstance(protection_plan, Mapping) else 0,
        )
        if protected:
            rerank_score = (
                (support_norm * 0.24)
                + (target_closeness * (0.18 + (strength * 0.10)))
                + (block_bias * (0.26 + (strength * 0.08)))
                + (protection_closeness * 0.30)
                + (base_rank_bonus * 0.04)
                - (movement_penalty * (0.02 + ((1.0 - strength) * 0.02)))
            )
        else:
            rerank_score = (
                (support_norm * (0.28 if aggressive else 0.52))
                + (target_closeness * ((0.28 if aggressive else 0.18) + (strength * (0.18 if aggressive else 0.10))))
                + (block_bias * ((0.42 if aggressive else 0.22) + (strength * (0.14 if aggressive else 0.08))))
                + (base_rank_bonus * (0.05 if aggressive else 0.12))
                - (movement_penalty * ((0.03 if aggressive else 0.06) + ((1.0 - strength) * (0.02 if aggressive else 0.04))))
            )
        enriched = dict(detail)
        enriched["original_rank_position"] = original_rank
        enriched["oscillation_block_index"] = int(block_index)
        enriched["oscillation_block_bias"] = round(float(block_bias), 6)
        enriched["oscillation_target_closeness"] = round(float(target_closeness), 6)
        enriched["oscillation_protection_closeness"] = round(float(protection_closeness), 6)
        enriched["oscillation_rerank_score"] = round(float(rerank_score), 6)
        scored_details.append(enriched)

    desired_order = sorted(
        scored_details,
        key=lambda item: (
            -_safe_float(item.get("oscillation_rerank_score"), 0.0),
            -_safe_float(item.get("weighted_support_score"), 0.0),
            _safe_int(item.get("original_rank_position"), 999),
        ),
    )
    if protected and isinstance(protection_plan, Mapping):
        protection_side = str(protection_plan.get("protection_side") or "")
        protection_candidates = sorted(
            [
                item
                for item in scored_details
                if _safe_float(item.get("oscillation_protection_closeness"), 0.0) > 0.0
            ],
            key=lambda item: (
                -_safe_float(item.get("oscillation_protection_closeness"), 0.0),
                -_safe_float(item.get("weighted_support_score"), 0.0),
                _safe_int(item.get("original_rank_position"), 999)
                if protection_side == "top"
                else -_safe_int(item.get("original_rank_position"), 0),
            ),
        )[: _safe_int(protection_plan.get("count"), 0)]
        desired_order = _merge_protection_candidates(
            desired_order=desired_order,
            protection_candidates=protection_candidates,
            protection_slots=[int(slot) for slot in (protection_plan.get("slots") or [])],
        )
    reordered_details = _apply_position_guardrails(
        desired_order=desired_order,
        suggestion_size=len(selected_number_details),
        max_shift=int(target["max_shift"]),
    )

    reordered_suggestion = [int(item["number"]) for item in reordered_details]
    summary = _build_support_summary(reordered_details)
    return {
        "available": bool(normalized_payload["available"]),
        "list": reordered_suggestion,
        "suggestion": reordered_suggestion,
        "ordered_suggestion": reordered_suggestion,
        "pattern_count": int(normalized_payload["pattern_count"]),
        "unique_numbers": int(normalized_payload["unique_numbers"] or len(reordered_suggestion)),
        "selected_number_details": reordered_details,
        "entry_shadow": dict(normalized_payload["entry_shadow"]),
        "explanation": (
            f"Oscillation {('selective protected v3' if protected else ('selective v3' if selective else ('aggressive-blocks v2' if aggressive else 'soft-blocks v1')))} derivada do ranking base. "
            f"modo={target['mode']} referencia_rank={oscillation['reference_rank'] or '-'} "
            f"alvo={target['target_block_label']} target_rank={target_rank} max_shift={target['max_shift']}"
            + (
                f" protection={protection_plan.get('protection_side')} slots={len(protection_plan.get('slots') or [])}"
                if isinstance(protection_plan, Mapping)
                else ""
            )
            + "."
        ),
        "oscillation": {
            **oscillation,
            **target,
            "profile": (
                "oscillation_v3_selective_protected"
                if protected
                else ("oscillation_v3_selective" if selective
                else ("oscillation_v2_aggressive" if aggressive else "oscillation_v1")
                )
            ),
            "selective_gate": dict(selective_gate) if isinstance(selective_gate, Mapping) else None,
            "protection": dict(protection_plan) if isinstance(protection_plan, Mapping) else None,
            "source_base_event_id": last_event_id,
            "recent_base_ranks": [int(rank) for rank in recent_ranks[:8]],
        },
        **summary,
    }


def build_selective_compact_payload_from_base(
    *,
    base_payload: Mapping[str, Any],
    recent_resolved_base_events: List[Mapping[str, Any]] | None,
    hold_state: Mapping[str, Any] | None = None,
    compact_size: int = 18,
    hold_rounds: int = 3,
) -> Dict[str, Any] | None:
    normalized_payload = _normalize_payload_for_event(base_payload)
    suggestion = list(normalized_payload.get("list") or [])
    if not suggestion:
        return None

    selected_number_details = _normalize_selected_number_details(base_payload)
    if not selected_number_details:
        return None

    recent_events = [dict(item) for item in (recent_resolved_base_events or []) if isinstance(item, Mapping)]
    recent_ranks = [
        _safe_int(item.get("resolved_rank_position"), 0)
        for item in recent_events
        if _safe_int(item.get("resolved_rank_position"), 0) > 0
    ]
    last_event_id = str(recent_events[0].get("_id") or "").strip() if recent_events else None
    target = _build_soft_block_context(
        resolved_ranks=recent_ranks,
        suggestion_size=len(suggestion),
        aggressive=True,
    )
    selective_gate = _build_compact_selective_gate(
        resolved_ranks=recent_ranks,
        target=target,
        suggestion_size=len(suggestion),
    )
    blocks = _build_rank_blocks(len(selected_number_details))
    safe_hold_rounds = max(1, int(hold_rounds or 1))
    compact_limit = max(1, min(len(selected_number_details), int(compact_size or 18)))

    effective_hold = dict(hold_state or {}) if isinstance(hold_state, Mapping) else {}
    using_hold = bool(effective_hold.get("active")) and _safe_int(effective_hold.get("rounds_remaining"), 0) > 0
    if using_hold:
        target_block_index = max(0, min(len(blocks) - 1, _safe_int(effective_hold.get("target_block_index"), 0)))
        predicted_move = str(effective_hold.get("predicted_move") or "neutral")
        hold_origin = "carryover"
        remaining_before = max(1, _safe_int(effective_hold.get("rounds_remaining"), 1))
    else:
        if not bool(selective_gate.get("active", False)):
            return {
                "available": False,
                "list": [],
                "suggestion": [],
                "ordered_suggestion": [],
                "pattern_count": int(normalized_payload["pattern_count"]),
                "unique_numbers": 0,
                "selected_number_details": [],
                "entry_shadow": dict(normalized_payload["entry_shadow"]),
                "evaluation_window_attempts": 3,
                "explanation": (
                    "Oscillation selective compact v4 sem entrada. "
                    f"motivo={selective_gate.get('reason') or '-'} "
                    f"edge_pressure={selective_gate.get('edge_pressure') or 0} "
                    f"trend={selective_gate.get('trend_direction') or '-'}."
                ),
                "oscillation": {
                    **target,
                    "profile": "oscillation_v4_selective_compact",
                    "selective_gate": dict(selective_gate),
                    "compact_hold": {
                        "active": False,
                        "origin": "gate_closed",
                        "rounds_remaining": 0,
                        "rounds_total": safe_hold_rounds,
                    },
                    "source_base_event_id": last_event_id,
                    "recent_base_ranks": [int(rank) for rank in recent_ranks[:8]],
                },
            }
        predicted_move = str(selective_gate.get("predicted_move") or "neutral")
        target_block_index = 0 if predicted_move == "up" else len(blocks) - 1
        hold_origin = "new_gate"
        remaining_before = safe_hold_rounds

    target_block_index = max(0, min(len(blocks) - 1, int(target_block_index)))
    priority_blocks = _build_compact_block_priority(
        block_count=len(blocks),
        target_block_index=target_block_index,
    )
    block_priority_map = {block_index: priority for priority, block_index in enumerate(priority_blocks)}
    compact_details: List[Dict[str, Any]] = []
    for original_rank, detail in enumerate(selected_number_details, start=1):
        block_index = _block_index_for_rank(original_rank, blocks)
        enriched = dict(detail)
        enriched["original_rank_position"] = original_rank
        enriched["compact_block_index"] = int(block_index)
        enriched["compact_block_priority"] = int(block_priority_map.get(block_index, len(priority_blocks)))
        compact_details.append(enriched)

    compact_details.sort(
        key=lambda item: (
            _safe_int(item.get("compact_block_priority"), 999),
            -_safe_float(item.get("weighted_support_score"), 0.0),
            _safe_int(item.get("original_rank_position"), 999),
        )
    )
    compact_details = compact_details[:compact_limit]
    compact_suggestion = [int(item["number"]) for item in compact_details]
    remaining_after = max(0, remaining_before - 1)
    summary = _build_support_summary(compact_details)
    target_block = blocks[target_block_index]
    return {
        "available": True,
        "list": compact_suggestion,
        "suggestion": compact_suggestion,
        "ordered_suggestion": compact_suggestion,
        "pattern_count": int(normalized_payload["pattern_count"]),
        "unique_numbers": int(len(compact_suggestion)),
        "selected_number_details": compact_details,
        "entry_shadow": dict(normalized_payload["entry_shadow"]),
        "evaluation_window_attempts": 3,
        "explanation": (
            "Oscillation selective compact v4 ativa. "
            f"origem={hold_origin} alvo={target_block['label']} move={predicted_move} "
            f"hold_restante={remaining_after}/{safe_hold_rounds} compact_size={compact_limit}."
        ),
        "oscillation": {
            **target,
            "profile": "oscillation_v4_selective_compact",
            "selective_gate": dict(selective_gate),
            "compact_hold": {
                "active": remaining_after > 0,
                "origin": hold_origin,
                "rounds_remaining": remaining_after,
                "rounds_total": safe_hold_rounds,
                "target_block_index": int(target_block_index),
                "target_block_label": str(target_block["label"]),
                "predicted_move": predicted_move,
                "compact_size": compact_limit,
            },
            "source_base_event_id": last_event_id,
            "recent_base_ranks": [int(rank) for rank in recent_ranks[:8]],
        },
        **summary,
    }


def build_shadow_variant_resolution_fields(
    event_doc: Mapping[str, Any],
    result_doc: Mapping[str, Any],
    *,
    attempt_number: int,
) -> Dict[str, Any]:
    raw_variants = event_doc.get("shadow_variants")
    if not isinstance(raw_variants, Mapping):
        return {}

    result_number = int(result_doc["value"])
    result_history_id = str(result_doc["history_id"])
    result_timestamp = ensure_utc_datetime(result_doc["history_timestamp_utc"])
    updated_variants: Dict[str, Any] = {}

    for variant_key, raw_variant in raw_variants.items():
        if not isinstance(raw_variant, Mapping):
            continue
        variant = dict(raw_variant)
        if not bool(variant.get("available", False)):
            updated_variants[str(variant_key)] = variant
            continue
        if str(variant.get("status") or "").strip().lower() == "resolved":
            updated_variants[str(variant_key)] = variant
            continue

        suggestion = _normalize_suggestion(variant.get("suggestion") or [])
        variant["attempts_elapsed"] = attempt_number
        if result_number not in suggestion:
            updated_variants[str(variant_key)] = variant
            continue

        rank_position = suggestion.index(result_number) + 1
        detail = next(
            (
                item
                for item in (variant.get("selected_number_details") or [])
                if isinstance(item, Mapping) and _safe_int(item.get("number"), -1) == result_number
            ),
            None,
        )
        variant.update(
            {
                "status": "resolved",
                "resolved_attempt": attempt_number,
                "resolved_history_id": result_history_id,
                "resolved_number": result_number,
                "resolved_rank_position": rank_position,
                "resolved_support_score": _safe_int(detail.get("support_score"), 0) if isinstance(detail, Mapping) else 0,
                "resolved_weighted_support_score": round(
                    _safe_float(detail.get("weighted_support_score"), 0.0),
                    6,
                )
                if isinstance(detail, Mapping)
                else 0.0,
                "resolved_timestamp_utc": result_timestamp,
                "resolved_timestamp_br": result_timestamp.astimezone(BR_TZ),
                "hit_within_1": attempt_number <= 1,
                "hit_within_4": attempt_number <= 4,
                "hit_within_8": attempt_number <= 8,
                "hit_within_16": attempt_number <= 16,
            }
        )
        updated_variants[str(variant_key)] = variant

    return updated_variants


def build_pattern_candidates(selected_number_details: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_pattern: Dict[str, Dict[str, Any]] = {}
    for rank_position, detail in enumerate(selected_number_details, start=1):
        number = int(detail.get("number"))
        for raw_pattern in detail.get("supporting_patterns") or []:
            pattern_id = str(raw_pattern.get("pattern_id") or "").strip()
            if not pattern_id:
                continue
            current = by_pattern.setdefault(
                pattern_id,
                {
                    "pattern_id": pattern_id,
                    "base_pattern_id": str(raw_pattern.get("base_pattern_id") or pattern_id).strip() or pattern_id,
                    "pattern_name": str(raw_pattern.get("pattern_name") or pattern_id).strip() or pattern_id,
                    "applied_weight": round(_safe_float(raw_pattern.get("applied_weight"), 1.0), 6),
                    "supported_numbers": [],
                    "supported_rank_positions": [],
                },
            )
            if number not in current["supported_numbers"]:
                current["supported_numbers"].append(number)
            if rank_position not in current["supported_rank_positions"]:
                current["supported_rank_positions"].append(rank_position)

    candidates = []
    for item in by_pattern.values():
        item["supported_numbers"] = sorted(int(n) for n in item["supported_numbers"])
        item["supported_rank_positions"] = sorted(int(p) for p in item["supported_rank_positions"])
        item["supported_count"] = len(item["supported_numbers"])
        candidates.append(item)
    candidates.sort(key=lambda row: (-row["supported_count"], row["pattern_name"], row["pattern_id"]))
    return candidates


def build_monitor_event_document(
    *,
    anchor_doc: Mapping[str, Any],
    simple_payload: Mapping[str, Any] | None,
    history_values: List[int],
    config_key: str,
    ranking_variant: str = "base_v1",
    source_base_event_id: str | None = None,
    source_base_config_key: str | None = None,
    suggestion_type: str = "simple_http",
    status_override: str | None = None,
    error_message: str | None = None,
    shadow_compare_max_numbers: int | None = None,
) -> Dict[str, Any]:
    anchor = dict(anchor_doc)
    anchor_timestamp = ensure_utc_datetime(anchor["history_timestamp_utc"])
    history_id = str(anchor["history_id"])
    roulette_id = str(anchor["roulette_id"])
    roulette_name = str(anchor["roulette_name"])
    payload = dict(simple_payload or {})

    suggestion = _normalize_suggestion(payload.get("list") or payload.get("suggestion") or [])
    selected_number_details = _normalize_selected_number_details(payload)
    shadow_variants = _build_shadow_variants(
        payload=payload,
        base_suggestion=suggestion,
        selected_number_details=selected_number_details,
        compare_max_numbers=int(shadow_compare_max_numbers or 0),
    )
    pattern_candidates = build_pattern_candidates(selected_number_details)
    entry_shadow = payload.get("entry_shadow")
    if not isinstance(entry_shadow, Mapping):
        entry_shadow = {}
    evaluation_window_attempts = _safe_int(payload.get("evaluation_window_attempts"), 0)
    oscillation = dict(payload.get("oscillation") or {}) if isinstance(payload.get("oscillation"), Mapping) else {}

    available = bool(payload.get("available", False)) and bool(suggestion)
    status = (
        str(status_override).strip()
        if status_override
        else ("pending" if available else "unavailable")
    )
    explanation = str(error_message or payload.get("explanation") or "").strip()
    event_id = build_event_id(history_id, config_key)
    document = {
        "_id": event_id,
        "event_type": "suggestion_monitor_event",
        "monitor_version": 1,
        "config_key": config_key,
        "ranking_variant": str(ranking_variant or "base_v1").strip() or "base_v1",
        "ranking_source_variant": "base_v1" if str(ranking_variant or "base_v1").strip() != "base_v1" else None,
        "source_base_event_id": str(source_base_event_id or "").strip() or None,
        "source_base_config_key": str(source_base_config_key or "").strip() or None,
        "suggestion_type": suggestion_type,
        "roulette_id": roulette_id,
        "roulette_name": roulette_name,
        "anchor_history_id": history_id,
        "anchor_number": int(anchor["value"]),
        **build_time_fields("anchor", anchor_timestamp),
        "history_window_size": len(history_values),
        "history_head": list(history_values[:30]),
        "history_signature": list(history_values[:8]),
        "available": available,
        "status": status,
        "explanation": explanation,
        "suggestion": list(suggestion),
        "ordered_suggestion": list(suggestion),
        "suggestion_size": len(suggestion),
        "pattern_count": _safe_int(payload.get("pattern_count"), 0),
        "unique_numbers": _safe_int(payload.get("unique_numbers"), 0),
        "top_support_count": _safe_int(payload.get("top_support_count"), 0),
        "avg_support_count": round(_safe_float(payload.get("avg_support_count"), 0.0), 4),
        "min_support_count": _safe_int(payload.get("min_support_count"), 0),
        "top_weighted_support_score": round(_safe_float(payload.get("top_weighted_support_score"), 0.0), 6),
        "avg_weighted_support_score": round(_safe_float(payload.get("avg_weighted_support_score"), 0.0), 6),
        "min_weighted_support_score": round(_safe_float(payload.get("min_weighted_support_score"), 0.0), 6),
        "selected_number_details": selected_number_details,
        "shadow_variants": shadow_variants,
        "pattern_candidates": pattern_candidates,
        "entry_shadow": dict(entry_shadow),
        "oscillation": oscillation,
        "evaluation_window_attempts": evaluation_window_attempts if evaluation_window_attempts > 0 else None,
        "window_result_status": "pending" if (available and evaluation_window_attempts > 0) else None,
        "window_result_finalized": False,
        "window_result_hit": None,
        "window_result_attempt": None,
        "window_result_number": None,
        "window_result_timestamp_utc": None,
        "attempts_elapsed": 0,
        "last_attempt_history_id": None,
        "last_attempt_number": 0,
        "last_result_number": None,
        "last_result_timestamp_utc": None,
        "resolved_attempt": None,
        "resolved_history_id": None,
        "resolved_number": None,
        "resolved_rank_position": None,
        "resolved_support_score": None,
        "resolved_weighted_support_score": None,
        "resolved_after_seconds": None,
        "hit_supporting_patterns": [],
        "hit_pattern_ids": [],
        "hit_within_1": False,
        "hit_within_4": False,
        "hit_within_8": False,
        "hit_within_16": False,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    if status == "generation_error":
        document["generation_error"] = explanation or "Erro ao gerar sugestao."
    return document


def build_pattern_outcome_documents(event_doc: Mapping[str, Any]) -> List[Dict[str, Any]]:
    pattern_candidates = event_doc.get("pattern_candidates")
    if not isinstance(pattern_candidates, list):
        return []

    now = datetime.now(timezone.utc)
    documents: List[Dict[str, Any]] = []
    for candidate in pattern_candidates:
        if not isinstance(candidate, Mapping):
            continue
        pattern_id = str(candidate.get("pattern_id") or "").strip()
        if not pattern_id:
            continue
        documents.append(
            {
                "_id": f"{event_doc['_id']}:pattern:{pattern_id}",
                "event_type": "suggestion_monitor_pattern_outcome",
                "monitor_version": 1,
                "suggestion_event_id": str(event_doc["_id"]),
                "roulette_id": str(event_doc["roulette_id"]),
                "roulette_name": str(event_doc["roulette_name"]),
                "anchor_history_id": str(event_doc["anchor_history_id"]),
                "anchor_number": int(event_doc["anchor_number"]),
                "anchor_timestamp_utc": event_doc["anchor_timestamp_utc"],
                "anchor_timestamp_br": event_doc["anchor_timestamp_br"],
                "pattern_id": pattern_id,
                "base_pattern_id": str(candidate.get("base_pattern_id") or pattern_id),
                "pattern_name": str(candidate.get("pattern_name") or pattern_id),
                "applied_weight": round(_safe_float(candidate.get("applied_weight"), 1.0), 6),
                "supported_numbers": [int(n) for n in candidate.get("supported_numbers") or []],
                "supported_rank_positions": [int(p) for p in candidate.get("supported_rank_positions") or []],
                "supported_count": _safe_int(candidate.get("supported_count"), 0),
                "status": str(event_doc.get("status") or "pending"),
                "covered_hit": False,
                "resolved_attempt": None,
                "resolved_number": None,
                "resolved_rank_position": None,
                "resolved_timestamp_utc": None,
                "created_at": now,
                "updated_at": now,
            }
        )
    return documents


def build_attempt_document(
    event_doc: Mapping[str, Any],
    result_doc: Mapping[str, Any],
) -> Dict[str, Any]:
    suggestion = _normalize_suggestion(event_doc.get("suggestion") or [])
    result_number = int(result_doc["value"])
    attempt_number = _safe_int(event_doc.get("attempts_elapsed"), 0) + 1
    rank_position = None
    if result_number in suggestion:
        rank_position = suggestion.index(result_number) + 1
    detail = next(
        (
            item
            for item in (event_doc.get("selected_number_details") or [])
            if isinstance(item, Mapping) and _safe_int(item.get("number"), -1) == result_number
        ),
        None,
    )
    hit_patterns = []
    if isinstance(detail, Mapping):
        hit_patterns = [dict(item) for item in (detail.get("supporting_patterns") or []) if isinstance(item, Mapping)]
    attempt_id = f"{event_doc['_id']}:result:{result_doc['history_id']}"
    attempt_doc = {
        "_id": attempt_id,
        "event_type": "suggestion_monitor_attempt",
        "monitor_version": 1,
        "suggestion_event_id": str(event_doc["_id"]),
        "roulette_id": str(event_doc["roulette_id"]),
        "roulette_name": str(event_doc["roulette_name"]),
        "anchor_history_id": str(event_doc["anchor_history_id"]),
        "anchor_number": int(event_doc["anchor_number"]),
        "attempt_number": attempt_number,
        "result_history_id": str(result_doc["history_id"]),
        "result_number": result_number,
        **build_time_fields("result", ensure_utc_datetime(result_doc["history_timestamp_utc"])),
        "is_hit": rank_position is not None,
        "hit_rank_position": rank_position,
        "support_score": _safe_int(detail.get("support_score"), 0) if isinstance(detail, Mapping) else 0,
        "weighted_support_score": round(_safe_float(detail.get("weighted_support_score"), 0.0), 6)
        if isinstance(detail, Mapping)
        else 0.0,
        "patterns_covering_result": hit_patterns,
        "created_at": datetime.now(timezone.utc),
    }
    return attempt_doc


def build_event_resolution_fields(
    event_doc: Mapping[str, Any],
    attempt_doc: Mapping[str, Any],
) -> Dict[str, Any]:
    result_timestamp = ensure_utc_datetime(attempt_doc["result_timestamp_utc"])
    anchor_timestamp = ensure_utc_datetime(event_doc["anchor_timestamp_utc"])
    attempt_number = int(attempt_doc["attempt_number"])
    result_number = int(attempt_doc["result_number"])
    is_hit = bool(attempt_doc.get("is_hit", False))
    fields: Dict[str, Any] = {
        "attempts_elapsed": attempt_number,
        "last_attempt_history_id": str(attempt_doc["result_history_id"]),
        "last_attempt_number": attempt_number,
        "last_result_number": result_number,
        "last_result_timestamp_utc": result_timestamp,
        "updated_at": datetime.now(timezone.utc),
    }
    if is_hit:
        fields.update(
            {
                "status": "resolved",
                "resolved_attempt": attempt_number,
                "resolved_history_id": str(attempt_doc["result_history_id"]),
                "resolved_number": result_number,
                "resolved_rank_position": _safe_int(attempt_doc.get("hit_rank_position"), 0) or None,
                "resolved_support_score": _safe_int(attempt_doc.get("support_score"), 0),
                "resolved_weighted_support_score": round(_safe_float(attempt_doc.get("weighted_support_score"), 0.0), 6),
                "resolved_after_seconds": max(0.0, round((result_timestamp - anchor_timestamp).total_seconds(), 3)),
                "hit_supporting_patterns": [dict(item) for item in (attempt_doc.get("patterns_covering_result") or [])],
                "hit_pattern_ids": [
                    str(item.get("pattern_id") or "").strip()
                    for item in (attempt_doc.get("patterns_covering_result") or [])
                    if isinstance(item, Mapping) and str(item.get("pattern_id") or "").strip()
                ],
                "hit_within_1": attempt_number <= 1,
                "hit_within_4": attempt_number <= 4,
                "hit_within_8": attempt_number <= 8,
                "hit_within_16": attempt_number <= 16,
                **build_time_fields("resolved", result_timestamp),
            }
        )
    window_limit = _safe_int(event_doc.get("evaluation_window_attempts"), 0)
    current_window_status = str(event_doc.get("window_result_status") or "").strip().lower()
    if window_limit > 0 and current_window_status not in {"hit", "miss"}:
        if is_hit and attempt_number <= window_limit:
            fields.update(
                {
                    "window_result_status": "hit",
                    "window_result_finalized": True,
                    "window_result_hit": True,
                    "window_result_attempt": attempt_number,
                    "window_result_number": result_number,
                    "window_result_timestamp_utc": result_timestamp,
                }
            )
        elif (not is_hit) and attempt_number >= window_limit:
            fields.update(
                {
                    "status": "resolved",
                    "window_result_status": "miss",
                    "window_result_finalized": True,
                    "window_result_hit": False,
                    "window_result_attempt": window_limit,
                    "window_result_number": None,
                    "window_result_timestamp_utc": result_timestamp,
                }
            )
    return fields


def build_pattern_resolution_documents(
    event_doc: Mapping[str, Any],
    attempt_doc: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    if not bool(attempt_doc.get("is_hit", False)):
        return []

    hit_pattern_ids = {
        str(item.get("pattern_id") or "").strip()
        for item in (attempt_doc.get("patterns_covering_result") or [])
        if isinstance(item, Mapping) and str(item.get("pattern_id") or "").strip()
    }
    resolved_attempt = int(attempt_doc["attempt_number"])
    resolved_number = int(attempt_doc["result_number"])
    resolved_rank_position = _safe_int(attempt_doc.get("hit_rank_position"), 0) or None
    resolved_timestamp = ensure_utc_datetime(attempt_doc["result_timestamp_utc"])

    docs = []
    for candidate in event_doc.get("pattern_candidates") or []:
        if not isinstance(candidate, Mapping):
            continue
        pattern_id = str(candidate.get("pattern_id") or "").strip()
        if not pattern_id:
            continue
        docs.append(
            {
                "_id": f"{event_doc['_id']}:pattern:{pattern_id}",
                "status": "resolved",
                "covered_hit": pattern_id in hit_pattern_ids,
                "resolved_attempt": resolved_attempt,
                "resolved_number": resolved_number,
                "resolved_rank_position": resolved_rank_position,
                "resolved_timestamp_utc": resolved_timestamp,
                "updated_at": datetime.now(timezone.utc),
            }
        )
    return docs
