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
    sliced_payload = slice_snapshot_payload(snapshot_doc.get("payload") or {}, take=take)
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
