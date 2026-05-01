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
