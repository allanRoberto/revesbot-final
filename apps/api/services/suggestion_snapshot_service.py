from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping
from bson import ObjectId

from api.core.db import (
    history_coll,
    suggestion_snapshot_configs_coll,
    suggestion_snapshots_coll,
)
from api.routes.patterns import FinalSuggestionRequest, _compute_final_suggestion


GLOBAL_SUGGESTION_SNAPSHOT_CONFIG_ID = "global-default"
SUGGESTION_SNAPSHOT_RANKING_SIZE = 37

DEFAULT_GLOBAL_SUGGESTION_SNAPSHOT_CONFIG: Dict[str, Any] = {
    "config_id": GLOBAL_SUGGESTION_SNAPSHOT_CONFIG_ID,
    "label": "Global Default",
    "history_limit": 2000,
    "base_weight": 0.4,
    "optimized_weight": 0.6,
    "siege_window": 6,
    "siege_min_occurrences": 3,
    "siege_min_streak": 2,
    "siege_veto_relief": 0.4,
    "block_bets_enabled": False,
    "inversion_enabled": True,
    "inversion_context_window": 15,
    "inversion_penalty_factor": 0.3,
    "weight_profile_id": None,
    "weight_profile_weights": {},
    "protected_mode_enabled": False,
    "protected_suggestion_size": 35,
    "protected_swap_enabled": False,
    "cold_count": 18,
    "occurrence_fusion_enabled": True,
    "occurrence_history_limit": 2000,
    "occurrence_window_before": 5,
    "occurrence_window_after": 3,
    "occurrence_ranking_size": 18,
    "occurrence_invert_check_window": 0,
    "occurrence_pattern_weight": 0.75,
    "occurrence_weight": 0.25,
    "occurrence_overlap_bonus": 0.05,
    "occurrence_tail_replace_limit": 2,
    "assertiveness_gate_enabled": True,
    "assertiveness_min_score": 55,
    "runtime_overrides": {},
}

_CONFIG_FIELDS = [
    "history_limit",
    "base_weight",
    "optimized_weight",
    "siege_window",
    "siege_min_occurrences",
    "siege_min_streak",
    "siege_veto_relief",
    "block_bets_enabled",
    "inversion_enabled",
    "inversion_context_window",
    "inversion_penalty_factor",
    "weight_profile_id",
    "weight_profile_weights",
    "protected_mode_enabled",
    "protected_suggestion_size",
    "protected_swap_enabled",
    "cold_count",
    "occurrence_fusion_enabled",
    "occurrence_history_limit",
    "occurrence_window_before",
    "occurrence_window_after",
    "occurrence_ranking_size",
    "occurrence_invert_check_window",
    "occurrence_pattern_weight",
    "occurrence_weight",
    "occurrence_overlap_bonus",
    "occurrence_tail_replace_limit",
    "assertiveness_gate_enabled",
    "assertiveness_min_score",
    "runtime_overrides",
]


def _serialize_datetime(value: Any) -> str | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return None


def _mongo_safe_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _mongo_safe_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_mongo_safe_value(item) for item in value]
    return value


def _normalize_config_document(raw_doc: Mapping[str, Any] | None) -> Dict[str, Any]:
    base = copy.deepcopy(DEFAULT_GLOBAL_SUGGESTION_SNAPSHOT_CONFIG)
    if isinstance(raw_doc, Mapping):
        for field in _CONFIG_FIELDS:
            if field in raw_doc:
                base[field] = raw_doc[field]
        if raw_doc.get("label"):
            base["label"] = str(raw_doc.get("label"))
        if raw_doc.get("config_id"):
            base["config_id"] = str(raw_doc.get("config_id"))
    base["history_limit"] = max(200, min(10000, int(base.get("history_limit") or 2000)))
    base["weight_profile_id"] = str(base.get("weight_profile_id") or "").strip() or None
    base["weight_profile_weights"] = dict(base.get("weight_profile_weights") or {})
    base["runtime_overrides"] = dict(base.get("runtime_overrides") or {})
    return base


def build_suggestion_snapshot_config_key(config_doc: Mapping[str, Any]) -> str:
    normalized = _normalize_config_document(config_doc)
    payload = {field: normalized.get(field) for field in _CONFIG_FIELDS}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha1(encoded.encode("utf-8")).hexdigest()[:16]
    return f"{normalized.get('config_id') or GLOBAL_SUGGESTION_SNAPSHOT_CONFIG_ID}:{digest}"


def build_suggestion_snapshot_id(*, roulette_id: str, anchor_history_id: str, config_key: str) -> str:
    digest = hashlib.sha1(
        f"{roulette_id}|{anchor_history_id}|{config_key}".encode("utf-8")
    ).hexdigest()[:24]
    return f"snap:{digest}"


def build_suggestion_snapshot_request(
    *,
    history: List[int],
    focus_number: int,
    config_doc: Mapping[str, Any],
) -> FinalSuggestionRequest:
    normalized = _normalize_config_document(config_doc)
    payload = {
        "history": [int(n) for n in history if 0 <= int(n) <= 36],
        "focus_number": int(focus_number),
        "from_index": 0,
        "max_numbers": SUGGESTION_SNAPSHOT_RANKING_SIZE,
        "optimized_max_numbers": SUGGESTION_SNAPSHOT_RANKING_SIZE,
        "base_weight": float(normalized["base_weight"]),
        "optimized_weight": float(normalized["optimized_weight"]),
        "runtime_overrides": dict(normalized.get("runtime_overrides") or {}),
        "siege_window": int(normalized["siege_window"]),
        "siege_min_occurrences": int(normalized["siege_min_occurrences"]),
        "siege_min_streak": int(normalized["siege_min_streak"]),
        "siege_veto_relief": float(normalized["siege_veto_relief"]),
        "block_bets_enabled": bool(normalized["block_bets_enabled"]),
        "inversion_enabled": bool(normalized["inversion_enabled"]),
        "inversion_context_window": int(normalized["inversion_context_window"]),
        "inversion_penalty_factor": float(normalized["inversion_penalty_factor"]),
        "weight_profile_id": normalized.get("weight_profile_id"),
        "weight_profile_weights": dict(normalized.get("weight_profile_weights") or {}),
        "protected_mode_enabled": bool(normalized["protected_mode_enabled"]),
        "protected_suggestion_size": int(normalized["protected_suggestion_size"]),
        "protected_swap_enabled": bool(normalized["protected_swap_enabled"]),
        "cold_count": int(normalized["cold_count"]),
        "occurrence_fusion_enabled": bool(normalized["occurrence_fusion_enabled"]),
        "occurrence_history_limit": int(normalized["occurrence_history_limit"]),
        "occurrence_window_before": int(normalized["occurrence_window_before"]),
        "occurrence_window_after": int(normalized["occurrence_window_after"]),
        "occurrence_ranking_size": int(normalized["occurrence_ranking_size"]),
        "occurrence_invert_check_window": int(normalized["occurrence_invert_check_window"]),
        "occurrence_pattern_weight": float(normalized["occurrence_pattern_weight"]),
        "occurrence_weight": float(normalized["occurrence_weight"]),
        "occurrence_overlap_bonus": float(normalized["occurrence_overlap_bonus"]),
        "occurrence_tail_replace_limit": int(normalized["occurrence_tail_replace_limit"]),
        "assertiveness_gate_enabled": bool(normalized["assertiveness_gate_enabled"]),
        "assertiveness_min_score": int(normalized["assertiveness_min_score"]),
    }
    return FinalSuggestionRequest(**payload)


def _slice_simple_payload(payload: Dict[str, Any], take: int) -> None:
    safe_take = max(1, min(SUGGESTION_SNAPSHOT_RANKING_SIZE, int(take)))
    for key in ("list", "suggestion", "ordered_suggestion"):
        values = payload.get(key)
        if isinstance(values, list):
            payload[key] = list(values[:safe_take])
    selected_details = payload.get("selected_number_details")
    if isinstance(selected_details, list):
        payload["selected_number_details"] = list(selected_details[:safe_take])
    payload["max_numbers"] = safe_take


def slice_snapshot_payload(payload: Mapping[str, Any], *, take: int) -> Dict[str, Any]:
    safe_take = max(1, min(SUGGESTION_SNAPSHOT_RANKING_SIZE, int(take)))
    cloned: Dict[str, Any] = copy.deepcopy(dict(payload))

    for key in ("list", "suggestion", "ordered_suggestion", "base_suggestion", "simple_suggestion"):
        values = cloned.get(key)
        if isinstance(values, list):
            cloned[key] = list(values[:safe_take])

    simple_payload = cloned.get("simple_payload")
    if isinstance(simple_payload, dict):
        _slice_simple_payload(simple_payload, safe_take)

    optimized_payload = cloned.get("optimized_payload")
    if isinstance(optimized_payload, dict):
        values = optimized_payload.get("suggestion")
        if isinstance(values, list):
            optimized_payload["suggestion"] = list(values[:safe_take])

    simple_number_details = cloned.get("simple_number_details")
    if isinstance(simple_number_details, list):
        cloned["simple_number_details"] = list(simple_number_details[:safe_take])

    return cloned


def _trim_contribution_list(items: Any) -> List[Dict[str, Any]]:
    if not isinstance(items, list):
        return []
    trimmed: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        trimmed.append(
            {
                "pattern_id": str(item.get("pattern_id") or ""),
                "pattern_name": str(item.get("pattern_name") or ""),
                "explanation": str(item.get("explanation") or ""),
                "numbers": [
                    int(value)
                    for value in (item.get("numbers") or [])
                    if isinstance(value, (int, float, str)) and str(value).strip().isdigit()
                ],
            }
        )
    return trimmed


def _trim_pending_patterns(items: Any) -> List[Dict[str, Any]]:
    if not isinstance(items, list):
        return []
    trimmed: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        rows = []
        for row in item.get("items") or []:
            if not isinstance(row, Mapping):
                continue
            rows.append(
                {
                    "origin": [int(value) for value in (row.get("origin") or []) if isinstance(value, int)],
                    "target": int(row.get("target")) if isinstance(row.get("target"), int) else None,
                    "target_sum": int(row.get("target_sum")) if isinstance(row.get("target_sum"), int) else None,
                    "remaining": int(row.get("remaining")) if isinstance(row.get("remaining"), int) else None,
                }
            )
        trimmed.append(
            {
                "pattern_id": str(item.get("pattern_id") or ""),
                "pattern_name": str(item.get("pattern_name") or ""),
                "items": rows,
            }
        )
    return trimmed


def _trim_adaptive_weights(items: Any) -> List[Dict[str, Any]]:
    if not isinstance(items, list):
        return []
    trimmed: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        trimmed.append(
            {
                "pattern_id": str(item.get("pattern_id") or ""),
                "pattern_name": str(item.get("pattern_name") or ""),
                "multiplier": float(item.get("multiplier") or 0),
                "hit_rate": float(item.get("hit_rate") or 0),
                "signals": int(item.get("signals") or 0),
                "hits": int(item.get("hits") or 0),
            }
        )
    return trimmed


def _trim_simple_number_details(items: Any, *, limit: int = 6) -> List[Dict[str, Any]]:
    if not isinstance(items, list):
        return []
    trimmed: List[Dict[str, Any]] = []
    for item in items[: max(0, int(limit))]:
        if not isinstance(item, Mapping):
            continue
        number = item.get("number")
        support_score = item.get("support_score")
        if not isinstance(number, int):
            continue
        trimmed.append(
            {
                "number": int(number),
                "support_score": int(support_score or 0),
            }
        )
    return trimmed


def build_frontend_snapshot_payload(payload: Mapping[str, Any], *, take: int) -> Dict[str, Any]:
    sliced = slice_snapshot_payload(payload, take=take)
    optimized_payload = sliced.get("optimized_payload") if isinstance(sliced.get("optimized_payload"), Mapping) else {}
    simple_payload = sliced.get("simple_payload") if isinstance(sliced.get("simple_payload"), Mapping) else {}

    return {
        "available": bool(sliced.get("available", False)),
        "suggestion": list(sliced.get("suggestion") or sliced.get("list") or []),
        "ranking_locked": bool(sliced.get("ranking_locked", False)),
        "confidence": dict(sliced.get("confidence") or {}),
        "explanation": str(sliced.get("explanation") or ""),
        "protections": list(sliced.get("protections") or []),
        "invertedInFinal": list(sliced.get("invertedInFinal") or []),
        "invertedRemoved": list(sliced.get("invertedRemoved") or []),
        "protected_mode_enabled": bool(sliced.get("protected_mode_enabled", False)),
        "protected_suggestion_size": sliced.get("protected_suggestion_size"),
        "protected_swap_enabled": bool(sliced.get("protected_swap_enabled", False)),
        "protected_swap_applied": bool(sliced.get("protected_swap_applied", False)),
        "protected_swap_summary": str(sliced.get("protected_swap_summary") or ""),
        "protected_excluded_numbers": list(sliced.get("protected_excluded_numbers") or []),
        "protected_original_excluded_numbers": list(sliced.get("protected_original_excluded_numbers") or []),
        "protected_guard_numbers": list(sliced.get("protected_guard_numbers") or []),
        "protected_wait_triggered": bool(sliced.get("protected_wait_triggered", False)),
        "protected_wait_recommended_spins": int(sliced.get("protected_wait_recommended_spins") or 0),
        "protected_wait_reason": str(sliced.get("protected_wait_reason") or ""),
        "excluded_tail_numbers": list(sliced.get("excluded_tail_numbers") or []),
        "signal_quality": dict(sliced.get("signal_quality") or {}),
        "optimized_payload": {
            "available": bool(optimized_payload.get("available", False)),
            "suggestion": list(optimized_payload.get("suggestion") or []),
            "explanation": str(optimized_payload.get("explanation") or ""),
            "confidence": dict(optimized_payload.get("confidence") or {}),
            "confidence_breakdown": dict(optimized_payload.get("confidence_breakdown") or {}),
            "contributions": _trim_contribution_list(optimized_payload.get("contributions")),
            "negative_contributions": _trim_contribution_list(optimized_payload.get("negative_contributions")),
            "pending_patterns": _trim_pending_patterns(optimized_payload.get("pending_patterns")),
            "adaptive_weights": _trim_adaptive_weights(optimized_payload.get("adaptive_weights")),
        },
        "simple_payload": {
            "available": bool(simple_payload.get("available", False)),
            "suggestion": list(simple_payload.get("suggestion") or simple_payload.get("list") or []),
            "explanation": str(simple_payload.get("explanation") or ""),
            "number_details": _trim_simple_number_details(simple_payload.get("number_details")),
            "pattern_count": int(simple_payload.get("pattern_count") or 0),
            "unique_numbers": int(simple_payload.get("unique_numbers") or 0),
            "top_support_count": int(simple_payload.get("top_support_count") or 0),
            "min_support_count": int(simple_payload.get("min_support_count") or 0),
            "avg_support_count": float(simple_payload.get("avg_support_count") or 0),
            "ranking_locked": bool(simple_payload.get("ranking_locked", True)),
            "entry_shadow": dict(simple_payload.get("entry_shadow") or {}),
            "signal_quality": dict(simple_payload.get("signal_quality") or {}),
        },
    }


async def get_or_create_global_suggestion_snapshot_config() -> Dict[str, Any]:
    existing = await suggestion_snapshot_configs_coll.find_one(
        {"config_id": GLOBAL_SUGGESTION_SNAPSHOT_CONFIG_ID}
    )
    if isinstance(existing, Mapping):
        return _normalize_config_document(existing)

    document = _normalize_config_document(DEFAULT_GLOBAL_SUGGESTION_SNAPSHOT_CONFIG)
    document["created_at_utc"] = datetime.now(timezone.utc)
    document["updated_at_utc"] = document["created_at_utc"]
    await suggestion_snapshot_configs_coll.update_one(
        {"config_id": GLOBAL_SUGGESTION_SNAPSHOT_CONFIG_ID},
        {"$setOnInsert": document},
        upsert=True,
    )
    created = await suggestion_snapshot_configs_coll.find_one(
        {"config_id": GLOBAL_SUGGESTION_SNAPSHOT_CONFIG_ID}
    )
    if isinstance(created, Mapping):
        return _normalize_config_document(created)
    return document


async def _load_history_docs_for_anchor(roulette_id: str, *, from_index: int, history_limit: int) -> List[Dict[str, Any]]:
    safe_from_index = max(0, int(from_index))
    safe_limit = max(50, min(20000, safe_from_index + max(1, int(history_limit))))
    docs = await (
        history_coll.find({"roulette_id": roulette_id})
        .sort("timestamp", -1)
        .limit(safe_limit)
        .to_list(length=safe_limit)
    )
    return [dict(doc) for doc in docs]


async def _load_history_doc_by_id(roulette_id: str, history_id: str) -> Dict[str, Any] | None:
    raw_history_id = str(history_id or "").strip()
    if not raw_history_id:
        return None
    try:
        object_id = ObjectId(raw_history_id)
    except Exception:
        return None
    doc = await history_coll.find_one({"_id": object_id, "roulette_id": roulette_id})
    return dict(doc) if isinstance(doc, Mapping) else None


async def _compute_and_persist_snapshot(
    *,
    roulette_id: str,
    anchor_doc: Mapping[str, Any],
    history_at_anchor: List[int],
    config_doc: Mapping[str, Any],
    source: str,
) -> Dict[str, Any]:
    anchor_history_id = str(anchor_doc.get("_id"))
    anchor_number = int(anchor_doc.get("value"))
    config_key = build_suggestion_snapshot_config_key(config_doc)
    snapshot_id = build_suggestion_snapshot_id(
        roulette_id=roulette_id,
        anchor_history_id=anchor_history_id,
        config_key=config_key,
    )

    request = build_suggestion_snapshot_request(
        history=history_at_anchor,
        focus_number=anchor_number,
        config_doc=config_doc,
    )
    payload = await _compute_final_suggestion(request)
    now = datetime.now(timezone.utc)
    document = {
        "_id": snapshot_id,
        "snapshot_id": snapshot_id,
        "roulette_id": roulette_id,
        "anchor_history_id": anchor_history_id,
        "anchor_number": anchor_number,
        "anchor_timestamp_utc": anchor_doc.get("timestamp"),
        "config_id": str(config_doc.get("config_id") or GLOBAL_SUGGESTION_SNAPSHOT_CONFIG_ID),
        "config_key": config_key,
        "ranking_size": SUGGESTION_SNAPSHOT_RANKING_SIZE,
        "history_size_used": len(history_at_anchor),
        "payload": _mongo_safe_value(payload),
        "source": source,
        "created_at_utc": now,
        "updated_at_utc": now,
    }
    await suggestion_snapshots_coll.update_one(
        {"_id": snapshot_id},
        {"$setOnInsert": document},
        upsert=True,
    )
    saved = await suggestion_snapshots_coll.find_one({"_id": snapshot_id})
    return dict(saved) if isinstance(saved, Mapping) else document


def _serialize_snapshot_response(snapshot_doc: Mapping[str, Any], *, take: int) -> Dict[str, Any]:
    sliced_payload = build_frontend_snapshot_payload(snapshot_doc.get("payload") or {}, take=take)
    return {
        "available": bool(sliced_payload.get("available", False)),
        "result": sliced_payload,
        "snapshot": {
            "snapshot_id": str(snapshot_doc.get("snapshot_id") or snapshot_doc.get("_id") or ""),
            "roulette_id": str(snapshot_doc.get("roulette_id") or ""),
            "anchor_history_id": str(snapshot_doc.get("anchor_history_id") or ""),
            "anchor_number": int(snapshot_doc.get("anchor_number") or -1),
            "anchor_timestamp_utc": _serialize_datetime(snapshot_doc.get("anchor_timestamp_utc")),
            "config_id": str(snapshot_doc.get("config_id") or ""),
            "config_key": str(snapshot_doc.get("config_key") or ""),
            "ranking_size": int(snapshot_doc.get("ranking_size") or SUGGESTION_SNAPSHOT_RANKING_SIZE),
            "history_size_used": int(snapshot_doc.get("history_size_used") or 0),
            "source": str(snapshot_doc.get("source") or ""),
            "created_at_utc": _serialize_datetime(snapshot_doc.get("created_at_utc")),
        },
    }


async def resolve_suggestion_snapshot_by_index(
    *,
    roulette_id: str,
    from_index: int,
    take: int,
    source: str = "api_on_demand",
    create_if_missing: bool = True,
) -> Dict[str, Any]:
    config_doc = await get_or_create_global_suggestion_snapshot_config()
    docs = await _load_history_docs_for_anchor(
        roulette_id,
        from_index=from_index,
        history_limit=int(config_doc.get("history_limit") or 2000),
    )
    safe_from_index = max(0, int(from_index))
    if safe_from_index >= len(docs):
        raise LookupError("Âncora de histórico não encontrada para a roleta informada.")

    anchor_doc = docs[safe_from_index]
    anchor_history_id = str(anchor_doc.get("_id"))
    config_key = build_suggestion_snapshot_config_key(config_doc)
    snapshot_doc = await suggestion_snapshots_coll.find_one(
        {
            "roulette_id": roulette_id,
            "anchor_history_id": anchor_history_id,
            "config_key": config_key,
        }
    )
    cache_status = "hit"
    if not isinstance(snapshot_doc, Mapping):
        if not create_if_missing:
            raise LookupError("Não foi gerada a sugestão para esse número.")
        history_at_anchor = [
            int(doc.get("value"))
            for doc in docs[safe_from_index : safe_from_index + int(config_doc.get("history_limit") or 2000)]
            if 0 <= int(doc.get("value")) <= 36
        ]
        snapshot_doc = await _compute_and_persist_snapshot(
            roulette_id=roulette_id,
            anchor_doc=anchor_doc,
            history_at_anchor=history_at_anchor,
            config_doc=config_doc,
            source=source,
        )
        cache_status = "created"

    response = _serialize_snapshot_response(snapshot_doc, take=take)
    response["snapshot"]["cache_status"] = cache_status
    return response


def _extract_snapshot_ranking(snapshot_doc: Mapping[str, Any]) -> List[int]:
    payload = snapshot_doc.get("payload") if isinstance(snapshot_doc, Mapping) else None
    if not isinstance(payload, Mapping):
        return []
    for key in ("suggestion", "list", "ordered_suggestion", "base_suggestion", "simple_suggestion"):
        values = payload.get(key)
        if not isinstance(values, list):
            continue
        ranking: List[int] = []
        seen: set[int] = set()
        for value in values:
            try:
                number = int(value)
            except Exception:
                continue
            if not (0 <= number <= 36) or number in seen:
                continue
            seen.add(number)
            ranking.append(number)
            if len(ranking) >= SUGGESTION_SNAPSHOT_RANKING_SIZE:
                break
        if ranking:
            return ranking
    return []


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _extract_snapshot_timeline_context(snapshot_doc: Mapping[str, Any], ranking: List[int]) -> Dict[str, Any]:
    payload = snapshot_doc.get("payload") if isinstance(snapshot_doc, Mapping) else None
    if not isinstance(payload, Mapping):
        return {}

    simple_payload = payload.get("simple_payload") if isinstance(payload.get("simple_payload"), Mapping) else {}
    optimized_payload = payload.get("optimized_payload") if isinstance(payload.get("optimized_payload"), Mapping) else {}
    signal_quality = payload.get("signal_quality") if isinstance(payload.get("signal_quality"), Mapping) else {}
    simple_signal_quality = payload.get("simple_signal_quality") if isinstance(payload.get("simple_signal_quality"), Mapping) else {}
    if not simple_signal_quality and isinstance(simple_payload.get("signal_quality"), Mapping):
        simple_signal_quality = dict(simple_payload.get("signal_quality") or {})
    confidence = payload.get("confidence") if isinstance(payload.get("confidence"), Mapping) else {}
    optimized_confidence = optimized_payload.get("confidence") if isinstance(optimized_payload.get("confidence"), Mapping) else {}

    simple_suggestion_raw = simple_payload.get("suggestion") or simple_payload.get("list") or []
    simple_suggestion = [int(value) for value in simple_suggestion_raw if isinstance(value, int) or str(value).isdigit()]

    top12_rank = ranking[:12]
    top18_rank = ranking[:18]
    top12_simple = simple_suggestion[:12]
    top18_simple = simple_suggestion[:18]

    overlap_top12 = len(set(top12_rank).intersection(top12_simple))
    overlap_top18 = len(set(top18_rank).intersection(top18_simple))

    return {
        "confidence_score": _safe_float(confidence.get("score"), 0.0),
        "optimized_confidence_score": _safe_float(
            payload.get("optimized_confidence_effective")
            or optimized_payload.get("confidence_effective_score")
            or optimized_confidence.get("score"),
            0.0,
        ),
        "signal_quality_score": _safe_float(signal_quality.get("score"), 0.0),
        "simple_signal_quality_score": _safe_float(simple_signal_quality.get("score"), 0.0),
        "simple_pattern_count": _safe_int(
            payload.get("simple_pattern_count") or simple_payload.get("pattern_count"),
            0,
        ),
        "simple_top_support_count": _safe_int(simple_payload.get("top_support_count"), 0),
        "simple_avg_support_count": _safe_float(simple_payload.get("avg_support_count"), 0.0),
        "simple_unique_numbers": _safe_int(
            payload.get("simple_unique_numbers") or simple_payload.get("unique_numbers"),
            0,
        ),
        "occurrence_overlap_count": _safe_int(
            payload.get("simple_occurrence_overlap_count")
            or simple_payload.get("occurrence_overlap_count"),
            0,
        ),
        "occurrence_inverted_detected": bool(
            payload.get("simple_occurrence_inverted_detected")
            or simple_payload.get("occurrence_inverted_detected")
        ),
        "ranking_locked": bool(payload.get("ranking_locked") or simple_payload.get("ranking_locked")),
        "top12_simple_overlap": overlap_top12,
        "top18_simple_overlap": overlap_top18,
        "top12_simple_overlap_ratio": round(overlap_top12 / 12.0, 4),
        "top18_simple_overlap_ratio": round(overlap_top18 / 18.0, 4),
        "ranking_size": len(ranking),
    }


STRATEGY_OUTSIDE_RANK = 38
STRATEGY_MIN_CORRECTION = 4
STRATEGY_SMALL_EDGE_SIZE = 5
STRATEGY_MEDIUM_EDGE_SIZE = 8
STRATEGY_LARGE_EDGE_SIZE = 10
STRATEGY_SCORE_THRESHOLD_SMALL = 4.0
STRATEGY_SCORE_THRESHOLD_MEDIUM = 6.0
STRATEGY_SCORE_THRESHOLD_LARGE = 9.0
STRATEGY_SCORE_DECAY_PER_STEP = 0.35
STRATEGY_SCORE_MAX = 18.0
RANGE_PREDICTION_LOOKBACK = 12
RANGE_PREDICTION_NEIGHBORS = 15
RANGE_PREDICTION_SIZE = 18
RANGE_PREDICTION_MIN_TRAIN_ROWS = 120
RANGE_POLICY_BALANCED = {
    "name": "movement_range_middle_filter_v1",
    "confidence_threshold": 0.76,
    "coverage_threshold": 0.76,
    "concentration_threshold": 0.0,
    "direction_consistency_threshold": 0.0,
    "middle_overlap_max": 0.66,
    "support_threshold": 10,
}


def _invert_rank_extremes(rank: int | None, edge_size: int) -> int | None:
    if rank is None:
        return None
    safe_rank = int(rank)
    if not (1 <= safe_rank <= 37):
        return safe_rank
    safe_edge_size = max(1, min(18, int(edge_size)))
    bottom_start = 38 - safe_edge_size
    if safe_rank <= safe_edge_size:
        return 38 - safe_rank
    if safe_rank >= bottom_start:
        return 38 - safe_rank
    return safe_rank


def _resolve_inversion_depth(regime_score: float) -> int:
    safe_score = float(regime_score or 0.0)
    if safe_score >= STRATEGY_SCORE_THRESHOLD_LARGE:
        return STRATEGY_LARGE_EDGE_SIZE
    if safe_score >= STRATEGY_SCORE_THRESHOLD_MEDIUM:
        return STRATEGY_MEDIUM_EDGE_SIZE
    if safe_score >= STRATEGY_SCORE_THRESHOLD_SMALL:
        return STRATEGY_SMALL_EDGE_SIZE
    return 0


def _update_falling_regime_score(
    *,
    regime_score: float,
    previous_rank: int | None,
    current_rank: int | None,
    improvement_streak: int,
) -> tuple[float, int]:
    score = max(0.0, float(regime_score or 0.0) - STRATEGY_SCORE_DECAY_PER_STEP)
    streak = max(0, int(improvement_streak or 0))

    if not isinstance(previous_rank, int) or not isinstance(current_rank, int):
        return (round(min(score, STRATEGY_SCORE_MAX), 2), streak)

    delta = int(current_rank) - int(previous_rank)

    if delta >= STRATEGY_MIN_CORRECTION:
        if previous_rank <= 10:
            score += min(6.5, 1.8 + (delta * 0.42))
        elif previous_rank <= 18:
            score += min(4.5, 0.8 + (delta * 0.24))
        else:
            score += min(2.5, delta * 0.10)

        if current_rank >= 33:
            score += 2.5
        elif current_rank >= 28:
            score += 1.5
        elif current_rank >= 19:
            score += 0.6
        streak = 0
    elif delta < 0:
        improvement = abs(delta)
        if previous_rank >= 28 and current_rank <= 20:
            score -= min(5.0, 1.4 + (improvement * 0.18))
        elif current_rank <= 10:
            score -= min(2.4, 0.8 + (improvement * 0.14))
        elif current_rank <= 18:
            score -= min(1.2, 0.35 + (improvement * 0.06))
        else:
            score -= min(0.6, improvement * 0.03)
        streak = (streak + 1) if current_rank <= 18 else 0
    else:
        if current_rank >= 28:
            score += 0.4
        streak = 0

    score = max(0.0, min(score, STRATEGY_SCORE_MAX))
    return (round(score, 2), streak)


def _apply_inversion_strategy(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    triggered_items = 0
    strategy_distribution = {str(rank): 0 for rank in range(1, 38)}
    strategy_hit_items: List[Dict[str, Any]] = []
    depth_counts = {
        str(STRATEGY_SMALL_EDGE_SIZE): 0,
        str(STRATEGY_MEDIUM_EDGE_SIZE): 0,
        str(STRATEGY_LARGE_EDGE_SIZE): 0,
    }
    regime_score = 0.0
    improvement_streak = 0
    observed_ranks: List[int] = []

    for item in items:
        original_hit_rank = item.get("hit_rank")
        strategy_invert_depth = _resolve_inversion_depth(regime_score)
        strategy_mode = "inverted_extremes" if strategy_invert_depth > 0 else "normal"
        strategy_triggered = strategy_invert_depth > 0
        strategy_trigger_reason = "falling_regime_active" if strategy_triggered else ""
        strategy_reference_ranks: List[int] = observed_ranks[-3:]
        strategy_signal_strength = round(regime_score, 2)
        strategy_hit_rank = original_hit_rank
        strategy_plot_rank = item.get("plot_rank")
        if strategy_invert_depth > 0:
            depth_counts[str(strategy_invert_depth)] += 1
            triggered_items += 1
            if isinstance(original_hit_rank, int):
                strategy_hit_rank = _invert_rank_extremes(original_hit_rank, strategy_invert_depth)
                strategy_plot_rank = strategy_hit_rank
            else:
                strategy_plot_rank = STRATEGY_OUTSIDE_RANK

        item["strategy_mode"] = strategy_mode
        item["strategy_triggered"] = strategy_triggered
        item["strategy_trigger_reason"] = strategy_trigger_reason
        item["strategy_reference_ranks"] = strategy_reference_ranks
        item["strategy_invert_depth"] = strategy_invert_depth
        item["strategy_signal_strength"] = round(strategy_signal_strength, 2)
        item["strategy_hit_rank"] = strategy_hit_rank
        item["strategy_plot_rank"] = strategy_plot_rank

        if isinstance(strategy_hit_rank, int):
            strategy_distribution[str(int(strategy_hit_rank))] += 1
            strategy_hit_items.append(item)

        previous_rank = observed_ranks[-1] if observed_ranks else None
        regime_score, improvement_streak = _update_falling_regime_score(
            regime_score=regime_score,
            previous_rank=previous_rank,
            current_rank=int(original_hit_rank) if isinstance(original_hit_rank, int) else None,
            improvement_streak=improvement_streak,
        )
        if isinstance(original_hit_rank, int):
            observed_ranks.append(int(original_hit_rank))

    strategy_resolved_items = [item for item in items if item.get("next_number") is not None]
    strategy_outside = len([item for item in strategy_resolved_items if item.get("strategy_hit_rank") is None])

    return {
        "enabled": True,
        "name": "inverted_extremes_movement_v2",
        "min_correction": STRATEGY_MIN_CORRECTION,
        "depth_options": [
            STRATEGY_SMALL_EDGE_SIZE,
            STRATEGY_MEDIUM_EDGE_SIZE,
            STRATEGY_LARGE_EDGE_SIZE,
        ],
        "score_thresholds": {
            str(STRATEGY_SMALL_EDGE_SIZE): STRATEGY_SCORE_THRESHOLD_SMALL,
            str(STRATEGY_MEDIUM_EDGE_SIZE): STRATEGY_SCORE_THRESHOLD_MEDIUM,
            str(STRATEGY_LARGE_EDGE_SIZE): STRATEGY_SCORE_THRESHOLD_LARGE,
        },
        "depth_counts": depth_counts,
        "preserved_middle_ranges": {
            str(STRATEGY_SMALL_EDGE_SIZE): [STRATEGY_SMALL_EDGE_SIZE + 1, 37 - STRATEGY_SMALL_EDGE_SIZE],
            str(STRATEGY_MEDIUM_EDGE_SIZE): [STRATEGY_MEDIUM_EDGE_SIZE + 1, 37 - STRATEGY_MEDIUM_EDGE_SIZE],
            str(STRATEGY_LARGE_EDGE_SIZE): [STRATEGY_LARGE_EDGE_SIZE + 1, 37 - STRATEGY_LARGE_EDGE_SIZE],
        },
        "triggered_items": triggered_items,
        "resolved_items": len(strategy_resolved_items),
        "hits_in_ranking": len(strategy_hit_items),
        "outside_ranking": strategy_outside,
        "hit_rate_percent": round((len(strategy_hit_items) / len(strategy_resolved_items) * 100.0), 2) if strategy_resolved_items else 0.0,
        "top_1_hits": strategy_distribution["1"],
        "top_3_hits": sum(strategy_distribution[str(rank)] for rank in range(1, 4)),
        "top_5_hits": sum(strategy_distribution[str(rank)] for rank in range(1, 6)),
        "top_10_hits": sum(strategy_distribution[str(rank)] for rank in range(1, 11)),
        "avg_hit_rank": round(sum(int(item["strategy_hit_rank"]) for item in strategy_hit_items) / len(strategy_hit_items), 2) if strategy_hit_items else None,
        "rank_distribution": strategy_distribution,
    }


def _build_rank_movement_vector(previous_ranks: List[int]) -> List[float]:
    if not previous_ranks:
        return []
    safe = [int(rank) for rank in previous_ranks]
    deltas = [float(safe[idx] - safe[idx + 1]) for idx in range(len(safe) - 1)]
    amplitude = float(max(safe) - min(safe))
    momentum = float(safe[0] - safe[-1])
    avg_rank = float(sum(safe) / len(safe))
    return [float(rank) for rank in safe] + deltas + [amplitude, momentum, avg_rank]


def _sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _movement_distance(left: List[float], right: List[float]) -> float:
    if not left or not right or len(left) != len(right):
        return float("inf")
    return sum(abs(float(a) - float(b)) for a, b in zip(left, right))


def _resolve_best_rank_window(
    nearest_rows: List[tuple[float, Dict[str, Any]]],
    *,
    window_size: int = RANGE_PREDICTION_SIZE,
) -> Dict[str, Any]:
    safe_window = max(1, min(37, int(window_size or RANGE_PREDICTION_SIZE)))
    max_start = max(1, 37 - safe_window + 1)
    total_weight = 0.0
    direction_weights = {-1: 0.0, 0: 0.0, 1: 0.0}
    weighted_neighbors: List[Dict[str, Any]] = []

    for distance, row in nearest_rows:
        weight = 1.0 / (float(distance) + 0.001)
        total_weight += weight
        latest_rank = int(row.get("current_rank") or 38)
        first_future_rank = int((row.get("future_ranks") or [38])[0])
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
        "end": safe_window,
        "center": round((1 + safe_window) / 2.0, 2),
        "coverage_ratio": 0.0,
        "concentration_score": 0.0,
        "confidence": 0.0,
    }

    for start in range(1, max_start + 1):
        end = start + safe_window - 1
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
            concentration_score = 1.0 - min(1.0, avg_distance / max(1.0, (safe_window - 1) / 2.0))
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
            "size": safe_window,
            "direction_consistency": round(direction_consistency, 4),
            "expected_direction": (
                "subida" if dominant_direction < 0 else "queda" if dominant_direction > 0 else "indefinida"
            ),
            "support_weight_percent": round(best_payload["coverage_ratio"] * 100.0, 2),
        }
    )
    return best_payload


def _apply_movement_range_prediction(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    predicted_items = 0
    hits_in_range = 0
    misses_in_range = 0
    pending_items = 0
    policy_allowed = 0
    policy_blocked = 0
    blocked_by_middle = 0
    observed_ranks: List[int | None] = [
        int(item["plot_rank"]) if isinstance(item.get("plot_rank"), int) else None
        for item in items
    ]

    for item_index, item in enumerate(items):
        prediction = {
            "available": False,
            "start": None,
            "end": None,
            "size": RANGE_PREDICTION_SIZE,
            "center": None,
            "support_weight_percent": None,
            "coverage_ratio": None,
            "concentration_score": None,
            "direction_consistency": None,
            "expected_direction": "indefinida",
            "hit": None,
            "status": "insuficiente",
            "lookback": RANGE_PREDICTION_LOOKBACK,
            "neighbors": 0,
            "future_attempts": 3,
            "future_ranks": [],
            "middle_overlap_ratio": None,
            "policy": {
                "name": RANGE_POLICY_BALANCED["name"],
                "bettable": None,
                "status": "insuficiente",
            },
        }
        current_rank = observed_ranks[item_index]
        if not isinstance(current_rank, int):
            item["range_prediction"] = prediction
            continue
        future_ranks = [
            int(rank)
            for rank in observed_ranks[item_index + 1 : item_index + 4]
            if isinstance(rank, int)
        ]

        if item_index >= (RANGE_PREDICTION_LOOKBACK - 1 + RANGE_PREDICTION_MIN_TRAIN_ROWS):
            current_pattern = [
                int(observed_ranks[item_index - step])
                for step in range(0, RANGE_PREDICTION_LOOKBACK)
                if isinstance(observed_ranks[item_index - step], int)
            ]
            if len(current_pattern) != RANGE_PREDICTION_LOOKBACK:
                item["range_prediction"] = prediction
                continue
            current_vector = _build_rank_movement_vector(current_pattern)
            candidates: List[tuple[float, Dict[str, Any]]] = []

            for target_index in range(RANGE_PREDICTION_LOOKBACK - 1, item_index):
                history_slice = observed_ranks[target_index - RANGE_PREDICTION_LOOKBACK + 1 : target_index + 1]
                if len(history_slice) != RANGE_PREDICTION_LOOKBACK or any(rank is None for rank in history_slice):
                    continue
                neighbor_future_ranks = [
                    int(rank)
                    for rank in observed_ranks[target_index + 1 : target_index + 4]
                    if isinstance(rank, int)
                ]
                if not neighbor_future_ranks:
                    continue
                train_pattern = list(reversed(history_slice))
                train_vector = _build_rank_movement_vector(train_pattern)
                distance = _movement_distance(current_vector, train_vector)
                if distance == float("inf"):
                    continue
                candidates.append(
                    (
                        distance,
                        {
                            "current_rank": int(history_slice[-1]),
                            "future_ranks": neighbor_future_ranks,
                        },
                    )
                )

            if candidates:
                candidates.sort(key=lambda entry: entry[0])
                nearest = candidates[: max(1, min(RANGE_PREDICTION_NEIGHBORS, len(candidates)))]
                best_window = _resolve_best_rank_window(
                    nearest,
                    window_size=RANGE_PREDICTION_SIZE,
                )
                prediction_hit = None
                prediction_status = "pendente"
                if future_ranks:
                    if all(isinstance(rank, int) for rank in future_ranks):
                        prediction_hit = bool(any(best_window["start"] <= rank <= best_window["end"] for rank in future_ranks))
                        prediction_status = "acertou" if prediction_hit else "errou"
                    else:
                        prediction_hit = False
                        prediction_status = "errou"

                middle_overlap_ratio = round(
                    max(0, min(int(best_window["end"]), 25) - max(int(best_window["start"]), 13) + 1)
                    / max(1, int(best_window["size"])),
                    4,
                )
                prediction_confidence = float(best_window["confidence"])
                policy_bettable = (
                    prediction_confidence >= float(RANGE_POLICY_BALANCED["confidence_threshold"])
                    and float(best_window["coverage_ratio"]) >= float(RANGE_POLICY_BALANCED["coverage_threshold"])
                    and float(best_window["concentration_score"]) >= float(RANGE_POLICY_BALANCED["concentration_threshold"])
                    and float(best_window["direction_consistency"]) >= float(RANGE_POLICY_BALANCED["direction_consistency_threshold"])
                    and middle_overlap_ratio <= float(RANGE_POLICY_BALANCED["middle_overlap_max"])
                    and len(nearest) >= int(RANGE_POLICY_BALANCED["support_threshold"])
                )
                policy_reason = "miolo" if middle_overlap_ratio > float(RANGE_POLICY_BALANCED["middle_overlap_max"]) else "score"

                prediction = {
                    "available": True,
                    "start": int(best_window["start"]),
                    "end": int(best_window["end"]),
                    "size": int(best_window["size"]),
                    "center": best_window["center"],
                    "support_weight_percent": best_window["support_weight_percent"],
                    "coverage_ratio": best_window["coverage_ratio"],
                    "concentration_score": best_window["concentration_score"],
                    "direction_consistency": best_window["direction_consistency"],
                    "expected_direction": best_window["expected_direction"],
                    "confidence": prediction_confidence,
                    "hit": prediction_hit,
                    "status": prediction_status,
                    "lookback": RANGE_PREDICTION_LOOKBACK,
                    "neighbors": len(nearest),
                    "future_attempts": 3,
                    "future_ranks": future_ranks,
                    "middle_overlap_ratio": middle_overlap_ratio,
                    "policy": {
                        "name": RANGE_POLICY_BALANCED["name"],
                        "bettable": bool(policy_bettable),
                        "status": "apostar" if policy_bettable else "bloquear",
                        "reason": policy_reason,
                    },
                }
                predicted_items += 1
                if prediction_hit is True:
                    hits_in_range += 1
                elif prediction_hit is False:
                    misses_in_range += 1
                else:
                    pending_items += 1
                if policy_bettable:
                    policy_allowed += 1
                else:
                    policy_blocked += 1
                    if policy_reason == "miolo":
                        blocked_by_middle += 1

        item["range_prediction"] = prediction

    resolved_predictions = hits_in_range + misses_in_range
    return {
        "enabled": True,
        "name": "movement_range_v2_three_attempts",
        "lookback": RANGE_PREDICTION_LOOKBACK,
        "neighbors": RANGE_PREDICTION_NEIGHBORS,
        "range_size": RANGE_PREDICTION_SIZE,
        "future_attempts": 3,
        "predicted_items": predicted_items,
        "resolved_predictions": resolved_predictions,
        "hits_in_range": hits_in_range,
        "misses_in_range": misses_in_range,
        "pending_predictions": pending_items,
        "hit_rate_percent": round((hits_in_range / resolved_predictions) * 100.0, 2) if resolved_predictions else 0.0,
        "policy": {
            **RANGE_POLICY_BALANCED,
            "allowed_items": policy_allowed,
            "blocked_items": policy_blocked,
            "blocked_by_middle": blocked_by_middle,
            "blocked_rate_percent": round((policy_blocked / predicted_items) * 100.0, 2) if predicted_items else 0.0,
        },
    }


async def build_suggestion_snapshot_rank_timeline(
    *,
    roulette_id: str,
    limit: int = 200,
    include_all_configs: bool = False,
) -> Dict[str, Any]:
    safe_limit = max(20, min(2000, int(limit or 200)))
    config_doc = await get_or_create_global_suggestion_snapshot_config()
    current_config_key = build_suggestion_snapshot_config_key(config_doc)

    snapshot_query: Dict[str, Any] = {"roulette_id": roulette_id}
    if not include_all_configs:
        snapshot_query["config_key"] = current_config_key

    fetch_limit = min(safe_limit + 10, 2500)
    snapshot_docs = await (
        suggestion_snapshots_coll.find(snapshot_query)
        .sort("anchor_timestamp_utc", -1)
        .limit(fetch_limit)
        .to_list(length=fetch_limit)
    )
    snapshots = [dict(doc) for doc in snapshot_docs if isinstance(doc, Mapping)]
    if not snapshots:
        raise LookupError("Nenhum snapshot de sugestão encontrado para a roleta informada.")

    history_fetch_limit = min(max(fetch_limit * 6, 300), 5000)
    history_docs_raw = await (
        history_coll.find({"roulette_id": roulette_id})
        .sort("timestamp", -1)
        .limit(history_fetch_limit)
        .to_list(length=history_fetch_limit)
    )
    history_docs = [dict(doc) for doc in history_docs_raw if isinstance(doc, Mapping)]
    history_index = {str(doc.get("_id")): idx for idx, doc in enumerate(history_docs)}

    items_desc: List[Dict[str, Any]] = []
    unresolved_count = 0
    missing_history_count = 0

    for snapshot_doc in snapshots:
        anchor_history_id = str(snapshot_doc.get("anchor_history_id") or "").strip()
        if not anchor_history_id:
            missing_history_count += 1
            continue
        anchor_idx = history_index.get(anchor_history_id)
        if anchor_idx is None:
            missing_history_count += 1
            continue

        next_doc = history_docs[anchor_idx - 1] if anchor_idx > 0 else None
        ranking = _extract_snapshot_ranking(snapshot_doc)
        anchor_number = int(snapshot_doc.get("anchor_number") or -1)
        next_number = None
        next_history_id = ""
        next_timestamp_utc = None
        hit_rank = None
        plot_rank = None
        hit = False

        if isinstance(next_doc, Mapping):
            next_number = int(next_doc.get("value"))
            next_history_id = str(next_doc.get("_id") or "")
            next_timestamp_utc = _serialize_datetime(next_doc.get("timestamp"))
            if ranking and next_number in ranking:
                hit_rank = ranking.index(next_number) + 1
                plot_rank = hit_rank
                hit = True
            else:
                plot_rank = 38
        else:
            unresolved_count += 1

        items_desc.append(
            {
                "snapshot_id": str(snapshot_doc.get("snapshot_id") or snapshot_doc.get("_id") or ""),
                "anchor_history_id": anchor_history_id,
                "anchor_number": anchor_number,
                "anchor_timestamp_utc": _serialize_datetime(snapshot_doc.get("anchor_timestamp_utc")),
                "next_history_id": next_history_id,
                "next_number": next_number,
                "next_timestamp_utc": next_timestamp_utc,
                "hit_rank": hit_rank,
                "plot_rank": plot_rank,
                "hit": hit,
                "ranking_full": list(ranking),
                "ranking_top10": list(ranking[:10]),
                "ranking_size": len(ranking),
                "context": _extract_snapshot_timeline_context(snapshot_doc, ranking),
                "config_key": str(snapshot_doc.get("config_key") or ""),
                "source": str(snapshot_doc.get("source") or ""),
            }
        )
        if len(items_desc) >= safe_limit:
            break

    items = list(reversed(items_desc))
    resolved_items = [item for item in items if item.get("next_number") is not None]
    hit_items = [item for item in resolved_items if item.get("hit_rank") is not None]
    misses_count = len([item for item in resolved_items if item.get("hit_rank") is None])

    rank_distribution = {str(rank): 0 for rank in range(1, 38)}
    for item in hit_items:
        rank_distribution[str(int(item["hit_rank"]))] += 1

    summary = {
        "current_config_key": current_config_key,
        "using_current_config_only": not include_all_configs,
        "requested_limit": safe_limit,
        "returned_items": len(items),
        "resolved_items": len(resolved_items),
        "unresolved_items": unresolved_count,
        "missing_history_items": missing_history_count,
        "hits_in_ranking": len(hit_items),
        "outside_ranking": misses_count,
        "hit_rate_percent": round((len(hit_items) / len(resolved_items) * 100.0), 2) if resolved_items else 0.0,
        "top_1_hits": rank_distribution["1"],
        "top_3_hits": sum(rank_distribution[str(rank)] for rank in range(1, 4)),
        "top_5_hits": sum(rank_distribution[str(rank)] for rank in range(1, 6)),
        "top_10_hits": sum(rank_distribution[str(rank)] for rank in range(1, 11)),
        "avg_hit_rank": round(sum(int(item["hit_rank"]) for item in hit_items) / len(hit_items), 2) if hit_items else None,
        "rank_distribution": rank_distribution,
    }
    summary["strategy"] = _apply_inversion_strategy(items)
    summary["range_prediction"] = _apply_movement_range_prediction(items)

    return {
        "available": True,
        "roulette_id": roulette_id,
        "summary": summary,
        "items": items,
    }


async def resolve_latest_suggestion_snapshot(
    *,
    roulette_id: str,
    take: int,
    source: str = "api_latest",
    create_if_missing: bool = True,
) -> Dict[str, Any]:
    return await resolve_suggestion_snapshot_by_index(
        roulette_id=roulette_id,
        from_index=0,
        take=take,
        source=source,
        create_if_missing=create_if_missing,
    )


async def resolve_suggestion_snapshot_by_history_id(
    *,
    roulette_id: str,
    history_id: str,
    take: int,
    source: str = "api_on_demand",
    create_if_missing: bool = True,
) -> Dict[str, Any]:
    config_doc = await get_or_create_global_suggestion_snapshot_config()
    anchor_doc = await _load_history_doc_by_id(roulette_id, history_id)
    if not isinstance(anchor_doc, Mapping):
        raise LookupError("Resultado histórico não encontrado para a roleta informada.")

    anchor_history_id = str(anchor_doc.get("_id"))
    config_key = build_suggestion_snapshot_config_key(config_doc)
    snapshot_doc = await suggestion_snapshots_coll.find_one(
        {
            "roulette_id": roulette_id,
            "anchor_history_id": anchor_history_id,
            "config_key": config_key,
        }
    )
    cache_status = "hit"
    if not isinstance(snapshot_doc, Mapping):
        if not create_if_missing:
            raise LookupError("Não foi gerada a sugestão para esse número.")
        docs = await _load_history_docs_for_anchor(
            roulette_id,
            from_index=0,
            history_limit=int(config_doc.get("history_limit") or 2000),
        )
        anchor_index = next(
            (idx for idx, doc in enumerate(docs) if str(doc.get("_id")) == anchor_history_id),
            None,
        )
        if anchor_index is None:
            raise LookupError("Resultado histórico não encontrado para montar a sugestão.")
        history_at_anchor = [
            int(doc.get("value"))
            for doc in docs[anchor_index : anchor_index + int(config_doc.get("history_limit") or 2000)]
            if 0 <= int(doc.get("value")) <= 36
        ]
        snapshot_doc = await _compute_and_persist_snapshot(
            roulette_id=roulette_id,
            anchor_doc=anchor_doc,
            history_at_anchor=history_at_anchor,
            config_doc=config_doc,
            source=source,
        )
        cache_status = "created"

    response = _serialize_snapshot_response(snapshot_doc, take=take)
    response["snapshot"]["cache_status"] = cache_status
    return response
