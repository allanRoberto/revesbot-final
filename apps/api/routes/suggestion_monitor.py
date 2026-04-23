from __future__ import annotations

from datetime import datetime
import json
import os
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query

from api.core.db import (
    ensure_suggestion_monitor_indexes,
    suggestion_monitor_attempts_coll,
    suggestion_monitor_events_coll,
    suggestion_monitor_offsets_coll,
    suggestion_monitor_pattern_outcomes_coll,
)
from api.core.redis_client import get_redis_client


router = APIRouter()
redis_client = get_redis_client()
SUGGESTION_MONITOR_CONTROL_CHANNEL = (
    os.getenv("SUGGESTION_MONITOR_CONTROL_CHANNEL", "suggestion_monitor_control").strip()
    or "suggestion_monitor_control"
)
DEFAULT_MONITOR_RANK_CEILING = max(
    1,
    min(37, int(os.getenv("SUGGESTION_MONITOR_MAX_NUMBERS", "37") or "37")),
)
DEFAULT_ANALYTICS_WINDOWS = (50, 100, 200)
DEFAULT_GATE_CALIBRATION_LIMIT = 400


def _build_base_filter(roulette_id: str, config_key: str | None = None) -> Dict[str, Any]:
    filter_query: Dict[str, Any] = {"roulette_id": roulette_id}
    if config_key:
        filter_query["config_key"] = config_key
    return filter_query


def _normalize_hour(value: int | None) -> int | None:
    if value is None:
        return None
    try:
        hour = int(value)
    except (TypeError, ValueError):
        return None
    if 0 <= hour <= 23:
        return hour
    return None


async def _ensure_monitor_indexes() -> None:
    await ensure_suggestion_monitor_indexes()


def _variant_field_paths(ranking_variant: str | None = None) -> Dict[str, Any]:
    variant = str(ranking_variant or "base").strip().lower()
    if variant in {"compact", "oscillation_v4_selective_compact", "selective_compact_v4"}:
        return {
            "key": "oscillation_v4_selective_compact",
            "status": "status",
            "resolved_attempt": "resolved_attempt",
            "resolved_rank_position": "resolved_rank_position",
            "resolved_number": "resolved_number",
            "resolved_timestamp_br": "resolved_timestamp_br",
            "attempts_elapsed": "attempts_elapsed",
            "variant_filter": {"ranking_variant": "oscillation_v4_selective_compact"},
            "projection": {
                "anchor_number": 1,
                "anchor_timestamp_br": 1,
                "anchor_timestamp_utc": 1,
                "resolved_number": 1,
                "resolved_attempt": 1,
                "resolved_rank_position": 1,
                "suggestion_size": 1,
                "window_result_status": 1,
                "window_result_attempt": 1,
                "window_result_hit": 1,
            },
            "label": "oscillation_v4_selective_compact",
            "rank_ceiling": 18,
        }
    if variant in {"temporal", "temporal_blend", "temporal_blend_v1"}:
        return {
            "key": "temporal_blend_v1",
            "status": "status",
            "resolved_attempt": "resolved_attempt",
            "resolved_rank_position": "resolved_rank_position",
            "resolved_number": "resolved_number",
            "resolved_timestamp_br": "resolved_timestamp_br",
            "attempts_elapsed": "attempts_elapsed",
            "variant_filter": {"ranking_variant": "temporal_blend_v1"},
            "projection": {
                "anchor_number": 1,
                "anchor_timestamp_br": 1,
                "anchor_timestamp_utc": 1,
                "resolved_number": 1,
                "resolved_attempt": 1,
                "resolved_rank_position": 1,
                "suggestion_size": 1,
            },
            "label": "temporal_blend_v1",
            "rank_ceiling": DEFAULT_MONITOR_RANK_CEILING,
        }
    if variant in {"time_window_prior", "time_window_prior_v1", "temporal_window_prior"}:
        return {
            "key": "time_window_prior_v1",
            "status": "status",
            "resolved_attempt": "resolved_attempt",
            "resolved_rank_position": "resolved_rank_position",
            "resolved_number": "resolved_number",
            "resolved_timestamp_br": "resolved_timestamp_br",
            "attempts_elapsed": "attempts_elapsed",
            "variant_filter": {"ranking_variant": "time_window_prior_v1"},
            "projection": {
                "anchor_number": 1,
                "anchor_timestamp_br": 1,
                "anchor_timestamp_utc": 1,
                "resolved_number": 1,
                "resolved_attempt": 1,
                "resolved_rank_position": 1,
                "suggestion_size": 1,
            },
            "label": "time_window_prior_v1",
            "rank_ceiling": DEFAULT_MONITOR_RANK_CEILING,
        }
    if variant in {"top26", "ranking_v2_top26", "top_26_v2"}:
        return {
            "key": "ranking_v2_top26",
            "status": "status",
            "resolved_attempt": "resolved_attempt",
            "resolved_rank_position": "resolved_rank_position",
            "resolved_number": "resolved_number",
            "resolved_timestamp_br": "resolved_timestamp_br",
            "attempts_elapsed": "attempts_elapsed",
            "variant_filter": {"ranking_variant": "ranking_v2_top26"},
            "projection": {
                "anchor_number": 1,
                "anchor_timestamp_br": 1,
                "anchor_timestamp_utc": 1,
                "resolved_number": 1,
                "resolved_attempt": 1,
                "resolved_rank_position": 1,
                "suggestion_size": 1,
            },
            "label": "ranking_v2_top26",
            "rank_ceiling": DEFAULT_MONITOR_RANK_CEILING,
        }
    if variant in {"ml", "ml_meta_rank", "ml_meta_rank_v1", "meta_rank_ml"}:
        return {
            "key": "ml_meta_rank_v1",
            "status": "status",
            "resolved_attempt": "resolved_attempt",
            "resolved_rank_position": "resolved_rank_position",
            "resolved_number": "resolved_number",
            "resolved_timestamp_br": "resolved_timestamp_br",
            "attempts_elapsed": "attempts_elapsed",
            "variant_filter": {"ranking_variant": "ml_meta_rank_v1"},
            "projection": {
                "anchor_number": 1,
                "anchor_timestamp_br": 1,
                "anchor_timestamp_utc": 1,
                "resolved_number": 1,
                "resolved_attempt": 1,
                "resolved_rank_position": 1,
                "suggestion_size": 1,
            },
            "label": "ml_meta_rank_v1",
            "rank_ceiling": DEFAULT_MONITOR_RANK_CEILING,
        }
    if variant in {"ml_top12_reference", "ml_top12_reference_12x4_v1", "ml_reference_12x4"}:
        return {
            "key": "ml_top12_reference_12x4_v1",
            "status": "status",
            "resolved_attempt": "resolved_attempt",
            "resolved_rank_position": "resolved_rank_position",
            "resolved_number": "resolved_number",
            "resolved_timestamp_br": "resolved_timestamp_br",
            "attempts_elapsed": "attempts_elapsed",
            "variant_filter": {"ranking_variant": "ml_top12_reference_12x4_v1"},
            "projection": {
                "anchor_number": 1,
                "anchor_timestamp_br": 1,
                "anchor_timestamp_utc": 1,
                "resolved_number": 1,
                "resolved_attempt": 1,
                "resolved_rank_position": 1,
                "suggestion_size": 1,
                "window_result_status": 1,
                "window_result_attempt": 1,
                "window_result_hit": 1,
                "suggestion": 1,
            },
            "label": "ml_top12_reference_12x4_v1",
            "rank_ceiling": 12,
        }
    if variant in {"ml_entry_gate", "ml_entry_gate_12x4_v1", "entry_gate_ml_12x4"}:
        return {
            "key": "ml_entry_gate_12x4_v1",
            "status": "status",
            "resolved_attempt": "resolved_attempt",
            "resolved_rank_position": "resolved_rank_position",
            "resolved_number": "resolved_number",
            "resolved_timestamp_br": "resolved_timestamp_br",
            "attempts_elapsed": "attempts_elapsed",
            "variant_filter": {"ranking_variant": "ml_entry_gate_12x4_v1"},
            "projection": {
                "anchor_number": 1,
                "anchor_timestamp_br": 1,
                "anchor_timestamp_utc": 1,
                "resolved_number": 1,
                "resolved_attempt": 1,
                "resolved_rank_position": 1,
                "suggestion_size": 1,
                "window_result_status": 1,
                "window_result_attempt": 1,
                "window_result_hit": 1,
                "suggestion": 1,
            },
            "label": "ml_entry_gate_12x4_v1",
            "rank_ceiling": 12,
        }
    if variant in {"top26_selective", "top26_selective_16x4_v1", "strategy_16x4"}:
        return {
            "key": "top26_selective_16x4_v1",
            "status": "status",
            "resolved_attempt": "resolved_attempt",
            "resolved_rank_position": "resolved_rank_position",
            "resolved_number": "resolved_number",
            "resolved_timestamp_br": "resolved_timestamp_br",
            "attempts_elapsed": "attempts_elapsed",
            "variant_filter": {"ranking_variant": "top26_selective_16x4_v1"},
            "projection": {
                "anchor_number": 1,
                "anchor_timestamp_br": 1,
                "anchor_timestamp_utc": 1,
                "resolved_number": 1,
                "resolved_attempt": 1,
                "resolved_rank_position": 1,
                "suggestion_size": 1,
                "window_result_status": 1,
                "window_result_attempt": 1,
                "window_result_hit": 1,
                "suggestion": 1,
            },
            "label": "top26_selective_16x4_v1",
            "rank_ceiling": 16,
        }
    if variant in {"top26_selective_dynamic", "top26_selective_16x4_dynamic_v1", "strategy_16x4_dynamic"}:
        return {
            "key": "top26_selective_16x4_dynamic_v1",
            "status": "status",
            "resolved_attempt": "resolved_attempt",
            "resolved_rank_position": "resolved_rank_position",
            "resolved_number": "resolved_number",
            "resolved_timestamp_br": "resolved_timestamp_br",
            "attempts_elapsed": "attempts_elapsed",
            "variant_filter": {"ranking_variant": "top26_selective_16x4_dynamic_v1"},
            "projection": {
                "anchor_number": 1,
                "anchor_timestamp_br": 1,
                "anchor_timestamp_utc": 1,
                "resolved_number": 1,
                "resolved_attempt": 1,
                "resolved_rank_position": 1,
                "suggestion_size": 1,
                "window_result_status": 1,
                "window_result_attempt": 1,
                "window_result_hit": 1,
                "suggestion": 1,
            },
            "label": "top26_selective_16x4_dynamic_v1",
            "rank_ceiling": 16,
        }
    if variant in {"selective_protected", "oscillation_v3_selective_protected", "selective_protection_v3"}:
        return {
            "key": "oscillation_v3_selective_protected",
            "status": "status",
            "resolved_attempt": "resolved_attempt",
            "resolved_rank_position": "resolved_rank_position",
            "resolved_number": "resolved_number",
            "resolved_timestamp_br": "resolved_timestamp_br",
            "attempts_elapsed": "attempts_elapsed",
            "variant_filter": {"ranking_variant": "oscillation_v3_selective_protected"},
            "projection": {
                "anchor_number": 1,
                "anchor_timestamp_br": 1,
                "anchor_timestamp_utc": 1,
                "resolved_number": 1,
                "resolved_attempt": 1,
                "resolved_rank_position": 1,
                "suggestion_size": 1,
            },
            "label": "oscillation_v3_selective_protected",
            "rank_ceiling": DEFAULT_MONITOR_RANK_CEILING,
        }
    if variant in {"selective", "oscillation_v3_selective", "selective_v3"}:
        return {
            "key": "oscillation_v3_selective",
            "status": "status",
            "resolved_attempt": "resolved_attempt",
            "resolved_rank_position": "resolved_rank_position",
            "resolved_number": "resolved_number",
            "resolved_timestamp_br": "resolved_timestamp_br",
            "attempts_elapsed": "attempts_elapsed",
            "variant_filter": {"ranking_variant": "oscillation_v3_selective"},
            "projection": {
                "anchor_number": 1,
                "anchor_timestamp_br": 1,
                "anchor_timestamp_utc": 1,
                "resolved_number": 1,
                "resolved_attempt": 1,
                "resolved_rank_position": 1,
                "suggestion_size": 1,
            },
            "label": "oscillation_v3_selective",
            "rank_ceiling": DEFAULT_MONITOR_RANK_CEILING,
        }
    if variant in {"aggressive", "oscillation_v2_aggressive", "aggressive_v2"}:
        return {
            "key": "oscillation_v2_aggressive",
            "status": "status",
            "resolved_attempt": "resolved_attempt",
            "resolved_rank_position": "resolved_rank_position",
            "resolved_number": "resolved_number",
            "resolved_timestamp_br": "resolved_timestamp_br",
            "attempts_elapsed": "attempts_elapsed",
            "variant_filter": {"ranking_variant": "oscillation_v2_aggressive"},
            "projection": {
                "anchor_number": 1,
                "anchor_timestamp_br": 1,
                "anchor_timestamp_utc": 1,
                "resolved_number": 1,
                "resolved_attempt": 1,
                "resolved_rank_position": 1,
                "suggestion_size": 1,
            },
            "label": "oscillation_v2_aggressive",
            "rank_ceiling": DEFAULT_MONITOR_RANK_CEILING,
        }
    if variant in {"optimized", "oscillation", "oscillation_v1"}:
        return {
            "key": "oscillation_v1",
            "status": "status",
            "resolved_attempt": "resolved_attempt",
            "resolved_rank_position": "resolved_rank_position",
            "resolved_number": "resolved_number",
            "resolved_timestamp_br": "resolved_timestamp_br",
            "attempts_elapsed": "attempts_elapsed",
            "variant_filter": {"ranking_variant": "oscillation_v1"},
            "projection": {
                "anchor_number": 1,
                "anchor_timestamp_br": 1,
                "anchor_timestamp_utc": 1,
                "resolved_number": 1,
                "resolved_attempt": 1,
                "resolved_rank_position": 1,
                "suggestion_size": 1,
            },
            "label": "oscillation_v1",
            "rank_ceiling": DEFAULT_MONITOR_RANK_CEILING,
        }
    return {
        "key": "base_v1",
        "status": "status",
        "resolved_attempt": "resolved_attempt",
        "resolved_rank_position": "resolved_rank_position",
        "resolved_number": "resolved_number",
        "resolved_timestamp_br": "resolved_timestamp_br",
        "attempts_elapsed": "attempts_elapsed",
        "variant_filter": {
            "$or": [
                {"ranking_variant": "base_v1"},
                {"ranking_variant": {"$exists": False}},
            ]
        },
        "projection": {
            "anchor_number": 1,
            "anchor_timestamp_br": 1,
            "anchor_timestamp_utc": 1,
            "resolved_number": 1,
            "resolved_attempt": 1,
            "resolved_rank_position": 1,
            "suggestion_size": 1,
        },
        "label": "base_v1",
        "rank_ceiling": DEFAULT_MONITOR_RANK_CEILING,
    }


def _resolve_rank_ceiling(paths: Dict[str, Any], docs: List[Dict[str, Any]]) -> int:
    fallback = max(1, int(paths.get("rank_ceiling") or DEFAULT_MONITOR_RANK_CEILING))
    sizes = [
        max(1, min(37, int(doc.get("suggestion_size") or 0)))
        for doc in docs
        if int(doc.get("suggestion_size") or 0) > 0
    ]
    if not sizes:
        return fallback
    return max(fallback, max(sizes)) if paths.get("label") == "oscillation_v4_selective_compact" else max(sizes)


def _build_event_filter(
    *,
    roulette_id: str,
    config_key: str | None = None,
    status: str | None = None,
    attempt_filter: str | None = None,
    ranking_variant: str | None = None,
    shadow_action: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    start_hour: int | None = None,
    end_hour: int | None = None,
) -> Dict[str, Any]:
    paths = _variant_field_paths(ranking_variant)
    conditions: List[Dict[str, Any]] = [_build_base_filter(roulette_id, config_key)]
    if paths["variant_filter"]:
        conditions.append(dict(paths["variant_filter"]))

    clean_status = str(status or "").strip().lower()
    if clean_status:
        conditions.append({str(paths["status"]): clean_status})

    clean_attempt = str(attempt_filter or "").strip().lower()
    if clean_attempt:
        if clean_attempt.isdigit():
            conditions.append(
                {
                    str(paths["status"]): "resolved",
                    str(paths["resolved_attempt"]): int(clean_attempt),
                }
            )
        elif clean_attempt in {"pending", "resolved", "generation_error", "unavailable"}:
            conditions.append({str(paths["status"]): clean_attempt})

    clean_shadow_action = str(shadow_action or "").strip().lower()
    if clean_shadow_action in {"enter", "wait", "skip"}:
        conditions.append({"entry_shadow.recommendation.action": clean_shadow_action})

    date_condition: Dict[str, Any] = {}
    if start_date:
        date_condition["$gte"] = str(start_date)
    if end_date:
        date_condition["$lte"] = str(end_date)
    if date_condition:
        conditions.append({"anchor_date_br": date_condition})

    start_hour_value = _normalize_hour(start_hour)
    end_hour_value = _normalize_hour(end_hour)
    if start_hour_value is not None or end_hour_value is not None:
        if start_hour_value is not None and end_hour_value is not None:
            if start_hour_value <= end_hour_value:
                conditions.append({"anchor_hour_br": {"$gte": start_hour_value, "$lte": end_hour_value}})
            else:
                conditions.append(
                    {
                        "$or": [
                            {"anchor_hour_br": {"$gte": start_hour_value}},
                            {"anchor_hour_br": {"$lte": end_hour_value}},
                        ]
                    }
                )
        elif start_hour_value is not None:
            conditions.append({"anchor_hour_br": {"$gte": start_hour_value}})
        elif end_hour_value is not None:
            conditions.append({"anchor_hour_br": {"$lte": end_hour_value}})

    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def _serialize_datetime(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _round_or_none(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _merge_filter_with_condition(filter_query: Dict[str, Any], condition: Dict[str, Any]) -> Dict[str, Any]:
    if not filter_query:
        return dict(condition)
    merged = dict(filter_query)
    merged.update(condition)
    return merged


def _parse_window_sizes(raw_value: str | None) -> List[int]:
    if not str(raw_value or "").strip():
        return list(DEFAULT_ANALYTICS_WINDOWS)
    windows: List[int] = []
    seen: set[int] = set()
    for chunk in str(raw_value).split(","):
        try:
            value = int(str(chunk).strip())
        except (TypeError, ValueError):
            continue
        if value < 10 or value > 1000 or value in seen:
            continue
        seen.add(value)
        windows.append(value)
    return windows or list(DEFAULT_ANALYTICS_WINDOWS)


def _extract_ml_gate_context(doc: Dict[str, Any]) -> Dict[str, Any]:
    entry_shadow = dict(doc.get("entry_shadow") or {}) if isinstance(doc.get("entry_shadow"), dict) else {}
    recommendation = (
        dict(entry_shadow.get("recommendation") or {})
        if isinstance(entry_shadow.get("recommendation"), dict)
        else {}
    )
    oscillation = dict(doc.get("oscillation") or {}) if isinstance(doc.get("oscillation"), dict) else {}
    ml_entry_gate = (
        dict(oscillation.get("ml_entry_gate") or {})
        if isinstance(oscillation.get("ml_entry_gate"), dict)
        else {}
    )
    probability = ml_entry_gate.get("probability")
    threshold = ml_entry_gate.get("threshold")
    return {
        "gate_action": str(recommendation.get("action") or "").strip(),
        "gate_label": str(recommendation.get("label") or "").strip(),
        "gate_reason": str(recommendation.get("reason") or "").strip(),
        "gate_probability": round(_safe_float(probability), 6) if probability is not None else None,
        "gate_threshold": round(_safe_float(threshold), 6) if threshold is not None else None,
        "gate_should_enter": (
            bool(ml_entry_gate.get("should_enter"))
            if "should_enter" in ml_entry_gate
            else None
        ),
        "gate_trained_events": (
            int(ml_entry_gate.get("trained_events") or 0)
            if "trained_events" in ml_entry_gate
            else None
        ),
        "gate_warmup_events": (
            int(ml_entry_gate.get("warmup_events") or 0)
            if "warmup_events" in ml_entry_gate
            else None
        ),
        "gate_warmup_required": (
            int(ml_entry_gate.get("warmup_required") or 0)
            if "warmup_required" in ml_entry_gate
            else None
        ),
        "gate_warmup_ready": (
            bool(ml_entry_gate.get("warmup_ready"))
            if "warmup_ready" in ml_entry_gate
            else None
        ),
    }


def _event_summary(doc: Dict[str, Any]) -> str:
    status = str(doc.get("status") or "").strip().lower()
    anchor = doc.get("anchor_number")
    if status == "resolved":
        attempt = int(doc.get("resolved_attempt") or 0)
        result = doc.get("resolved_number")
        rank = doc.get("resolved_rank_position")
        if rank:
            return f"Ancora {anchor} acertou no numero {result} em {attempt} tiro(s), posicao {rank} da lista."
        return f"Ancora {anchor} acertou no numero {result} em {attempt} tiro(s)."
    if status == "pending":
        attempts_elapsed = int(doc.get("attempts_elapsed") or 0)
        return f"Ancora {anchor} segue pendente apos {attempts_elapsed} giro(s) observados."
    if status == "generation_error":
        return str(doc.get("generation_error") or doc.get("explanation") or "Falha ao gerar sugestao.")
    if status == "unavailable":
        return str(doc.get("explanation") or "Sugestao indisponivel.")
    return str(doc.get("explanation") or f"Evento da ancora {anchor}.")


def _format_latest_event(doc: Dict[str, Any]) -> Dict[str, Any]:
    entry_shadow = doc.get("entry_shadow") if isinstance(doc.get("entry_shadow"), dict) else {}
    recommendation = (
        entry_shadow.get("recommendation")
        if isinstance(entry_shadow.get("recommendation"), dict)
        else {}
    )
    probabilities = entry_shadow.get("probabilities") if isinstance(entry_shadow.get("probabilities"), dict) else {}
    status = str(doc.get("status") or "").strip().lower()
    attempts_elapsed = int(doc.get("attempts_elapsed") or 0)
    resolved_attempt = doc.get("resolved_attempt")
    if status == "resolved" and resolved_attempt:
        outcome_label = f"Hit em {int(resolved_attempt)} tiro(s)"
    elif status == "pending":
        outcome_label = f"Pendente ha {attempts_elapsed} giro(s)"
    elif status == "generation_error":
        outcome_label = "Erro ao gerar"
    elif status == "unavailable":
        outcome_label = "Sem sugestao"
    else:
        outcome_label = status.title() or "Indefinido"
    return {
        "id": str(doc.get("_id")),
        "anchor_history_id": str(doc.get("anchor_history_id") or ""),
        "anchor_number": doc.get("anchor_number"),
        "anchor_timestamp_br": _serialize_datetime(doc.get("anchor_timestamp_br")),
        "status": status,
        "outcome_label": outcome_label,
        "summary": _event_summary(doc),
        "suggestion_size": int(doc.get("suggestion_size") or 0),
        "suggestion_preview": [int(n) for n in (doc.get("suggestion") or [])],
        "attempts_elapsed": attempts_elapsed,
        "resolved_attempt": resolved_attempt,
        "resolved_number": doc.get("resolved_number"),
        "resolved_rank_position": doc.get("resolved_rank_position"),
        "resolved_timestamp_br": _serialize_datetime(doc.get("resolved_timestamp_br")),
        "pattern_count": int(doc.get("pattern_count") or 0),
        "top_support_count": int(doc.get("top_support_count") or 0),
        "shadow_action": str(recommendation.get("action") or "").strip(),
        "shadow_label": str(recommendation.get("label") or "").strip(),
        "shadow_reason": str(recommendation.get("reason") or "").strip(),
        "shadow_confidence_base_score": int((entry_shadow.get("entry_confidence") or {}).get("base_score_before_rank_feedback") or 0)
        if isinstance(entry_shadow.get("entry_confidence"), dict)
        else 0,
        "shadow_confidence_score": int((entry_shadow.get("entry_confidence") or {}).get("score") or 0)
        if isinstance(entry_shadow.get("entry_confidence"), dict)
        else 0,
        "shadow_confidence_delta": int((entry_shadow.get("rank_context_confidence") or {}).get("confidence_delta") or 0)
        if isinstance(entry_shadow.get("rank_context_confidence"), dict)
        else 0,
        "shadow_rank_context_band": str((entry_shadow.get("rank_context_confidence") or {}).get("latest_rank_band") or "").strip()
        if isinstance(entry_shadow.get("rank_context_confidence"), dict)
        else "",
        "shadow_p_hit_1": round(_safe_float(probabilities.get("hit_1"), 0.0), 6),
        "shadow_late_hit_risk": round(_safe_float(entry_shadow.get("late_hit_risk"), 0.0), 6),
        "shadow_ev": round(_safe_float((entry_shadow.get("expected_value") or {}).get("net_units"), 0.0), 6)
        if isinstance(entry_shadow.get("expected_value"), dict)
        else 0.0,
        "generation_error": str(doc.get("generation_error") or "").strip(),
        "explanation": str(doc.get("explanation") or "").strip(),
    }


def _format_optimized_companion(doc: Dict[str, Any] | None) -> Dict[str, Any]:
    if not isinstance(doc, dict):
        return {
            "available": False,
            "status": "",
            "suggestion_preview": [],
            "suggestion_size": 0,
            "oscillation_mode": "",
            "oscillation_reference_rank": None,
            "explanation": "",
        }
    oscillation = doc.get("oscillation") if isinstance(doc.get("oscillation"), dict) else {}
    return {
        "available": True,
        "status": str(doc.get("status") or "").strip().lower(),
        "suggestion_preview": [int(n) for n in (doc.get("suggestion") or [])],
        "suggestion_size": int(doc.get("suggestion_size") or 0),
        "oscillation_mode": str(oscillation.get("mode") or "").strip(),
        "oscillation_reference_rank": oscillation.get("reference_rank"),
        "explanation": str(doc.get("explanation") or "").strip(),
    }


def _apply_dynamic_pattern_weights(
    items: List[Dict[str, Any]],
    weights: Dict[str, float] | None = None,
    details: Dict[str, Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    normalized_weights = {
        str(pattern_id).strip(): float(weight)
        for pattern_id, weight in dict(weights or {}).items()
        if str(pattern_id).strip()
    }
    normalized_details = {
        str(pattern_id).strip(): dict(detail)
        for pattern_id, detail in dict(details or {}).items()
        if str(pattern_id).strip() and isinstance(detail, dict)
    }
    enriched: List[Dict[str, Any]] = []
    for item in list(items or []):
        pattern_id = str(item.get("pattern_id") or "").strip()
        detail = normalized_details.get(pattern_id, {})
        current_weight = float(normalized_weights.get(pattern_id, 1.0))
        row = dict(item)
        row["current_weight"] = round(current_weight, 6)
        row["weight_delta"] = round(current_weight - 1.0, 6)
        row["weight_sample"] = round(_safe_float(detail.get("sample"), 0.0), 6)
        row["top_rank_hit_rate"] = round(_safe_float(detail.get("top_rank_hit_rate"), 0.0), 6)
        row["upper_mid_hit_rate"] = round(_safe_float(detail.get("upper_mid_hit_rate"), 0.0), 6)
        row["deep_rank_hit_rate"] = round(_safe_float(detail.get("deep_rank_hit_rate"), 0.0), 6)
        row["avg_hit_rank_ratio"] = round(_safe_float(detail.get("avg_hit_rank_ratio"), 0.0), 6)
        row["recent_miss_streak"] = int(detail.get("recent_miss_streak") or 0)
        enriched.append(row)
    enriched.sort(
        key=lambda row: (
            -float(row.get("current_weight", 1.0)),
            -float(row.get("first_hit_rate", 0.0)),
            -float(row.get("covered_hit_rate", 0.0)),
            str(row.get("pattern_id") or ""),
        )
    )
    return enriched


def _compute_first_hit_streaks(resolved_docs: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not resolved_docs:
        return {
            "current_first_hit_streak": 0,
            "max_first_hit_streak": 0,
            "max_first_hit_streak_occurrences": 0,
            "first_hit_streak_occurrences": 0,
            "first_hit_streak_distribution": [],
            "current_unpaid_streak": 0,
            "max_unpaid_streak": 0,
            "max_unpaid_streak_occurrences": 0,
            "unpaid_streak_occurrences": 0,
            "unpaid_streak_distribution": [],
            "current_resolved_streak": 0,
            "recent_sequence": [],
        }

    recent_sequence = [1 if int(doc.get("resolved_attempt") or 0) == 1 else 0 for doc in resolved_docs]
    max_first_hit_streak = 0
    max_unpaid_streak = 0
    current_run = 0
    current_unpaid_run = 0
    first_hit_streak_lengths: List[int] = []
    unpaid_streak_lengths: List[int] = []
    for is_first_hit in recent_sequence:
        if is_first_hit:
            current_run += 1
            if current_run > max_first_hit_streak:
                max_first_hit_streak = current_run
            if current_unpaid_run > 0:
                unpaid_streak_lengths.append(current_unpaid_run)
            current_unpaid_run = 0
        else:
            if current_run > 0:
                first_hit_streak_lengths.append(current_run)
            current_run = 0
            current_unpaid_run += 1
            if current_unpaid_run > max_unpaid_streak:
                max_unpaid_streak = current_unpaid_run

    if current_run > 0:
        first_hit_streak_lengths.append(current_run)
    if current_unpaid_run > 0:
        unpaid_streak_lengths.append(current_unpaid_run)

    current_first_hit_streak = 0
    for is_first_hit in reversed(recent_sequence):
        if is_first_hit:
            current_first_hit_streak += 1
        else:
            break

    current_unpaid_streak = 0
    for is_first_hit in reversed(recent_sequence):
        if not is_first_hit:
            current_unpaid_streak += 1
        else:
            break

    first_hit_distribution_map: Dict[int, int] = {}
    for length in first_hit_streak_lengths:
        first_hit_distribution_map[length] = first_hit_distribution_map.get(length, 0) + 1

    distribution_map: Dict[int, int] = {}
    for length in unpaid_streak_lengths:
        distribution_map[length] = distribution_map.get(length, 0) + 1

    first_hit_streak_distribution = [
        {"length": length, "occurrences": first_hit_distribution_map[length]}
        for length in sorted(first_hit_distribution_map)
    ]
    unpaid_streak_distribution = [
        {"length": length, "occurrences": distribution_map[length]}
        for length in sorted(distribution_map)
    ]
    max_first_hit_streak_occurrences = first_hit_distribution_map.get(max_first_hit_streak, 0) if max_first_hit_streak else 0
    max_unpaid_streak_occurrences = distribution_map.get(max_unpaid_streak, 0) if max_unpaid_streak else 0

    return {
        "current_first_hit_streak": current_first_hit_streak,
        "max_first_hit_streak": max_first_hit_streak,
        "max_first_hit_streak_occurrences": max_first_hit_streak_occurrences,
        "first_hit_streak_occurrences": len(first_hit_streak_lengths),
        "first_hit_streak_distribution": first_hit_streak_distribution,
        "current_unpaid_streak": current_unpaid_streak,
        "max_unpaid_streak": max_unpaid_streak,
        "max_unpaid_streak_occurrences": max_unpaid_streak_occurrences,
        "unpaid_streak_occurrences": len(unpaid_streak_lengths),
        "unpaid_streak_distribution": unpaid_streak_distribution,
        "current_resolved_streak": len(recent_sequence),
        "recent_sequence": recent_sequence[-50:],
    }


def _build_attempt_options_from_rows(rows: List[Dict[str, Any]], total_events: int) -> List[Dict[str, Any]]:
    pending_count = 0
    unavailable_count = 0
    generation_error_count = 0
    resolved_counts: Dict[int, int] = {}

    for row in rows:
        status = str(row.get("_id", {}).get("status") or "").strip().lower()
        resolved_attempt = row.get("_id", {}).get("resolved_attempt")
        count = int(row.get("count", 0) or 0)
        if status == "pending":
            pending_count += count
        elif status == "unavailable":
            unavailable_count += count
        elif status == "generation_error":
            generation_error_count += count
        elif status == "resolved" and resolved_attempt is not None:
            try:
                resolved_counts[int(resolved_attempt)] = resolved_counts.get(int(resolved_attempt), 0) + count
            except (TypeError, ValueError):
                continue

    options = [{"value": "", "label": "Todas as sugestões", "count": int(total_events)}]
    if pending_count:
        options.append({"value": "pending", "label": "Pendentes", "count": pending_count})
    for attempt in sorted(resolved_counts):
        suffix = "ª" if attempt != 1 else "ª"
        options.append(
            {
                "value": str(attempt),
                "label": f"{attempt}{suffix} tentativa",
                "count": int(resolved_counts[attempt]),
            }
        )
    if unavailable_count:
        options.append({"value": "unavailable", "label": "Sem sugestão", "count": unavailable_count})
    if generation_error_count:
        options.append({"value": "generation_error", "label": "Erro de geração", "count": generation_error_count})
    return options


def _build_rank_position_items(
    rows: List[Dict[str, Any]],
    total_resolved: int,
    default_max_rank: int = 24,
) -> List[Dict[str, Any]]:
    rank_counts: Dict[int, int] = {}
    max_rank = int(default_max_rank or 0)
    for row in rows:
        rank = row.get("_id")
        count = int(row.get("count", 0) or 0)
        if rank is None:
            continue
        try:
            rank_value = int(rank)
        except (TypeError, ValueError):
            continue
        if rank_value <= 0:
            continue
        rank_counts[rank_value] = rank_counts.get(rank_value, 0) + count
        if rank_value > max_rank:
            max_rank = rank_value

    if max_rank <= 0:
        max_rank = int(default_max_rank or 24)

    return [
        {
            "position": position,
            "hits": int(rank_counts.get(position, 0)),
            "hit_rate": round((rank_counts.get(position, 0) / total_resolved), 4) if total_resolved else 0.0,
        }
        for position in range(1, max_rank + 1)
    ]


def _build_rank_timeline_items(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for index, doc in enumerate(docs, start=1):
        try:
            resolved_attempt = int(doc.get("resolved_attempt") or 0)
        except (TypeError, ValueError):
            resolved_attempt = 0
        try:
            rank_position = int(doc.get("resolved_rank_position") or 0)
        except (TypeError, ValueError):
            rank_position = 0
        if resolved_attempt <= 0 or rank_position <= 0:
            continue
        if resolved_attempt == 1:
            attempt_bucket = "first"
        elif resolved_attempt == 2:
            attempt_bucket = "second"
        else:
            attempt_bucket = "late"
        items.append(
            {
                "sequence_index": index,
                "anchor_number": doc.get("anchor_number"),
                "anchor_timestamp_br": _serialize_datetime(doc.get("anchor_timestamp_br")),
                "resolved_number": doc.get("resolved_number"),
                "resolved_attempt": resolved_attempt,
                "rank_position": rank_position,
                "attempt_bucket": attempt_bucket,
            }
        )
    return items


def _build_top_k_metrics(
    docs: List[Dict[str, Any]],
    *,
    total_events: int,
    thresholds: List[int] | None = None,
) -> Dict[str, Any]:
    normalized_docs = _normalize_resolved_docs(docs)
    resolved_count = len(normalized_docs)
    rank_positions = [
        max(1, int(doc.get("resolved_rank_position") or 0))
        for doc in normalized_docs
        if int(doc.get("resolved_rank_position") or 0) > 0
    ]
    target_thresholds = [int(value) for value in (thresholds or [6, 12, 18, 26]) if int(value) > 0]
    metrics = {
        f"hit_at_{threshold}": round(
            (
                sum(1 for rank in rank_positions if rank <= threshold)
                / max(1, resolved_count)
            ),
            4,
        ) if resolved_count else 0.0
        for threshold in target_thresholds
    }
    hit_at_26_count = sum(1 for rank in rank_positions if rank <= 26)
    mean_rank = round(sum(rank_positions) / resolved_count, 4) if resolved_count else 0.0
    mrr = round(sum(1.0 / rank for rank in rank_positions) / resolved_count, 6) if resolved_count else 0.0
    return {
        "total_events": int(total_events),
        "total_resolved": int(resolved_count),
        "top26_rate": round(hit_at_26_count / max(1, total_events), 4) if total_events else 0.0,
        "mean_rank": mean_rank,
        "mrr": mrr,
        **metrics,
    }


def _normalize_resolved_docs(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for doc in docs:
        raw_doc = dict(doc)
        try:
            resolved_attempt = int(raw_doc.get("resolved_attempt") or 0)
        except (TypeError, ValueError):
            resolved_attempt = 0
        try:
            resolved_rank_position = int(raw_doc.get("resolved_rank_position") or 0)
        except (TypeError, ValueError):
            resolved_rank_position = 0
        if resolved_attempt <= 0:
            continue
        raw_doc["resolved_attempt"] = resolved_attempt
        raw_doc["resolved_rank_position"] = resolved_rank_position
        normalized.append(raw_doc)
    return normalized


def _build_window_outcome_items(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for index, doc in enumerate(docs, start=1):
        status = str(doc.get("window_result_status") or "").strip().lower()
        if status not in {"hit", "miss"}:
            continue
        suggestion = [
            int(number)
            for number in (doc.get("suggestion") or [])
            if str(number).isdigit() and 0 <= int(number) <= 36
        ]
        items.append(
            {
                "sequence_index": index,
                "anchor_number": doc.get("anchor_number"),
                "anchor_timestamp_br": _serialize_datetime(doc.get("anchor_timestamp_br")),
                "outcome": status,
                "window_attempt": int(doc.get("window_result_attempt") or 0) or None,
                "resolved_attempt": int(doc.get("resolved_attempt") or 0) or None,
                "resolved_number": doc.get("resolved_number"),
                "resolved_rank_position": int(doc.get("resolved_rank_position") or 0) or None,
                "hit": bool(doc.get("window_result_hit")) if status == "hit" else False,
                "suggestion": suggestion,
                "suggestion_size": int(doc.get("suggestion_size") or len(suggestion) or 0),
                **_extract_ml_gate_context(doc),
            }
        )
    return items


def _build_window_monitor_aux_items(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for doc in docs:
        suggestion = [
            int(number)
            for number in (doc.get("suggestion") or [])
            if str(number).isdigit() and 0 <= int(number) <= 36
        ]
        items.append(
            {
                "anchor_number": doc.get("anchor_number"),
                "anchor_timestamp_br": _serialize_datetime(doc.get("anchor_timestamp_br")),
                "attempts_elapsed": int(doc.get("attempts_elapsed") or 0),
                "suggestion": suggestion,
                "suggestion_size": int(doc.get("suggestion_size") or len(suggestion) or 0),
                **_extract_ml_gate_context(doc),
            }
        )
    return items


def _build_window_hit_breakdown(docs: List[Dict[str, Any]], max_attempts: int = 4) -> Dict[str, int]:
    breakdown = {str(attempt): 0 for attempt in range(1, max(1, int(max_attempts)) + 1)}
    for doc in docs:
        status = str(doc.get("window_result_status") or "").strip().lower()
        if status != "hit":
            continue
        try:
            attempt = int(doc.get("window_result_attempt") or 0)
        except (TypeError, ValueError):
            attempt = 0
        if attempt <= 0:
            continue
        key = str(attempt)
        if key in breakdown:
            breakdown[key] += 1
    return breakdown


def _build_rolling_metric_snapshots(
    docs: List[Dict[str, Any]],
    *,
    windows: List[int],
) -> List[Dict[str, Any]]:
    normalized_docs = _normalize_resolved_docs(list(docs or []))
    snapshots: List[Dict[str, Any]] = []
    for window in windows:
        sample = normalized_docs[: max(1, int(window))]
        metrics = _build_top_k_metrics(sample, total_events=len(sample))
        first_hits = sum(1 for doc in sample if int(doc.get("resolved_attempt") or 0) == 1)
        snapshots.append(
            {
                "window": int(window),
                "sample_size": len(sample),
                "first_hit_rate": round(first_hits / len(sample), 4) if sample else 0.0,
                **metrics,
            }
        )
    return snapshots


def _headline_window(windows: List[int]) -> int:
    return 100 if 100 in windows else (windows[0] if windows else 100)


def _anchor_pair_key(doc: Dict[str, Any]) -> str:
    history_id = str(doc.get("anchor_history_id") or "").strip()
    if history_id:
        return f"history:{history_id}"
    timestamp = _serialize_datetime(doc.get("anchor_timestamp_utc")) or _serialize_datetime(doc.get("anchor_timestamp_br")) or ""
    return f"fallback:{doc.get('anchor_number')}|{timestamp}"


def _build_gate_reference_pairs(
    reference_docs: List[Dict[str, Any]],
    gate_docs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    gate_map = {
        _anchor_pair_key(dict(doc)): dict(doc)
        for doc in list(gate_docs or [])
        if isinstance(doc, dict)
    }
    pairs: List[Dict[str, Any]] = []
    for reference_doc in list(reference_docs or []):
        reference = dict(reference_doc)
        gate = gate_map.get(_anchor_pair_key(reference))
        gate_context = _extract_ml_gate_context(gate or {})
        gate_should_enter = gate_context.get("gate_should_enter")
        if gate_should_enter is None and gate is not None:
            gate_should_enter = bool(gate.get("available"))
        pairs.append(
            {
                "anchor_history_id": str(reference.get("anchor_history_id") or "").strip(),
                "anchor_number": reference.get("anchor_number"),
                "reference_hit": bool(reference.get("window_result_hit")),
                "reference_attempt": _safe_int(reference.get("window_result_attempt"), 0),
                "matched": gate is not None,
                "gate_should_enter": bool(gate_should_enter) if gate_should_enter is not None else False,
                "gate_probability": gate_context.get("gate_probability"),
                "gate_threshold": gate_context.get("gate_threshold"),
                "gate_trained_events": gate_context.get("gate_trained_events"),
                "gate_warmup_ready": gate_context.get("gate_warmup_ready"),
                "gate_reason": gate_context.get("gate_reason"),
            }
        )
    return pairs


def _build_gate_uplift_windows(
    pairs: List[Dict[str, Any]],
    *,
    windows: List[int],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for window in windows:
        subset = list(pairs[: max(1, int(window))])
        total_candidates = len(subset)
        matched = [item for item in subset if bool(item.get("matched"))]
        matched_count = len(matched)
        entered = [item for item in matched if bool(item.get("gate_should_enter"))]
        blocked = [item for item in matched if not bool(item.get("gate_should_enter"))]
        reference_hits_total = sum(1 for item in matched if bool(item.get("reference_hit")))
        entered_hits = sum(1 for item in entered if bool(item.get("reference_hit")))
        blocked_hits = sum(1 for item in blocked if bool(item.get("reference_hit")))
        blocked_misses = max(0, len(blocked) - blocked_hits)
        reference_hit_rate = (reference_hits_total / matched_count) if matched_count else None
        gate_hit_rate = (entered_hits / len(entered)) if entered else None
        activation_rate = (len(entered) / matched_count) if matched_count else None
        avoided_miss_rate = (blocked_misses / len(blocked)) if blocked else None
        blocked_hit_rate = (blocked_hits / len(blocked)) if blocked else None
        rows.append(
            {
                "window": int(window),
                "total_candidates": total_candidates,
                "matched_candidates": matched_count,
                "coverage_rate": _round_or_none((matched_count / total_candidates) if total_candidates else None),
                "entries": len(entered),
                "blocked": len(blocked),
                "activation_rate": _round_or_none(activation_rate),
                "reference_hit_rate": _round_or_none(reference_hit_rate),
                "gate_hit_rate": _round_or_none(gate_hit_rate),
                "uplift_vs_reference": _round_or_none(
                    (gate_hit_rate - reference_hit_rate)
                    if gate_hit_rate is not None and reference_hit_rate is not None
                    else None
                ),
                "avoided_miss_rate": _round_or_none(avoided_miss_rate),
                "blocked_hit_opportunity_rate": _round_or_none(blocked_hit_rate),
            }
        )
    return rows


def _probability_bucket_bounds(probability: float, *, step: float = 0.05) -> Dict[str, Any]:
    bounded = max(0.0, min(0.999999, float(probability)))
    lower = int(bounded / step) * step
    upper = min(1.0, lower + step)
    return {
        "lower": round(lower, 2),
        "upper": round(upper, 2),
        "label": f"{lower:.2f} - {upper:.2f}",
    }


def _build_gate_calibration_buckets(
    pairs: List[Dict[str, Any]],
    *,
    limit: int = DEFAULT_GATE_CALIBRATION_LIMIT,
) -> Dict[str, Any]:
    aggregates: Dict[str, Dict[str, Any]] = {}
    samples = [
        item
        for item in list(pairs[: max(20, int(limit))])
        if item.get("matched") and item.get("gate_probability") is not None
    ]
    for item in samples:
        bucket = _probability_bucket_bounds(_safe_float(item.get("gate_probability"), 0.0))
        label = str(bucket["label"])
        current = aggregates.setdefault(
            label,
            {
                "label": label,
                "lower": bucket["lower"],
                "upper": bucket["upper"],
                "count": 0,
                "predicted_sum": 0.0,
                "threshold_sum": 0.0,
                "actual_hits": 0,
                "entered": 0,
            },
        )
        current["count"] += 1
        current["predicted_sum"] += _safe_float(item.get("gate_probability"), 0.0)
        current["threshold_sum"] += _safe_float(item.get("gate_threshold"), 0.0)
        current["actual_hits"] += 1 if bool(item.get("reference_hit")) else 0
        current["entered"] += 1 if bool(item.get("gate_should_enter")) else 0

    items: List[Dict[str, Any]] = []
    for aggregate in sorted(aggregates.values(), key=lambda item: float(item["lower"])):
        count = int(aggregate["count"] or 0)
        predicted = (float(aggregate["predicted_sum"]) / count) if count else 0.0
        actual_rate = (int(aggregate["actual_hits"]) / count) if count else 0.0
        enter_rate = (int(aggregate["entered"]) / count) if count else 0.0
        threshold_mean = (float(aggregate["threshold_sum"]) / count) if count else 0.0
        items.append(
            {
                "bucket": aggregate["label"],
                "lower": aggregate["lower"],
                "upper": aggregate["upper"],
                "count": count,
                "predicted_probability": round(predicted, 4),
                "actual_hit_rate": round(actual_rate, 4),
                "calibration_gap": round(actual_rate - predicted, 4),
                "enter_rate": round(enter_rate, 4),
                "threshold_mean": round(threshold_mean, 4),
            }
        )

    total_samples = len(samples)
    predicted_avg = (sum(float(item.get("gate_probability") or 0.0) for item in samples) / total_samples) if total_samples else 0.0
    actual_avg = (sum(1 for item in samples if bool(item.get("reference_hit"))) / total_samples) if total_samples else 0.0
    enter_avg = (sum(1 for item in samples if bool(item.get("gate_should_enter"))) / total_samples) if total_samples else 0.0
    return {
        "sample_size": total_samples,
        "predicted_probability_mean": round(predicted_avg, 4) if total_samples else 0.0,
        "actual_hit_rate_mean": round(actual_avg, 4) if total_samples else 0.0,
        "calibration_gap_mean": round(actual_avg - predicted_avg, 4) if total_samples else 0.0,
        "enter_rate_mean": round(enter_avg, 4) if total_samples else 0.0,
        "items": items,
    }


def _metric_docs_from_pairs(rows: List[Dict[str, Any]], *, rank_key: str, attempt_key: str) -> List[Dict[str, Any]]:
    docs: List[Dict[str, Any]] = []
    for row in rows:
        rank = _safe_int(row.get(rank_key), 0)
        attempt = _safe_int(row.get(attempt_key), 0)
        if rank <= 0 or attempt <= 0:
            continue
        docs.append({"resolved_rank_position": rank, "resolved_attempt": attempt})
    return docs


def _build_ml_variant_pair_rows(
    ml_docs: List[Dict[str, Any]],
    top26_docs: List[Dict[str, Any]],
    base_docs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    top26_map = {
        _anchor_pair_key(dict(doc)): dict(doc)
        for doc in list(top26_docs or [])
        if isinstance(doc, dict)
    }
    base_map = {
        _anchor_pair_key(dict(doc)): dict(doc)
        for doc in list(base_docs or [])
        if isinstance(doc, dict)
    }
    rows: List[Dict[str, Any]] = []
    for ml_doc in list(ml_docs or []):
        ml = dict(ml_doc)
        pair_key = _anchor_pair_key(ml)
        top26 = top26_map.get(pair_key)
        base = base_map.get(pair_key)
        if top26 is None or base is None:
            continue
        rows.append(
            {
                "anchor_history_id": str(ml.get("anchor_history_id") or "").strip(),
                "anchor_number": ml.get("anchor_number"),
                "anchor_timestamp_br": _serialize_datetime(ml.get("anchor_timestamp_br")),
                "anchor_timestamp_utc": _serialize_datetime(ml.get("anchor_timestamp_utc")),
                "ml_rank": _safe_int(ml.get("resolved_rank_position"), 0),
                "ml_attempt": _safe_int(ml.get("resolved_attempt"), 0),
                "top26_rank": _safe_int(top26.get("resolved_rank_position"), 0),
                "top26_attempt": _safe_int(top26.get("resolved_attempt"), 0),
                "base_rank": _safe_int(base.get("resolved_rank_position"), 0),
                "base_attempt": _safe_int(base.get("resolved_attempt"), 0),
            }
        )
    return rows


def _build_ml_trend_points(
    rows: List[Dict[str, Any]],
    *,
    rolling_window: int,
) -> Dict[str, Any]:
    normalized_rows = list(rows or [])
    if len(normalized_rows) < max(5, int(rolling_window)):
        return {"items": [], "latest": None}
    items: List[Dict[str, Any]] = []
    window = max(10, int(rolling_window))
    for end_index in range(window - 1, len(normalized_rows)):
        sample = normalized_rows[end_index - window + 1 : end_index + 1]
        ml_metrics = _build_top_k_metrics(_metric_docs_from_pairs(sample, rank_key="ml_rank", attempt_key="ml_attempt"), total_events=len(sample))
        top26_metrics = _build_top_k_metrics(_metric_docs_from_pairs(sample, rank_key="top26_rank", attempt_key="top26_attempt"), total_events=len(sample))
        base_metrics = _build_top_k_metrics(_metric_docs_from_pairs(sample, rank_key="base_rank", attempt_key="base_attempt"), total_events=len(sample))
        anchor = sample[-1]
        items.append(
            {
                "sequence_index": len(items) + 1,
                "anchor_timestamp_br": anchor.get("anchor_timestamp_br"),
                "sample_size": len(sample),
                "ml_mean_rank": _round_or_none(ml_metrics.get("mean_rank"), 4),
                "top26_mean_rank": _round_or_none(top26_metrics.get("mean_rank"), 4),
                "base_mean_rank": _round_or_none(base_metrics.get("mean_rank"), 4),
                "mean_rank_gain_vs_top26": _round_or_none(
                    _safe_float(top26_metrics.get("mean_rank"), 0.0) - _safe_float(ml_metrics.get("mean_rank"), 0.0),
                    4,
                ),
                "mean_rank_gain_vs_base": _round_or_none(
                    _safe_float(base_metrics.get("mean_rank"), 0.0) - _safe_float(ml_metrics.get("mean_rank"), 0.0),
                    4,
                ),
                "ml_hit_at_26": _round_or_none(ml_metrics.get("hit_at_26"), 4),
                "hit_at_26_uplift_vs_top26": _round_or_none(
                    _safe_float(ml_metrics.get("hit_at_26"), 0.0) - _safe_float(top26_metrics.get("hit_at_26"), 0.0),
                    4,
                ),
                "mrr_uplift_vs_top26": _round_or_none(
                    _safe_float(ml_metrics.get("mrr"), 0.0) - _safe_float(top26_metrics.get("mrr"), 0.0),
                    6,
                ),
            }
        )
    return {"items": items, "latest": items[-1] if items else None}


def _build_gate_uplift_trend_points(
    pairs: List[Dict[str, Any]],
    *,
    rolling_window: int,
) -> Dict[str, Any]:
    rows = [item for item in list(pairs or []) if bool(item.get("matched"))]
    if len(rows) < max(5, int(rolling_window)):
        return {"items": [], "latest": None}
    items: List[Dict[str, Any]] = []
    window = max(10, int(rolling_window))
    for end_index in range(window - 1, len(rows)):
        sample = rows[end_index - window + 1 : end_index + 1]
        matched_count = len(sample)
        entered = [item for item in sample if bool(item.get("gate_should_enter"))]
        reference_hits = sum(1 for item in sample if bool(item.get("reference_hit")))
        gate_hits = sum(1 for item in entered if bool(item.get("reference_hit")))
        activation_rate = (len(entered) / matched_count) if matched_count else None
        reference_hit_rate = (reference_hits / matched_count) if matched_count else None
        gate_hit_rate = (gate_hits / len(entered)) if entered else None
        latest = sample[-1]
        items.append(
            {
                "sequence_index": len(items) + 1,
                "anchor_number": latest.get("anchor_number"),
                "sample_size": matched_count,
                "activation_rate": _round_or_none(activation_rate),
                "reference_hit_rate": _round_or_none(reference_hit_rate),
                "gate_hit_rate": _round_or_none(gate_hit_rate),
                "uplift_vs_reference": _round_or_none(
                    (gate_hit_rate - reference_hit_rate)
                    if gate_hit_rate is not None and reference_hit_rate is not None
                    else None
                ),
                "anchor_history_id": latest.get("anchor_history_id"),
            }
        )
    return {"items": items, "latest": items[-1] if items else None}


@router.get("/api/suggestion-monitor/overview")
async def get_suggestion_monitor_overview(
    roulette_id: str = Query(default="pragmatic-auto-roulette"),
    config_key: str | None = Query(default=None),
    attempt_filter: str | None = Query(default=None),
    ranking_variant: str | None = Query(default="base"),
    shadow_action: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    start_hour: int | None = Query(default=None, ge=0, le=23),
    end_hour: int | None = Query(default=None, ge=0, le=23),
) -> Dict[str, Any]:
    try:
        await _ensure_monitor_indexes()
        paths = _variant_field_paths(ranking_variant)
        base_filter = _build_event_filter(
            roulette_id=roulette_id,
            config_key=config_key,
            ranking_variant=ranking_variant,
            shadow_action=shadow_action,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
        )
        filter_query = _build_event_filter(
            roulette_id=roulette_id,
            config_key=config_key,
            attempt_filter=attempt_filter,
            ranking_variant=ranking_variant,
            shadow_action=shadow_action,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
        )
        facet_rows = await suggestion_monitor_events_coll.aggregate(
            [
                {
                    "$facet": {
                        "summary": [
                            {"$match": filter_query},
                            {
                                "$group": {
                                    "_id": None,
                                    "total_events": {"$sum": 1},
                                    "pending_events": {
                                        "$sum": {
                                            "$cond": [{"$eq": [f"${paths['status']}", "pending"]}, 1, 0]
                                        }
                                    },
                                    "resolved_events": {
                                        "$sum": {
                                            "$cond": [{"$eq": [f"${paths['status']}", "resolved"]}, 1, 0]
                                        }
                                    },
                                    "unavailable_events": {
                                        "$sum": {
                                            "$cond": [
                                                {"$in": [f"${paths['status']}", ["unavailable", "generation_error"]]},
                                                1,
                                                0,
                                            ]
                                        }
                                    },
                                    "first_hit_events": {
                                        "$sum": {
                                            "$cond": [
                                                {
                                                    "$and": [
                                                        {"$eq": [f"${paths['status']}", "resolved"]},
                                                        {"$eq": [f"${paths['resolved_attempt']}", 1]},
                                                    ]
                                                },
                                                1,
                                                0,
                                            ]
                                        }
                                    },
                                }
                            },
                        ],
                        "resolved_by_attempt": [
                            {"$match": _merge_filter_with_condition(filter_query, {str(paths["status"]): "resolved"})},
                            {"$group": {"_id": f"${paths['resolved_attempt']}", "count": {"$sum": 1}}},
                            {"$sort": {"_id": 1}},
                        ],
                        "attempt_rows": [
                            {"$match": base_filter},
                            {
                                "$group": {
                                    "_id": {
                                        "status": f"${paths['status']}",
                                        "resolved_attempt": f"${paths['resolved_attempt']}",
                                    },
                                    "count": {"$sum": 1},
                                }
                            },
                        ],
                        "base_total": [
                            {"$match": base_filter},
                            {"$count": "count"},
                        ],
                    }
                }
            ],
            allowDiskUse=True,
        ).to_list(length=1)
        facet = facet_rows[0] if facet_rows else {}
        summary_row = (facet.get("summary") or [{}])[0] or {}
        total_events = int(summary_row.get("total_events") or 0)
        pending_events = int(summary_row.get("pending_events") or 0)
        resolved_events = int(summary_row.get("resolved_events") or 0)
        unavailable_events = int(summary_row.get("unavailable_events") or 0)
        first_hit_events = int(summary_row.get("first_hit_events") or 0)

        per_attempt = {
            str(int(row["_id"])): int(row["count"])
            for row in list(facet.get("resolved_by_attempt") or [])
            if row.get("_id") is not None
        }
        attempt_rows = [dict(row) for row in list(facet.get("attempt_rows") or [])]
        base_total_rows = list(facet.get("base_total") or [])
        base_total_events = int((base_total_rows[0] or {}).get("count") or 0) if base_total_rows else 0
        attempt_options = _build_attempt_options_from_rows(
            attempt_rows,
            base_total_events,
        )

        return {
            "roulette_id": roulette_id,
            "config_key": config_key,
            "attempt_filter": attempt_filter,
            "ranking_variant": paths["label"],
            "shadow_action": shadow_action,
            "start_date": start_date,
            "end_date": end_date,
            "start_hour": start_hour,
            "end_hour": end_hour,
            "total_events": total_events,
            "pending_events": pending_events,
            "resolved_events": resolved_events,
            "unavailable_events": unavailable_events,
            "hit_first_attempt_rate": round(first_hit_events / resolved_events, 4) if resolved_events else 0.0,
            "resolved_by_attempt": per_attempt,
            "attempt_options": attempt_options,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/suggestion-monitor/events")
async def get_suggestion_monitor_events(
    roulette_id: str = Query(default="pragmatic-auto-roulette"),
    config_key: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    attempt_filter: str | None = Query(default=None),
    ranking_variant: str | None = Query(default="base"),
    shadow_action: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    start_hour: int | None = Query(default=None, ge=0, le=23),
    end_hour: int | None = Query(default=None, ge=0, le=23),
) -> Dict[str, Any]:
    try:
        await _ensure_monitor_indexes()
        filter_query = _build_event_filter(
            roulette_id=roulette_id,
            config_key=config_key,
            status=status,
            attempt_filter=attempt_filter,
            ranking_variant=ranking_variant,
            shadow_action=shadow_action,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
        )
        docs = await suggestion_monitor_events_coll.aggregate(
            [
                {"$match": filter_query},
                {"$sort": {"anchor_timestamp_utc": -1}},
                {"$limit": int(limit)},
            ],
            allowDiskUse=True,
        ).to_list(length=limit)
        items: List[Dict[str, Any]] = []
        for doc in docs:
            items.append(
                {
                    "id": str(doc.get("_id")),
                    "roulette_id": doc.get("roulette_id"),
                    "anchor_history_id": doc.get("anchor_history_id"),
                    "anchor_number": doc.get("anchor_number"),
                    "anchor_timestamp_br": doc.get("anchor_timestamp_br"),
                    "status": doc.get("status"),
                    "suggestion_size": doc.get("suggestion_size"),
                    "suggestion": doc.get("suggestion"),
                    "resolved_attempt": doc.get("resolved_attempt"),
                    "resolved_number": doc.get("resolved_number"),
                    "resolved_rank_position": doc.get("resolved_rank_position"),
                    "resolved_timestamp_br": doc.get("resolved_timestamp_br"),
                    "pattern_count": doc.get("pattern_count"),
                    "top_support_count": doc.get("top_support_count"),
                    "entry_shadow": doc.get("entry_shadow"),
                }
            )
        return {
            "roulette_id": roulette_id,
            "config_key": config_key,
            "ranking_variant": _variant_field_paths(ranking_variant)["label"],
            "items": items,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/suggestion-monitor/latest")
async def get_suggestion_monitor_latest(
    roulette_id: str = Query(default="pragmatic-auto-roulette"),
    config_key: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    attempt_filter: str | None = Query(default=None),
    ranking_variant: str | None = Query(default="base"),
    shadow_action: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    start_hour: int | None = Query(default=None, ge=0, le=23),
    end_hour: int | None = Query(default=None, ge=0, le=23),
) -> Dict[str, Any]:
    try:
        await _ensure_monitor_indexes()
        page_size = 50
        base_filter = _build_event_filter(
            roulette_id=roulette_id,
            config_key=config_key,
            ranking_variant=ranking_variant,
            shadow_action=shadow_action,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
        )
        filter_query = _build_event_filter(
            roulette_id=roulette_id,
            config_key=config_key,
            status=status,
            attempt_filter=attempt_filter,
            ranking_variant=ranking_variant,
            shadow_action=shadow_action,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
        )
        total_count = await suggestion_monitor_events_coll.count_documents(filter_query)
        total_pages = max(1, (total_count + page_size - 1) // page_size)
        current_page = min(max(1, int(page)), total_pages)
        skip = (current_page - 1) * page_size
        docs = await suggestion_monitor_events_coll.aggregate(
            [
                {"$match": filter_query},
                {"$sort": {"anchor_timestamp_utc": -1}},
                {"$skip": int(skip)},
                {"$limit": int(page_size)},
            ],
            allowDiskUse=True,
        ).to_list(length=page_size)
        docs_list = [dict(doc) for doc in docs]
        items = [_format_latest_event(doc) for doc in docs_list]
        if _variant_field_paths(ranking_variant)["label"] == "base_v1" and items:
            base_event_ids = [str(item["id"]) for item in items if item.get("id")]
            optimized_docs = await suggestion_monitor_events_coll.find(
                {
                    "source_base_event_id": {"$in": base_event_ids},
                    "ranking_variant": "ranking_v2_top26",
                },
                {
                    "_id": 1,
                    "source_base_event_id": 1,
                    "status": 1,
                    "suggestion": 1,
                    "suggestion_size": 1,
                    "oscillation": 1,
                    "explanation": 1,
                },
            ).to_list(length=None)
            optimized_by_base = {
                str(doc.get("source_base_event_id") or ""): _format_optimized_companion(dict(doc))
                for doc in optimized_docs
                if str(doc.get("source_base_event_id") or "").strip()
            }
            for item in items:
                item["optimized"] = optimized_by_base.get(
                    str(item.get("id") or ""),
                    _format_optimized_companion(None),
                )
        attempt_rows = await suggestion_monitor_events_coll.aggregate(
            [
                {"$match": base_filter},
                {
                    "$group": {
                        "_id": {"status": "$status", "resolved_attempt": "$resolved_attempt"},
                        "count": {"$sum": 1},
                    }
                },
            ],
            allowDiskUse=True,
        ).to_list(length=None)
        return {
            "roulette_id": roulette_id,
            "config_key": config_key,
            "attempt_filter": attempt_filter,
            "ranking_variant": _variant_field_paths(ranking_variant)["label"],
            "shadow_action": shadow_action,
            "start_date": start_date,
            "end_date": end_date,
            "start_hour": start_hour,
            "end_hour": end_hour,
            "count": len(items),
            "total_count": total_count,
            "page": current_page,
            "page_size": page_size,
            "total_pages": total_pages,
            "has_prev": current_page > 1,
            "has_next": current_page < total_pages,
            "attempt_options": _build_attempt_options_from_rows(
                [dict(row) for row in attempt_rows],
                await suggestion_monitor_events_coll.count_documents(base_filter),
            ),
            "items": items,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/suggestion-monitor/patterns")
async def get_suggestion_monitor_patterns(
    roulette_id: str = Query(default="pragmatic-auto-roulette"),
    config_key: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    attempt_filter: str | None = Query(default=None),
    ranking_variant: str | None = Query(default="base"),
    shadow_action: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    start_hour: int | None = Query(default=None, ge=0, le=23),
    end_hour: int | None = Query(default=None, ge=0, le=23),
) -> Dict[str, Any]:
    try:
        await _ensure_monitor_indexes()
        event_filter = _build_event_filter(
            roulette_id=roulette_id,
            config_key=config_key,
            attempt_filter=attempt_filter,
            ranking_variant=ranking_variant,
            shadow_action=shadow_action,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
        )
        event_docs = await suggestion_monitor_events_coll.find(event_filter, {"_id": 1}).to_list(length=None)
        event_ids = [str(doc.get("_id")) for doc in event_docs if doc.get("_id") is not None]
        if event_ids:
            filter_query = {"suggestion_event_id": {"$in": event_ids}}
        else:
            filter_query = {"suggestion_event_id": {"$in": []}}
        latest_dynamic_doc = await suggestion_monitor_events_coll.find_one(
            event_filter,
            {
                "_id": 1,
                "dynamic_weighting": 1,
                "anchor_timestamp_utc": 1,
            },
            sort=[("anchor_timestamp_utc", -1)],
        )
        dynamic_weighting = (
            latest_dynamic_doc.get("dynamic_weighting")
            if isinstance(latest_dynamic_doc, dict) and isinstance(latest_dynamic_doc.get("dynamic_weighting"), dict)
            else {}
        )
        dynamic_weights = {
            str(pattern_id).strip(): float(weight)
            for pattern_id, weight in dict(dynamic_weighting.get("weights") or {}).items()
            if str(pattern_id).strip()
        }
        dynamic_details = {
            str(pattern_id).strip(): dict(detail)
            for pattern_id, detail in dict(dynamic_weighting.get("details") or {}).items()
            if str(pattern_id).strip() and isinstance(detail, dict)
        }
        pipeline = [
            {"$match": filter_query},
            {
                "$group": {
                    "_id": "$pattern_id",
                    "pattern_name": {"$first": "$pattern_name"},
                    "signals": {"$sum": 1},
                    "covered_hits": {"$sum": {"$cond": ["$covered_hit", 1, 0]}},
                    "resolved": {
                        "$sum": {
                            "$cond": [{"$eq": ["$status", "resolved"]}, 1, 0]
                        }
                    },
                    "first_hits": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$and": [
                                        {"$eq": ["$status", "resolved"]},
                                        {"$eq": ["$covered_hit", True]},
                                        {"$eq": ["$resolved_attempt", 1]},
                                    ]
                                },
                                1,
                                0,
                            ]
                        }
                    },
                    "avg_resolved_attempt": {"$avg": "$resolved_attempt"},
                }
            },
            {"$sort": {"covered_hits": -1, "signals": -1, "_id": 1}},
            {"$limit": limit},
        ]
        rows = await suggestion_monitor_pattern_outcomes_coll.aggregate(
            pipeline,
            allowDiskUse=True,
        ).to_list(length=None)
        items = []
        for row in rows:
            signals = int(row.get("signals", 0) or 0)
            covered_hits = int(row.get("covered_hits", 0) or 0)
            first_hits = int(row.get("first_hits", 0) or 0)
            items.append(
                {
                    "pattern_id": str(row.get("_id")),
                    "pattern_name": row.get("pattern_name"),
                    "signals": signals,
                    "covered_hits": covered_hits,
                    "covered_hit_rate": round(covered_hits / signals, 4) if signals else 0.0,
                    "first_hits": first_hits,
                    "first_hit_rate": round(first_hits / signals, 4) if signals else 0.0,
                    "avg_resolved_attempt": round(float(row.get("avg_resolved_attempt") or 0.0), 4),
                }
            )
        items = _apply_dynamic_pattern_weights(items, dynamic_weights, dynamic_details)
        return {
            "roulette_id": roulette_id,
            "config_key": config_key,
            "ranking_variant": _variant_field_paths(ranking_variant)["label"],
            "dynamic_weighting": {
                "applied": bool(dynamic_weighting.get("applied", False)),
                "weight_count": int(dynamic_weighting.get("weight_count", 0) or 0),
                "source_event_id": (
                    str(latest_dynamic_doc.get("_id"))
                    if isinstance(latest_dynamic_doc, dict) and latest_dynamic_doc.get("_id") is not None
                    else ""
                ),
            },
            "items": items,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/suggestion-monitor/hourly")
async def get_suggestion_monitor_hourly(
    roulette_id: str = Query(default="pragmatic-auto-roulette"),
    config_key: str | None = Query(default=None),
    attempt_filter: str | None = Query(default=None),
    ranking_variant: str | None = Query(default="base"),
    shadow_action: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    start_hour: int | None = Query(default=None, ge=0, le=23),
    end_hour: int | None = Query(default=None, ge=0, le=23),
) -> Dict[str, Any]:
    try:
        await _ensure_monitor_indexes()
        paths = _variant_field_paths(ranking_variant)
        filter_query = _build_event_filter(
            roulette_id=roulette_id,
            config_key=config_key,
            attempt_filter=attempt_filter,
            ranking_variant=ranking_variant,
            shadow_action=shadow_action,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
        )
        pipeline = [
            {"$match": filter_query},
            {
                "$group": {
                    "_id": "$anchor_hour_br",
                    "events": {"$sum": 1},
                    "resolved": {"$sum": {"$cond": [{"$eq": [f"${paths['status']}", "resolved"]}, 1, 0]}},
                    "first_hits": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$and": [
                                        {"$eq": [f"${paths['status']}", "resolved"]},
                                        {"$eq": [f"${paths['resolved_attempt']}", 1]},
                                    ]
                                },
                                1,
                                0,
                            ]
                        }
                    },
                    "pending": {"$sum": {"$cond": [{"$eq": [f"${paths['status']}", "pending"]}, 1, 0]}},
                    "avg_resolved_attempt": {"$avg": f"${paths['resolved_attempt']}"},
                }
            },
            {"$sort": {"_id": 1}},
        ]
        rows = await suggestion_monitor_events_coll.aggregate(
            pipeline,
            allowDiskUse=True,
        ).to_list(length=None)
        hours = []
        for hour in range(24):
            row = next((item for item in rows if int(item.get("_id", -1)) == hour), None)
            events = int(row.get("events", 0) or 0) if row else 0
            resolved = int(row.get("resolved", 0) or 0) if row else 0
            first_hits = int(row.get("first_hits", 0) or 0) if row else 0
            pending = int(row.get("pending", 0) or 0) if row else 0
            avg_attempt = round(_safe_float(row.get("avg_resolved_attempt"), 0.0), 4) if row else 0.0
            hours.append(
                {
                    "hour": hour,
                    "label": f"{hour:02d}:00",
                    "events": events,
                    "resolved": resolved,
                    "pending": pending,
                    "first_hits": first_hits,
                    "first_hit_rate": round(first_hits / resolved, 4) if resolved else 0.0,
                    "resolution_rate": round(resolved / events, 4) if events else 0.0,
                    "avg_resolved_attempt": avg_attempt,
                }
            )
        return {"roulette_id": roulette_id, "config_key": config_key, "ranking_variant": paths["label"], "items": hours}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/suggestion-monitor/rank-timeline")
async def get_suggestion_monitor_rank_timeline(
    roulette_id: str = Query(default="pragmatic-auto-roulette"),
    config_key: str | None = Query(default=None),
    limit: int = Query(default=240, ge=10, le=1000),
    attempt_filter: str | None = Query(default=None),
    ranking_variant: str | None = Query(default="base"),
    shadow_action: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    start_hour: int | None = Query(default=None, ge=0, le=23),
    end_hour: int | None = Query(default=None, ge=0, le=23),
) -> Dict[str, Any]:
    try:
        await _ensure_monitor_indexes()
        paths = _variant_field_paths(ranking_variant)
        filter_query = _build_event_filter(
            roulette_id=roulette_id,
            config_key=config_key,
            status="resolved",
            attempt_filter=attempt_filter,
            ranking_variant=ranking_variant,
            shadow_action=shadow_action,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
        )
        total_resolved = await suggestion_monitor_events_coll.count_documents(filter_query)
        docs = await suggestion_monitor_events_coll.aggregate(
            [
                {"$match": filter_query},
                {"$sort": {"anchor_timestamp_utc": -1}},
                {"$limit": int(limit)},
                {"$project": dict(paths["projection"])},
            ],
            allowDiskUse=True,
        ).to_list(length=limit)
        docs.reverse()
        docs_list = [dict(doc) for doc in docs]
        normalized_docs = _normalize_resolved_docs(docs_list)
        items = _build_rank_timeline_items(normalized_docs)
        average_rank_position = (
            round(sum(int(item["rank_position"]) for item in items) / len(items), 4)
            if items
            else 0.0
        )
        rank_ceiling = _resolve_rank_ceiling(paths, docs_list)
        return {
            "roulette_id": roulette_id,
            "config_key": config_key,
            "ranking_variant": paths["label"],
            "limit": limit,
            "attempt_filter": attempt_filter,
            "shadow_action": shadow_action,
            "start_date": start_date,
            "end_date": end_date,
            "start_hour": start_hour,
            "end_hour": end_hour,
            "total_resolved": total_resolved,
            "displayed_points": len(items),
            "truncated": total_resolved > len(items),
            "average_rank_position": average_rank_position,
            "rank_ceiling": int(rank_ceiling),
            "items": items,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/suggestion-monitor/top-k-metrics")
async def get_suggestion_monitor_top_k_metrics(
    roulette_id: str = Query(default="pragmatic-auto-roulette"),
    config_key: str | None = Query(default=None),
    attempt_filter: str | None = Query(default=None),
    ranking_variant: str | None = Query(default="ranking_v2_top26"),
    shadow_action: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    start_hour: int | None = Query(default=None, ge=0, le=23),
    end_hour: int | None = Query(default=None, ge=0, le=23),
) -> Dict[str, Any]:
    try:
        await _ensure_monitor_indexes()
        paths = _variant_field_paths(ranking_variant)
        base_filter = _build_event_filter(
            roulette_id=roulette_id,
            config_key=config_key,
            ranking_variant=ranking_variant,
            shadow_action=shadow_action,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
        )
        resolved_filter = _build_event_filter(
            roulette_id=roulette_id,
            config_key=config_key,
            status="resolved",
            attempt_filter=attempt_filter,
            ranking_variant=ranking_variant,
            shadow_action=shadow_action,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
        )
        total_events = await suggestion_monitor_events_coll.count_documents(base_filter)
        docs = await suggestion_monitor_events_coll.aggregate(
            [
                {"$match": resolved_filter},
                {
                    "$project": {
                        "resolved_rank_position": 1,
                        "resolved_attempt": 1,
                    }
                },
            ],
            allowDiskUse=True,
        ).to_list(length=None)
        metrics = _build_top_k_metrics([dict(doc) for doc in docs], total_events=total_events)
        return {
            "roulette_id": roulette_id,
            "config_key": config_key,
            "ranking_variant": paths["label"],
            "attempt_filter": attempt_filter,
            "shadow_action": shadow_action,
            "start_date": start_date,
            "end_date": end_date,
            "start_hour": start_hour,
            "end_hour": end_hour,
            **metrics,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/suggestion-monitor/ml-evolution")
async def get_suggestion_monitor_ml_evolution(
    roulette_id: str = Query(default="pragmatic-auto-roulette"),
    config_key: str | None = Query(default=None),
    windows: str | None = Query(default=None),
    shadow_action: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    start_hour: int | None = Query(default=None, ge=0, le=23),
    end_hour: int | None = Query(default=None, ge=0, le=23),
) -> Dict[str, Any]:
    try:
        await _ensure_monitor_indexes()
        window_sizes = _parse_window_sizes(windows)
        max_window = max(window_sizes) if window_sizes else max(DEFAULT_ANALYTICS_WINDOWS)
        variant_specs = [
            ("base", "Ranking Bruto"),
            ("ranking_v2_top26", "Ranking V2 Top26"),
            ("time_window_prior_v1", "Prior Temporal"),
            ("ml_meta_rank_v1", "ML Meta Rank"),
        ]
        headline_window = _headline_window(window_sizes)
        variants: List[Dict[str, Any]] = []
        for variant_key, label in variant_specs:
            resolved_filter = _build_event_filter(
                roulette_id=roulette_id,
                config_key=config_key,
                status="resolved",
                ranking_variant=variant_key,
                shadow_action=shadow_action,
                start_date=start_date,
                end_date=end_date,
                start_hour=start_hour,
                end_hour=end_hour,
            )
            total_resolved = await suggestion_monitor_events_coll.count_documents(resolved_filter)
            docs = await suggestion_monitor_events_coll.aggregate(
                [
                    {"$match": resolved_filter},
                    {"$sort": {"anchor_timestamp_utc": -1}},
                    {"$limit": int(max_window)},
                    {
                        "$project": {
                            "resolved_rank_position": 1,
                            "resolved_attempt": 1,
                            "suggestion_size": 1,
                        }
                    },
                ],
                allowDiskUse=True,
            ).to_list(length=max_window)
            docs_list = [dict(doc) for doc in docs]
            rolling = _build_rolling_metric_snapshots(docs_list, windows=window_sizes)
            headline = next((item for item in rolling if int(item["window"]) == headline_window), rolling[0] if rolling else None)
            variants.append(
                {
                    "ranking_variant": _variant_field_paths(variant_key)["label"],
                    "label": label,
                    "total_resolved": total_resolved,
                    "rolling": rolling,
                    "headline": headline,
                }
            )
        return {
            "roulette_id": roulette_id,
            "config_key": config_key,
            "windows": window_sizes,
            "headline_window": headline_window,
            "variants": variants,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/suggestion-monitor/ml-gate-analytics")
async def get_suggestion_monitor_ml_gate_analytics(
    roulette_id: str = Query(default="pragmatic-auto-roulette"),
    config_key: str | None = Query(default=None),
    windows: str | None = Query(default=None),
    calibration_limit: int = Query(default=DEFAULT_GATE_CALIBRATION_LIMIT, ge=50, le=2000),
    shadow_action: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    start_hour: int | None = Query(default=None, ge=0, le=23),
    end_hour: int | None = Query(default=None, ge=0, le=23),
) -> Dict[str, Any]:
    try:
        await _ensure_monitor_indexes()
        window_sizes = _parse_window_sizes(windows)
        fetch_limit = max(max(window_sizes) if window_sizes else 0, int(calibration_limit))
        reference_filter = {
            "$and": [
                _build_event_filter(
                    roulette_id=roulette_id,
                    config_key=config_key,
                    ranking_variant="ml_top12_reference_12x4_v1",
                    shadow_action=shadow_action,
                    start_date=start_date,
                    end_date=end_date,
                    start_hour=start_hour,
                    end_hour=end_hour,
                ),
                {"window_result_finalized": True},
            ]
        }
        reference_docs = await suggestion_monitor_events_coll.aggregate(
            [
                {"$match": reference_filter},
                {"$sort": {"anchor_timestamp_utc": -1}},
                {"$limit": int(fetch_limit)},
                {
                    "$project": {
                        "anchor_history_id": 1,
                        "anchor_number": 1,
                        "anchor_timestamp_utc": 1,
                        "window_result_hit": 1,
                        "window_result_attempt": 1,
                    }
                },
            ],
            allowDiskUse=True,
        ).to_list(length=fetch_limit)
        reference_list = [dict(doc) for doc in reference_docs]
        anchor_history_ids = [
            str(doc.get("anchor_history_id") or "").strip()
            for doc in reference_list
            if str(doc.get("anchor_history_id") or "").strip()
        ]
        gate_docs: List[Dict[str, Any]] = []
        if anchor_history_ids:
            gate_filter: Dict[str, Any] = {
                "roulette_id": roulette_id,
                "ranking_variant": "ml_entry_gate_12x4_v1",
                "anchor_history_id": {"$in": anchor_history_ids},
            }
            if config_key:
                gate_filter["config_key"] = config_key
            gate_docs = [
                dict(doc)
                for doc in await suggestion_monitor_events_coll.find(
                    gate_filter,
                    {
                        "anchor_history_id": 1,
                        "anchor_number": 1,
                        "anchor_timestamp_utc": 1,
                        "available": 1,
                        "entry_shadow.recommendation": 1,
                        "oscillation.ml_entry_gate": 1,
                    },
                ).to_list(length=len(anchor_history_ids))
            ]
        pairs = _build_gate_reference_pairs(reference_list, gate_docs)
        uplift_windows = _build_gate_uplift_windows(pairs, windows=window_sizes)
        calibration = _build_gate_calibration_buckets(pairs, limit=calibration_limit)
        matched_pairs = sum(1 for item in pairs if bool(item.get("matched")))
        return {
            "roulette_id": roulette_id,
            "config_key": config_key,
            "windows": window_sizes,
            "reference_candidates": len(reference_list),
            "matched_pairs": matched_pairs,
            "uplift_windows": uplift_windows,
            "calibration": calibration,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/suggestion-monitor/ml-trend")
async def get_suggestion_monitor_ml_trend(
    roulette_id: str = Query(default="pragmatic-auto-roulette"),
    config_key: str | None = Query(default=None),
    rolling_window: int = Query(default=50, ge=10, le=400),
    limit: int = Query(default=320, ge=50, le=1200),
    shadow_action: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    start_hour: int | None = Query(default=None, ge=0, le=23),
    end_hour: int | None = Query(default=None, ge=0, le=23),
) -> Dict[str, Any]:
    try:
        await _ensure_monitor_indexes()
        ml_filter = _build_event_filter(
            roulette_id=roulette_id,
            config_key=config_key,
            status="resolved",
            ranking_variant="ml_meta_rank_v1",
            shadow_action=shadow_action,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
        )
        projection = {
            "anchor_history_id": 1,
            "anchor_number": 1,
            "anchor_timestamp_br": 1,
            "anchor_timestamp_utc": 1,
            "resolved_rank_position": 1,
            "resolved_attempt": 1,
        }
        ml_docs = await suggestion_monitor_events_coll.aggregate(
            [
                {"$match": ml_filter},
                {"$sort": {"anchor_timestamp_utc": -1}},
                {"$limit": int(limit)},
                {"$project": projection},
            ],
            allowDiskUse=True,
        ).to_list(length=limit)
        ml_list = [dict(doc) for doc in ml_docs]
        anchor_history_ids = [
            str(doc.get("anchor_history_id") or "").strip()
            for doc in ml_list
            if str(doc.get("anchor_history_id") or "").strip()
        ]
        if not anchor_history_ids:
            return {
                "roulette_id": roulette_id,
                "config_key": config_key,
                "rolling_window": rolling_window,
                "ml_meta_rank": {"items": [], "latest": None},
                "ml_gate": {"items": [], "latest": None},
            }
        common_filter: Dict[str, Any] = {
            "roulette_id": roulette_id,
            "anchor_history_id": {"$in": anchor_history_ids},
            "status": "resolved",
        }
        if config_key:
            common_filter["config_key"] = config_key
        top26_docs = await suggestion_monitor_events_coll.find(
            {**common_filter, "ranking_variant": "ranking_v2_top26"},
            projection,
        ).to_list(length=len(anchor_history_ids))
        base_docs = await suggestion_monitor_events_coll.find(
            {
                **common_filter,
                "$or": [
                    {"ranking_variant": "base_v1"},
                    {"ranking_variant": {"$exists": False}},
                ],
            },
            projection,
        ).to_list(length=len(anchor_history_ids))
        ml_rows = _build_ml_variant_pair_rows(ml_list, [dict(doc) for doc in top26_docs], [dict(doc) for doc in base_docs])
        ml_rows.sort(key=lambda item: (str(item.get("anchor_timestamp_utc") or ""), str(item.get("anchor_history_id") or "")))
        ml_trend = _build_ml_trend_points(ml_rows, rolling_window=rolling_window)

        reference_filter = {
            "$and": [
                _build_event_filter(
                    roulette_id=roulette_id,
                    config_key=config_key,
                    ranking_variant="ml_top12_reference_12x4_v1",
                    shadow_action=shadow_action,
                    start_date=start_date,
                    end_date=end_date,
                    start_hour=start_hour,
                    end_hour=end_hour,
                ),
                {"window_result_finalized": True},
            ]
        }
        reference_docs = await suggestion_monitor_events_coll.aggregate(
            [
                {"$match": reference_filter},
                {"$sort": {"anchor_timestamp_utc": 1}},
                {"$limit": int(limit)},
                {
                    "$project": {
                        "anchor_history_id": 1,
                        "anchor_number": 1,
                        "anchor_timestamp_utc": 1,
                        "window_result_hit": 1,
                        "window_result_attempt": 1,
                    }
                },
            ],
            allowDiskUse=True,
        ).to_list(length=limit)
        reference_list = [dict(doc) for doc in reference_docs]
        gate_docs = await suggestion_monitor_events_coll.find(
            {
                "roulette_id": roulette_id,
                "ranking_variant": "ml_entry_gate_12x4_v1",
                "anchor_history_id": {"$in": [
                    str(doc.get("anchor_history_id") or "").strip()
                    for doc in reference_list
                    if str(doc.get("anchor_history_id") or "").strip()
                ]},
                **({"config_key": config_key} if config_key else {}),
            },
            {
                "anchor_history_id": 1,
                "anchor_number": 1,
                "anchor_timestamp_utc": 1,
                "available": 1,
                "entry_shadow.recommendation": 1,
                "oscillation.ml_entry_gate": 1,
            },
        ).to_list(length=len(reference_list))
        pairs = _build_gate_reference_pairs(reference_list, [dict(doc) for doc in gate_docs])
        gate_trend = _build_gate_uplift_trend_points(pairs, rolling_window=rolling_window)
        return {
            "roulette_id": roulette_id,
            "config_key": config_key,
            "rolling_window": int(rolling_window),
            "limit": int(limit),
            "ml_meta_rank": ml_trend,
            "ml_gate": gate_trend,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/suggestion-monitor/window-outcome-timeline")
async def get_suggestion_monitor_window_outcome_timeline(
    roulette_id: str = Query(default="pragmatic-auto-roulette"),
    config_key: str | None = Query(default=None),
    limit: int = Query(default=240, ge=10, le=1000),
    ranking_variant: str | None = Query(default="top26_selective_16x4_v1"),
    shadow_action: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    start_hour: int | None = Query(default=None, ge=0, le=23),
    end_hour: int | None = Query(default=None, ge=0, le=23),
) -> Dict[str, Any]:
    try:
        await _ensure_monitor_indexes()
        paths = _variant_field_paths(ranking_variant)
        filter_query = _build_event_filter(
            roulette_id=roulette_id,
            config_key=config_key,
            ranking_variant=ranking_variant,
            shadow_action=shadow_action,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
        )
        finalized_filter = {
            "$and": [
                filter_query,
                {"window_result_finalized": True},
            ]
        }
        total_events = await suggestion_monitor_events_coll.count_documents(filter_query)
        pending_events = await suggestion_monitor_events_coll.count_documents(
            {
                "$and": [
                    filter_query,
                    {"status": "pending"},
                ]
            }
        )
        unavailable_events = await suggestion_monitor_events_coll.count_documents(
            {
                "$and": [
                    filter_query,
                    {"status": "unavailable"},
                ]
            }
        )
        total_finalized = await suggestion_monitor_events_coll.count_documents(finalized_filter)
        total_hits = await suggestion_monitor_events_coll.count_documents(
            {
                "$and": [
                    finalized_filter,
                    {"window_result_status": "hit"},
                ]
            }
        )
        docs = await suggestion_monitor_events_coll.aggregate(
            [
                {"$match": finalized_filter},
                {"$sort": {"anchor_timestamp_utc": -1}},
                {"$limit": int(limit)},
                {
                    "$project": {
                        "anchor_number": 1,
                        "anchor_timestamp_br": 1,
                        "anchor_timestamp_utc": 1,
                        "suggestion": 1,
                        "suggestion_size": 1,
                        "window_result_status": 1,
                        "window_result_attempt": 1,
                        "window_result_hit": 1,
                        "resolved_attempt": 1,
                        "resolved_number": 1,
                        "resolved_rank_position": 1,
                        "entry_shadow.recommendation": 1,
                        "oscillation.ml_entry_gate": 1,
                    }
                },
            ],
            allowDiskUse=True,
        ).to_list(length=limit)
        pending_docs = await suggestion_monitor_events_coll.aggregate(
            [
                {
                    "$match": {
                        "$and": [
                            filter_query,
                            {"status": "pending"},
                        ]
                    }
                },
                {"$sort": {"anchor_timestamp_utc": -1}},
                {"$limit": 20},
                {
                    "$project": {
                        "anchor_number": 1,
                        "anchor_timestamp_br": 1,
                        "anchor_timestamp_utc": 1,
                        "suggestion": 1,
                        "suggestion_size": 1,
                        "attempts_elapsed": 1,
                        "window_result_status": 1,
                        "entry_shadow.recommendation": 1,
                        "oscillation.ml_entry_gate": 1,
                    }
                },
            ],
            allowDiskUse=True,
        ).to_list(length=20)
        unavailable_docs = await suggestion_monitor_events_coll.aggregate(
            [
                {
                    "$match": {
                        "$and": [
                            filter_query,
                            {"status": "unavailable"},
                        ]
                    }
                },
                {"$sort": {"anchor_timestamp_utc": -1}},
                {"$limit": 20},
                {
                    "$project": {
                        "anchor_number": 1,
                        "anchor_timestamp_br": 1,
                        "anchor_timestamp_utc": 1,
                        "suggestion": 1,
                        "suggestion_size": 1,
                        "attempts_elapsed": 1,
                        "entry_shadow.recommendation": 1,
                        "oscillation.ml_entry_gate": 1,
                    }
                },
            ],
            allowDiskUse=True,
        ).to_list(length=20)
        docs.reverse()
        docs_list = [dict(doc) for doc in docs]
        items = _build_window_outcome_items(docs_list)
        hits_by_attempt = _build_window_hit_breakdown(docs_list, max_attempts=4)
        return {
            "roulette_id": roulette_id,
            "config_key": config_key,
            "ranking_variant": paths["label"],
            "total_events": total_events,
            "pending_events": pending_events,
            "unavailable_events": unavailable_events,
            "total_finalized": total_finalized,
            "total_hits": total_hits,
            "hit_rate": round(total_hits / total_finalized, 4) if total_finalized else 0.0,
            "hits_by_attempt": hits_by_attempt,
            "displayed_points": len(items),
            "truncated": total_finalized > len(items),
            "items": items,
            "pending_items": _build_window_monitor_aux_items([dict(doc) for doc in pending_docs]),
            "unavailable_items": _build_window_monitor_aux_items([dict(doc) for doc in unavailable_docs]),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/suggestion-monitor/streaks")
async def get_suggestion_monitor_streaks(
    roulette_id: str = Query(default="pragmatic-auto-roulette"),
    config_key: str | None = Query(default=None),
    limit: int = Query(default=2000, ge=10, le=10000),
    attempt_filter: str | None = Query(default=None),
    ranking_variant: str | None = Query(default="base"),
    shadow_action: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    start_hour: int | None = Query(default=None, ge=0, le=23),
    end_hour: int | None = Query(default=None, ge=0, le=23),
) -> Dict[str, Any]:
    try:
        await _ensure_monitor_indexes()
        paths = _variant_field_paths(ranking_variant)
        docs = await suggestion_monitor_events_coll.aggregate(
            [
                {
                    "$match": _build_event_filter(
                        roulette_id=roulette_id,
                        config_key=config_key,
                        status="resolved",
                        attempt_filter=attempt_filter,
                        ranking_variant=ranking_variant,
                        shadow_action=shadow_action,
                        start_date=start_date,
                        end_date=end_date,
                        start_hour=start_hour,
                        end_hour=end_hour,
                    )
                },
                {"$sort": {"anchor_timestamp_utc": 1}},
                {"$limit": int(limit)},
            ],
            allowDiskUse=True,
        ).to_list(length=limit)
        normalized_docs = _normalize_resolved_docs([dict(doc) for doc in docs])
        streaks = _compute_first_hit_streaks(normalized_docs)
        return {
            "roulette_id": roulette_id,
            "config_key": config_key,
            "ranking_variant": paths["label"],
            "events_analyzed": len(docs),
            **streaks,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/api/suggestion-monitor/reset")
async def reset_suggestion_monitor(
    roulette_id: str = Query(default="pragmatic-auto-roulette"),
    config_key: str | None = Query(default=None),
) -> Dict[str, Any]:
    try:
        base_filter = _build_base_filter(roulette_id, config_key)
        event_docs = await suggestion_monitor_events_coll.find(base_filter, {"_id": 1}).to_list(length=None)
        event_ids = [str(doc.get("_id")) for doc in event_docs if doc.get("_id") is not None]
        attempts_filter: Dict[str, Any]
        patterns_filter: Dict[str, Any]
        if event_ids:
            attempts_filter = {"suggestion_event_id": {"$in": event_ids}}
            patterns_filter = {"suggestion_event_id": {"$in": event_ids}}
        else:
            attempts_filter = {"roulette_id": roulette_id, "_id": {"$exists": False}}
            patterns_filter = {"roulette_id": roulette_id, "_id": {"$exists": False}}

        deleted_events = len(event_ids)
        deleted_attempts = await suggestion_monitor_attempts_coll.count_documents(attempts_filter)
        deleted_patterns = await suggestion_monitor_pattern_outcomes_coll.count_documents(patterns_filter)
        deleted_offsets = await suggestion_monitor_offsets_coll.count_documents(base_filter)

        if event_ids:
            await suggestion_monitor_events_coll.delete_many({"_id": {"$in": event_ids}})
            await suggestion_monitor_attempts_coll.delete_many(attempts_filter)
            await suggestion_monitor_pattern_outcomes_coll.delete_many(patterns_filter)
        await suggestion_monitor_events_coll.delete_many(base_filter)
        await suggestion_monitor_offsets_coll.delete_many(base_filter)

        control_payload = {
            "action": "reset_monitor",
            "roulette_id": roulette_id,
            "config_key": config_key,
        }
        published = await redis_client.publish(
            SUGGESTION_MONITOR_CONTROL_CHANNEL,
            json.dumps(control_payload),
        )

        return {
            "roulette_id": roulette_id,
            "config_key": config_key,
            "deleted_events": deleted_events,
            "deleted_attempts": deleted_attempts,
            "deleted_patterns": deleted_patterns,
            "deleted_offsets": deleted_offsets,
            "published_reset_signal": int(published or 0),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
