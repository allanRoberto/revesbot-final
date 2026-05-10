from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping
from bson import ObjectId

from api.core.db import (
    history_coll,
    suggestion_snapshot_configs_coll,
    suggestion_snapshots_coll,
)
from api.routes.patterns import FinalSuggestionRequest, _compute_final_suggestion
from api.services.pattern_score_live_service import (
    load_pattern_score_weight_profile,
    merge_pattern_score_weights,
    resolve_previous_snapshot_pattern_scores,
)

logger = logging.getLogger(__name__)


GLOBAL_SUGGESTION_SNAPSHOT_CONFIG_ID = "global-default"
SUGGESTION_SNAPSHOT_RANKING_SIZE = 37


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)) or default)
    except Exception:
        value = int(default)
    return max(int(minimum), min(int(maximum), int(value)))


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)) or default)
    except Exception:
        value = float(default)
    return max(float(minimum), min(float(maximum), float(value)))


SNAPSHOT_TIMING_LOG_THRESHOLD_SECONDS = _env_float(
    "SUGGESTION_SNAPSHOT_TIMING_LOG_THRESHOLD_SECONDS",
    1.0,
    0.0,
    60.0,
)

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
    "pattern_score_weighting_enabled": True,
    "pattern_score_min_activations": 5,
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


async def _build_live_strategy_data_for_snapshot(
    *,
    roulette_id: str,
    snapshot_id: str,
    anchor_doc: Mapping[str, Any],
    config_key: str,
    ranking: List[int],
) -> Dict[str, Any]:
    safe_ranking = _coerce_number_ranking(ranking)
    if not safe_ranking:
        return {}

    snapshot_query: Dict[str, Any] = {
        "roulette_id": roulette_id,
        "config_key": config_key,
    }
    anchor_timestamp = anchor_doc.get("timestamp")
    if anchor_timestamp is not None:
        snapshot_query["anchor_timestamp_utc"] = {"$lt": anchor_timestamp}

    snapshot_projection = {
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
        "payload.simple_payload.ordered_suggestion": 1,
        "payload.simple_payload.suggestion": 1,
        "payload.simple_payload.list": 1,
    }
    previous_docs_raw = await (
        suggestion_snapshots_coll.find(snapshot_query, projection=snapshot_projection)
        .sort("anchor_timestamp_utc", -1)
        .limit(STRATEGY_LIVE_LOOKBACK_SNAPSHOTS)
        .to_list(length=STRATEGY_LIVE_LOOKBACK_SNAPSHOTS)
    )
    previous_docs = [dict(doc) for doc in previous_docs_raw if isinstance(doc, Mapping)]

    history_fetch_limit = min(
        max((len(previous_docs) + 1) * 6, 300),
        5000,
    )
    history_docs_raw = await (
        history_coll.find({"roulette_id": roulette_id}, projection={"_id": 1, "value": 1, "timestamp": 1})
        .sort("timestamp", -1)
        .limit(history_fetch_limit)
        .to_list(length=history_fetch_limit)
    )
    history_docs = [dict(doc) for doc in history_docs_raw if isinstance(doc, Mapping)]
    history_index = {str(doc.get("_id")): idx for idx, doc in enumerate(history_docs)}

    items_desc: List[Dict[str, Any]] = []
    for snapshot_doc in previous_docs:
        anchor_history_id = str(snapshot_doc.get("anchor_history_id") or "").strip()
        anchor_idx = history_index.get(anchor_history_id)
        if anchor_idx is None:
            continue

        previous_ranking = _extract_snapshot_ranking(snapshot_doc)
        if not previous_ranking:
            continue

        next_doc = history_docs[anchor_idx - 1] if anchor_idx > 0 else None
        next_number = None
        hit_rank = None
        plot_rank = None
        if isinstance(next_doc, Mapping):
            next_number = int(next_doc.get("value"))
            if next_number in previous_ranking:
                hit_rank = previous_ranking.index(next_number) + 1
                plot_rank = hit_rank
            else:
                plot_rank = STRATEGY_OUTSIDE_RANK

        items_desc.append(
            {
                "snapshot_id": str(snapshot_doc.get("snapshot_id") or snapshot_doc.get("_id") or ""),
                "anchor_history_id": anchor_history_id,
                "anchor_number": int(v) if (v := snapshot_doc.get("anchor_number")) is not None else -1,
                "anchor_timestamp_utc": _serialize_datetime(snapshot_doc.get("anchor_timestamp_utc")),
                "next_number": next_number,
                "hit_rank": hit_rank,
                "plot_rank": plot_rank,
                "hit": hit_rank is not None,
                "ranking_full": list(previous_ranking),
                "ranking_size": len(previous_ranking),
                "config_key": str(snapshot_doc.get("config_key") or ""),
                "source": str(snapshot_doc.get("source") or ""),
            }
        )

    current_item = {
        "snapshot_id": snapshot_id,
        "anchor_history_id": str(anchor_doc.get("_id") or ""),
        "anchor_number": int(anchor_doc.get("value")),
        "anchor_timestamp_utc": _serialize_datetime(anchor_doc.get("timestamp")),
        "next_number": None,
        "hit_rank": None,
        "plot_rank": None,
        "hit": False,
        "ranking_full": list(safe_ranking),
        "ranking_size": len(safe_ranking),
        "config_key": config_key,
        "source": "snapshot_creation",
    }
    items = list(reversed(items_desc)) + [current_item]
    _apply_inversion_strategy(items)
    for item in items:
        item["ranking_otimizado_replay"] = list(item.get("ranking_otimizado") or [])
        _snapshot_strategy_fields(item, prefix="strategy_replay")
    _apply_live_inversion_strategy(items)
    current = items[-1]
    persisted = _build_strategy_data_for_persistence(current)
    persisted["lookback_snapshots"] = len(previous_docs)
    persisted["history_fetch_limit"] = history_fetch_limit
    return persisted


def _schedule_previous_pattern_score_resolution(
    *,
    roulette_id: str,
    anchor_doc: Mapping[str, Any],
    config_key: str,
) -> Dict[str, Any]:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return {"available": False, "mode": "not_scheduled", "reason": "no_running_loop"}

    task = loop.create_task(
        resolve_previous_snapshot_pattern_scores(
            roulette_id=roulette_id,
            current_anchor_doc=anchor_doc,
            config_key=config_key,
        )
    )

    def _log_result(done: asyncio.Task[Dict[str, Any]]) -> None:
        try:
            result = done.result()
        except asyncio.CancelledError:
            logger.debug("Pattern score background resolution cancelled | roulette=%s", roulette_id)
            return
        except Exception as exc:
            logger.warning(
                "Pattern score background resolution failed | roulette=%s | error=%s",
                roulette_id,
                exc,
            )
            return
        if result.get("inserted"):
            logger.info(
                "Pattern score background resolved | roulette=%s | snapshot=%s | inserted=%s | skipped=%s",
                roulette_id,
                result.get("resolved_snapshot_id"),
                result.get("inserted"),
                result.get("skipped_existing"),
            )

    task.add_done_callback(_log_result)
    return {"available": None, "mode": "background_scheduled"}


async def _compute_and_persist_snapshot(
    *,
    roulette_id: str,
    anchor_doc: Mapping[str, Any],
    history_at_anchor: List[int],
    config_doc: Mapping[str, Any],
    source: str,
) -> Dict[str, Any]:
    started_at = time.perf_counter()
    last_stage_at = started_at
    stage_timings: Dict[str, float] = {}

    def mark_stage(name: str) -> None:
        nonlocal last_stage_at
        now = time.perf_counter()
        stage_timings[name] = round(now - last_stage_at, 4)
        last_stage_at = now

    anchor_history_id = str(anchor_doc.get("_id"))
    anchor_number = int(anchor_doc.get("value"))
    config_key = build_suggestion_snapshot_config_key(config_doc)
    snapshot_id = build_suggestion_snapshot_id(
        roulette_id=roulette_id,
        anchor_history_id=anchor_history_id,
        config_key=config_key,
    )

    normalized_config = _normalize_config_document(config_doc)
    pattern_score_meta: Dict[str, Any] = {
        "enabled": bool(normalized_config.get("pattern_score_weighting_enabled", True)),
        "applied": False,
        "weight_count": 0,
        "min_activations": int(normalized_config.get("pattern_score_min_activations") or 5),
        "previous_resolution": {},
    }
    request_config_doc: Mapping[str, Any] = config_doc
    if pattern_score_meta["enabled"]:
        try:
            pattern_score_meta["previous_resolution"] = _schedule_previous_pattern_score_resolution(
                roulette_id=roulette_id,
                anchor_doc=anchor_doc,
                config_key=config_key,
            )
        except Exception as exc:
            pattern_score_meta["previous_resolution"] = {"available": False, "error": str(exc)}
        mark_stage("pattern_score_schedule")
        try:
            score_profile = await load_pattern_score_weight_profile(
                roulette_id=roulette_id,
                min_activations=int(pattern_score_meta["min_activations"]),
            )
            dynamic_weights = dict(score_profile.get("weights") or {})
            if dynamic_weights:
                request_config = copy.deepcopy(dict(config_doc))
                request_config["weight_profile_weights"] = merge_pattern_score_weights(
                    config_doc.get("weight_profile_weights") if isinstance(config_doc, Mapping) else {},
                    dynamic_weights,
                )
                request_config_doc = request_config
                pattern_score_meta.update(
                    {
                        "applied": True,
                        "weight_count": int(score_profile.get("weight_count") or len(dynamic_weights)),
                        "cache": str(score_profile.get("cache") or ""),
                        "top_positive": list(score_profile.get("top_positive") or [])[:12],
                        "top_negative": list(score_profile.get("top_negative") or [])[:12],
                    }
                )
        except Exception as exc:
            pattern_score_meta["load_error"] = str(exc)
        mark_stage("pattern_score_weights")

    request = build_suggestion_snapshot_request(
        history=history_at_anchor,
        focus_number=anchor_number,
        config_doc=request_config_doc,
    )
    payload = await _compute_final_suggestion(request)
    mark_stage("final_suggestion")
    if isinstance(payload, dict):
        payload["pattern_score_weighting"] = pattern_score_meta
    base_ranking = _extract_payload_ranking(payload if isinstance(payload, Mapping) else {})
    try:
        strategy_data = await _build_live_strategy_data_for_snapshot(
            roulette_id=roulette_id,
            snapshot_id=snapshot_id,
            anchor_doc=anchor_doc,
            config_key=config_key,
            ranking=base_ranking,
        )
    except Exception as exc:
        print(f"⚠️  Falha ao calcular ranking otimizado live do snapshot: {exc}")
        strategy_data = {}
    mark_stage("live_strategy")
    now = datetime.now(timezone.utc)
    total_elapsed = round(time.perf_counter() - started_at, 4)
    timing_data = {
        "total_seconds": total_elapsed,
        "stages": dict(stage_timings),
        "target_seconds": 3.0,
        "within_target": total_elapsed <= 3.0,
    }
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
        "strategy_data": _mongo_safe_value(strategy_data),
        "pattern_score_weighting": _mongo_safe_value(pattern_score_meta),
        "timing": timing_data,
        "source": source,
        "created_at_utc": now,
        "updated_at_utc": now,
    }
    await suggestion_snapshots_coll.update_one(
        {"_id": snapshot_id},
        {"$setOnInsert": document},
        upsert=True,
    )
    mark_stage("mongo_upsert")
    total_elapsed = round(time.perf_counter() - started_at, 4)
    timing_data["total_seconds"] = total_elapsed
    timing_data["stages"] = dict(stage_timings)
    timing_data["within_target"] = total_elapsed <= 3.0
    if total_elapsed >= SNAPSHOT_TIMING_LOG_THRESHOLD_SECONDS:
        logger.info(
            "suggestion snapshot timing | roulette=%s | anchor=%s | total=%.3fs | target=3.000s | stages=%s",
            roulette_id,
            anchor_number,
            total_elapsed,
            " | ".join(f"{name}={elapsed:.3f}s" for name, elapsed in stage_timings.items()),
        )
    return document


def _serialize_snapshot_response(snapshot_doc: Mapping[str, Any], *, take: int) -> Dict[str, Any]:
    sliced_payload = build_frontend_snapshot_payload(snapshot_doc.get("payload") or {}, take=take)
    return {
        "available": bool(sliced_payload.get("available", False)),
        "result": sliced_payload,
        "snapshot": {
            "snapshot_id": str(snapshot_doc.get("snapshot_id") or snapshot_doc.get("_id") or ""),
            "roulette_id": str(snapshot_doc.get("roulette_id") or ""),
            "anchor_history_id": str(snapshot_doc.get("anchor_history_id") or ""),
            "anchor_number": int(v) if (v := snapshot_doc.get("anchor_number")) is not None else -1,
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


def _coerce_number_ranking(values: Any) -> List[int]:
    if not isinstance(values, list):
        return []
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
    return ranking


def _extract_payload_ranking(payload: Mapping[str, Any]) -> List[int]:
    for key in ("suggestion", "list", "ordered_suggestion", "base_suggestion", "simple_suggestion"):
        ranking = _coerce_number_ranking(payload.get(key))
        if ranking:
            return ranking
    return []


def _extract_snapshot_ranking(snapshot_doc: Mapping[str, Any]) -> List[int]:
    payload = snapshot_doc.get("payload") if isinstance(snapshot_doc, Mapping) else None
    if not isinstance(payload, Mapping):
        return []
    return _extract_payload_ranking(payload)


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
ZIGZAG_DEFAULT_TOP_END = 7
ZIGZAG_DEFAULT_BOTTOM_START = 29
ZIGZAG_MIN_SAMPLE = 8
ZIGZAG_RUNS_TEST_Z_THRESHOLD = 1.96
STRATEGY_MIN_CORRECTION = 4
STRATEGY_SMALL_EDGE_SIZE = 5
STRATEGY_MEDIUM_EDGE_SIZE = 8
STRATEGY_LARGE_EDGE_SIZE = 10
STRATEGY_DEPTH_OPTIONS = (
    STRATEGY_SMALL_EDGE_SIZE,
    STRATEGY_MEDIUM_EDGE_SIZE,
    STRATEGY_LARGE_EDGE_SIZE,
)
STRATEGY_SCORE_THRESHOLD_SMALL = 4.0
STRATEGY_SCORE_THRESHOLD_MEDIUM = 6.0
STRATEGY_SCORE_THRESHOLD_LARGE = 9.0
STRATEGY_SCORE_DECAY_PER_STEP = 0.35
STRATEGY_SCORE_MAX = 18.0
STRATEGY_TREND_WINDOW = 5
STRATEGY_EARLY_ACTIVATION_MARGIN = 1.5
STRATEGY_VOLATILITY_AMPLIFY_THRESHOLD = 0.65
STRATEGY_INVERSION_CONFIDENCE_TOLERANCE = 5
STRATEGY_INVERSION_CONFIDENCE_NEUTRAL = 0.5
STRATEGY_INVERSION_CONFIDENCE_MIN = 0.3
STRATEGY_FEEDBACK_MIN_SAMPLES = 3
STRATEGY_FEEDBACK_HIGH_RATE = 0.6
STRATEGY_FEEDBACK_LOW_RATE = 0.35
STRATEGY_FEEDBACK_THRESHOLD_ADJUST = 0.8
STRATEGY_FEEDBACK_THRESHOLD_FLOOR = 1.0
STRATEGY_ZONE_TOP_END = 12
STRATEGY_ZONE_BOTTOM_START = 25
STRATEGY_GRAPH_GATE_WINDOW = 14
STRATEGY_GRAPH_GATE_MIN_SAMPLES = 8
STRATEGY_GRAPH_GATE_MIN_AMPLITUDE = 6.0
STRATEGY_GRAPH_GATE_MIN_AVG_RANK_GAIN = 1.0
STRATEGY_GRAPH_GATE_MIN_TAIL_RANK_GAIN = 0.5
STRATEGY_GRAPH_GATE_MIN_WORSENING_SLOPE = 0.25
STRATEGY_SCORE_DEACTIVATION_SMALL = 2.5
STRATEGY_SCORE_DEACTIVATION_MEDIUM = 4.0
STRATEGY_SCORE_DEACTIVATION_LARGE = 7.0
STRATEGY_PERSISTENCE_TURNS = 3
STRATEGY_LIVE_LOOKBACK_SNAPSHOTS = _env_int(
    "SUGGESTION_SNAPSHOT_STRATEGY_LOOKBACK",
    120,
    60,
    300,
)
STRATEGY_LEGACY_ZONE_ORDER = (
    36, 37, 35, 34, 33, 32, 31, 30, 29, 28, 27, 26,
    13, 25, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23,
    12, 24, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1,
)
STRATEGY_LEGACY_ZONE_RANKS = {
    original_rank: optimized_rank
    for optimized_rank, original_rank in enumerate(STRATEGY_LEGACY_ZONE_ORDER, start=1)
}
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


def _rank_zone(rank: int | None, depth: int | None = None) -> str:
    if not isinstance(rank, int):
        return "none"
    safe_rank = int(rank)
    if not (1 <= safe_rank <= 37):
        return "none"
    if safe_rank <= STRATEGY_ZONE_TOP_END:
        return "top"
    if safe_rank >= STRATEGY_ZONE_BOTTOM_START:
        return "bottom"
    return "middle"


def _invert_rank_zones(rank: int | None, depth: int) -> int | None:
    """
    Inverte pela faixa ampla do MANÁ, mas com uma permutação 1:1.

    A versão antiga usava zonas fixas 1-12 e 25-37 e produzia empates no
    rank otimizado. Esta ordem preserva o mesmo ranking final estável, sem
    colisões entre ranks originais.
    """
    if rank is None:
        return None
    safe_rank = int(rank)
    if not (1 <= safe_rank <= 37):
        return safe_rank
    if int(depth or 0) <= 0:
        return safe_rank

    return STRATEGY_LEGACY_ZONE_RANKS.get(safe_rank, safe_rank)


def _build_optimized_ranking(ranking: List[int], depth: int) -> List[int]:
    """
    Reconstrói o ranking aplicando a inversão por zonas.
    Cada número recebe uma posição otimizada via _invert_rank_zones,
    depois ordena pelo rank otimizado.
    """
    if not ranking or depth == 0:
        return list(ranking)
    ranked = []
    for idx, num in enumerate(ranking):
        original_rank = idx + 1
        optimized_rank = _invert_rank_zones(original_rank, depth)
        ranked.append((num, optimized_rank if optimized_rank is not None else original_rank, original_rank))
    ranked.sort(key=lambda x: (x[1], x[2]))
    return [num for num, _, _ in ranked]


def _resolve_inversion_depth(regime_score: float) -> int:
    safe_score = float(regime_score or 0.0)
    if safe_score >= STRATEGY_SCORE_THRESHOLD_LARGE:
        return STRATEGY_LARGE_EDGE_SIZE
    if safe_score >= STRATEGY_SCORE_THRESHOLD_MEDIUM:
        return STRATEGY_MEDIUM_EDGE_SIZE
    if safe_score >= STRATEGY_SCORE_THRESHOLD_SMALL:
        return STRATEGY_SMALL_EDGE_SIZE
    return 0


def _resolve_inversion_depth_with_hysteresis(
    regime_score: float,
    currently_active: bool,
) -> int:
    """
    Como _resolve_inversion_depth, mas com hysteresis: quando já está ativo,
    usa thresholds de desativação mais baixos para evitar ligar/desligar rápido.
    """
    safe_score = float(regime_score or 0.0)

    # Thresholds normais de ativação (igual ao original)
    if safe_score >= STRATEGY_SCORE_THRESHOLD_LARGE:
        return STRATEGY_LARGE_EDGE_SIZE
    if safe_score >= STRATEGY_SCORE_THRESHOLD_MEDIUM:
        return STRATEGY_MEDIUM_EDGE_SIZE
    if safe_score >= STRATEGY_SCORE_THRESHOLD_SMALL:
        return STRATEGY_SMALL_EDGE_SIZE

    # Zona de hysteresis: já ativo → usar thresholds de desativação mais baixos
    if currently_active:
        if safe_score >= STRATEGY_SCORE_DEACTIVATION_LARGE:
            return STRATEGY_LARGE_EDGE_SIZE
        if safe_score >= STRATEGY_SCORE_DEACTIVATION_MEDIUM:
            return STRATEGY_MEDIUM_EDGE_SIZE
        if safe_score >= STRATEGY_SCORE_DEACTIVATION_SMALL:
            return STRATEGY_SMALL_EDGE_SIZE

    return 0


def _detect_trend_state(recent_ranks: List[int]) -> str:
    if len(recent_ranks) < 3:
        return "unknown"
    n = len(recent_ranks)
    increasing = sum(1 for i in range(1, n) if recent_ranks[i] > recent_ranks[i - 1])
    ratio = increasing / (n - 1)
    if ratio >= 0.7:
        return "rising"
    if ratio <= 0.3:
        return "falling"
    return "stable"


def _calculate_volatility_score(recent_ranks: List[int]) -> float:
    if len(recent_ranks) < 3:
        return 0.5
    mean = sum(recent_ranks) / len(recent_ranks)
    variance = sum((r - mean) ** 2 for r in recent_ranks) / len(recent_ranks)
    std_dev = variance ** 0.5
    return min(1.0, std_dev / 15.0)


def _calculate_dynamic_depth(
    regime_score: float,
    current_rank: int | None,
    trend_state: str,
    volatility: float,
    inversion_confidence: float = STRATEGY_INVERSION_CONFIDENCE_NEUTRAL,
    tracker: "_InversionDepthTracker | None" = None,
    currently_active: bool = False,
) -> int:
    threshold_small = STRATEGY_SCORE_THRESHOLD_SMALL
    if tracker is not None:
        threshold_small = tracker.adjusted_threshold(threshold_small, STRATEGY_SMALL_EDGE_SIZE)

    base = _resolve_inversion_depth_with_hysteresis(regime_score, currently_active)
    if base == 0:
        if trend_state == "rising" and regime_score >= (threshold_small - STRATEGY_EARLY_ACTIVATION_MARGIN):
            base = STRATEGY_SMALL_EDGE_SIZE
    if base == 0:
        return 0

    if inversion_confidence < STRATEGY_INVERSION_CONFIDENCE_MIN:
        return 0

    if volatility > STRATEGY_VOLATILITY_AMPLIFY_THRESHOLD and trend_state == "rising":
        base = min(STRATEGY_LARGE_EDGE_SIZE, base + 2)

    if isinstance(current_rank, int):
        if current_rank <= 2 or current_rank >= 36:
            base = min(base, 3)

    return base


def _validate_inversion_confidence(
    original_rank: int,
    inverted_rank: int,
    history: List[int],
) -> float:
    if len(history) < 5 or not isinstance(original_rank, int) or not isinstance(inverted_rank, int):
        return STRATEGY_INVERSION_CONFIDENCE_NEUTRAL

    matches = 0
    successes = 0
    for i in range(len(history) - 1):
        if abs(history[i] - original_rank) <= STRATEGY_INVERSION_CONFIDENCE_TOLERANCE:
            matches += 1
            if abs(history[i + 1] - inverted_rank) <= STRATEGY_INVERSION_CONFIDENCE_TOLERANCE:
                successes += 1

    if matches == 0:
        return STRATEGY_INVERSION_CONFIDENCE_NEUTRAL
    return round(successes / matches, 3)


def _calculate_graph_slope(values: List[int]) -> float:
    if len(values) < 2:
        return 0.0
    n = len(values)
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    denominator = sum((idx - x_mean) ** 2 for idx in range(n))
    if denominator <= 0:
        return 0.0
    numerator = sum((idx - x_mean) * (value - y_mean) for idx, value in enumerate(values))
    return numerator / denominator


def _evaluate_inversion_gate(
    graph_ranks: List[int],
    *,
    depth: int,
    zigzag_gate: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    safe_depth = int(depth or 0)
    if safe_depth <= 0:
        return {
            "allowed": False,
            "reason": "depth_zero",
            "depth": safe_depth,
        }

    safe_window = max(
        STRATEGY_GRAPH_GATE_MIN_SAMPLES,
        min(60, int(STRATEGY_GRAPH_GATE_WINDOW)),
    )
    ranks = [
        int(rank)
        for rank in graph_ranks[-safe_window:]
        if isinstance(rank, int) and 1 <= int(rank) <= STRATEGY_OUTSIDE_RANK
    ]
    if len(ranks) < STRATEGY_GRAPH_GATE_MIN_SAMPLES:
        return {
            "allowed": False,
            "reason": "insufficient_graph_samples",
            "depth": safe_depth,
            "sample_size": len(ranks),
            "min_samples": STRATEGY_GRAPH_GATE_MIN_SAMPLES,
        }

    transformed = [
        int(_invert_rank_zones(rank, safe_depth) or rank)
        for rank in ranks
    ]
    sample_size = len(ranks)
    mean_rank = sum(ranks) / sample_size
    variance = sum((rank - mean_rank) ** 2 for rank in ranks) / sample_size
    std_rank = variance ** 0.5
    min_rank = min(ranks)
    max_rank = max(ranks)
    amplitude = max_rank - min_rank
    band_offset = max(2.0, std_rank * 0.35)
    lower_band = mean_rank - band_offset
    upper_band = mean_rank + band_offset
    last_rank = ranks[-1]
    previous_rank = ranks[-2] if sample_size >= 2 else last_rank
    last_delta = last_rank - previous_rank
    recent_delta = last_rank - ranks[max(0, sample_size - 4)]
    slope = _calculate_graph_slope(ranks)
    tail_size = min(4, sample_size)
    tail_ranks = ranks[-tail_size:]
    tail_transformed = transformed[-tail_size:]
    improved = sum(1 for rank, inverted_rank in zip(ranks, transformed) if inverted_rank < rank)
    harmed = sum(1 for rank, inverted_rank in zip(ranks, transformed) if inverted_rank > rank)
    avg_rank_gain = sum(rank - inverted_rank for rank, inverted_rank in zip(ranks, transformed)) / sample_size
    tail_avg_rank_gain = (
        sum(rank - inverted_rank for rank, inverted_rank in zip(tail_ranks, tail_transformed)) / tail_size
        if tail_size
        else 0.0
    )
    improve_rate = improved / sample_size
    harm_rate = harmed / sample_size
    graph_is_worsening = (
        slope >= STRATEGY_GRAPH_GATE_MIN_WORSENING_SLOPE
        or recent_delta >= 4
        or last_delta >= 3
    )
    graph_at_upper_band = last_rank >= upper_band
    graph_is_recovering = slope <= -STRATEGY_GRAPH_GATE_MIN_WORSENING_SLOPE and last_delta <= 0
    gate = dict(zigzag_gate or {})
    zigzag_action = str(gate.get("action") or "neutral")
    zigzag_invert = bool(gate.get("active")) and zigzag_action == "invert"
    zigzag_keep_normal = bool(gate.get("active")) and zigzag_action == "keep_normal"

    result = {
        "allowed": False,
        "reason": "",
        "depth": safe_depth,
        "sample_size": sample_size,
        "window": safe_window,
        "last_rank": last_rank,
        "previous_rank": previous_rank,
        "last_delta": round(float(last_delta), 4),
        "recent_delta": round(float(recent_delta), 4),
        "slope": round(float(slope), 4),
        "mean_rank": round(mean_rank, 4),
        "std_rank": round(std_rank, 4),
        "min_rank": int(min_rank),
        "max_rank": int(max_rank),
        "amplitude": round(float(amplitude), 4),
        "lower_band": round(lower_band, 4),
        "upper_band": round(upper_band, 4),
        "graph_is_worsening": bool(graph_is_worsening),
        "graph_at_upper_band": bool(graph_at_upper_band),
        "graph_is_recovering": bool(graph_is_recovering),
        "avg_rank_gain": round(avg_rank_gain, 4),
        "tail_avg_rank_gain": round(tail_avg_rank_gain, 4),
        "improve_rate": round(improve_rate, 4),
        "harm_rate": round(harm_rate, 4),
        "zigzag_active": bool(gate.get("active")),
        "zigzag_action": zigzag_action,
    }

    if amplitude < STRATEGY_GRAPH_GATE_MIN_AMPLITUDE:
        result["reason"] = "graph_flat"
        return result

    if graph_is_recovering and last_rank <= mean_rank:
        result["reason"] = "graph_recovery_protected"
        return result

    if last_rank <= lower_band and not zigzag_invert:
        result["reason"] = "graph_strength_protected"
        return result

    if zigzag_keep_normal and avg_rank_gain < (STRATEGY_GRAPH_GATE_MIN_AVG_RANK_GAIN * 2):
        result["reason"] = "graph_zigzag_keep_normal"
        return result

    if not (graph_at_upper_band or graph_is_worsening or zigzag_invert):
        result["reason"] = "graph_no_reversal_setup"
        return result

    if avg_rank_gain < STRATEGY_GRAPH_GATE_MIN_AVG_RANK_GAIN:
        result["reason"] = "graph_projection_not_positive"
        return result

    if tail_avg_rank_gain < STRATEGY_GRAPH_GATE_MIN_TAIL_RANK_GAIN:
        result["reason"] = "graph_tail_projection_weak"
        return result

    if harm_rate > improve_rate and avg_rank_gain < (STRATEGY_GRAPH_GATE_MIN_AVG_RANK_GAIN * 2):
        result["reason"] = "graph_harm_rate_too_high"
        return result

    result["allowed"] = True
    if zigzag_invert:
        result["reason"] = "graph_zigzag_reversal"
    elif graph_at_upper_band:
        result["reason"] = "graph_upper_band_reversal"
    else:
        result["reason"] = "graph_worsening_reversal"
    return result


class _InversionDepthTracker:
    def __init__(self) -> None:
        self._stats: Dict[int, Dict[str, int]] = {
            d: {"hits": 0, "total": 0}
            for d in [STRATEGY_SMALL_EDGE_SIZE, STRATEGY_MEDIUM_EDGE_SIZE, STRATEGY_LARGE_EDGE_SIZE]
        }

    def record(self, depth: int, original_rank: int | None, strategy_rank: int | None) -> None:
        if depth not in self._stats or not isinstance(original_rank, int):
            return
        self._stats[depth]["total"] += 1
        if isinstance(strategy_rank, int) and strategy_rank < original_rank:
            self._stats[depth]["hits"] += 1

    def success_rate(self, depth: int) -> float:
        s = self._stats.get(depth, {})
        total = s.get("total", 0)
        if total < STRATEGY_FEEDBACK_MIN_SAMPLES:
            return STRATEGY_INVERSION_CONFIDENCE_NEUTRAL
        return round(s.get("hits", 0) / total, 3)

    def adjusted_threshold(self, base_threshold: float, depth: int) -> float:
        rate = self.success_rate(depth)
        if rate > STRATEGY_FEEDBACK_HIGH_RATE:
            return max(base_threshold - STRATEGY_FEEDBACK_THRESHOLD_ADJUST, STRATEGY_FEEDBACK_THRESHOLD_FLOOR)
        if rate < STRATEGY_FEEDBACK_LOW_RATE:
            return base_threshold + STRATEGY_FEEDBACK_THRESHOLD_ADJUST
        return base_threshold

    def to_dict(self) -> Dict[str, Any]:
        return {
            str(d): {
                "hits": s["hits"],
                "total": s["total"],
                "rate": self.success_rate(d),
            }
            for d, s in self._stats.items()
        }


def _update_falling_regime_score(
    *,
    regime_score: float,
    previous_rank: int | None,
    current_rank: int | None,
    improvement_streak: int,
    volatility_bonus: float = 0.0,
) -> tuple[float, int]:
    score = max(0.0, float(regime_score or 0.0) - STRATEGY_SCORE_DECAY_PER_STEP)
    score += volatility_bonus * 0.4
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


def _apply_inversion_strategy(
    items: List[Dict[str, Any]],
    *,
    use_current_hit_guard: bool = True,
) -> Dict[str, Any]:
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
    tracker = _InversionDepthTracker()
    inversion_active: bool = False
    persistence_counter: int = 0
    gate_allowed_items = 0
    gate_block_counts: Dict[str, int] = {}

    for item in items:
        original_hit_rank = item.get("hit_rank")
        raw_plot_rank = item.get("plot_rank")
        current_graph_rank = (
            int(raw_plot_rank)
            if isinstance(raw_plot_rank, int)
            else int(original_hit_rank)
            if isinstance(original_hit_rank, int)
            else None
        )
        recent_window = observed_ranks[-STRATEGY_TREND_WINDOW:]
        trend_state = _detect_trend_state(recent_window)
        volatility = _calculate_volatility_score(recent_window)
        volatility_bonus = volatility * 0.5 if trend_state == "rising" else 0.0

        last_rank = observed_ranks[-1] if observed_ranks else None
        zigzag_gate = _resolve_rolling_zigzag_gate(observed_ranks)
        inverted_rank_preview = (
            _invert_rank_zones(last_rank, STRATEGY_LARGE_EDGE_SIZE)
            if isinstance(last_rank, int)
            else None
        )
        inversion_confidence = _validate_inversion_confidence(
            last_rank, inverted_rank_preview, observed_ranks
        )

        # Atualizar persistência antes de calcular o depth
        if persistence_counter > 0:
            persistence_counter -= 1

        proposed_invert_depth = _calculate_dynamic_depth(
            regime_score,
            last_rank,
            trend_state,
            volatility,
            inversion_confidence=inversion_confidence,
            tracker=tracker,
            currently_active=inversion_active,
        )

        # Aplicar persistência: se estava ativo e counter > 0, manter depth mínimo
        if proposed_invert_depth == 0 and inversion_active and persistence_counter > 0:
            proposed_invert_depth = STRATEGY_SMALL_EDGE_SIZE

        strategy_inversion_gate = _evaluate_inversion_gate(
            observed_ranks,
            depth=proposed_invert_depth or STRATEGY_SMALL_EDGE_SIZE,
            zigzag_gate=zigzag_gate,
        )
        if proposed_invert_depth <= 0:
            if bool(strategy_inversion_gate.get("allowed")):
                proposed_invert_depth = STRATEGY_SMALL_EDGE_SIZE
                strategy_inversion_gate["activation_source"] = "graph_behavior"
            else:
                strategy_inversion_gate["activation_source"] = "graph_probe_blocked"
        else:
            strategy_inversion_gate["activation_source"] = "regime_score"
        # No replay, protege pontos em que o próprio gráfico já estava em força.
        if (
            use_current_hit_guard
            and proposed_invert_depth > 0
            and isinstance(current_graph_rank, int)
            and isinstance(strategy_inversion_gate.get("lower_band"), (int, float))
            and current_graph_rank <= float(strategy_inversion_gate.get("lower_band"))
        ):
            strategy_inversion_gate = {
                **strategy_inversion_gate,
                "allowed": False,
                "reason": "current_graph_strength_protected",
                "current_graph_rank": int(current_graph_rank),
            }

        strategy_invert_depth = (
            proposed_invert_depth
            if proposed_invert_depth > 0 and bool(strategy_inversion_gate.get("allowed"))
            else 0
        )
        if proposed_invert_depth > 0:
            if strategy_invert_depth > 0:
                gate_allowed_items += 1
            else:
                gate_reason = str(strategy_inversion_gate.get("reason") or "blocked")
                gate_block_counts[gate_reason] = gate_block_counts.get(gate_reason, 0) + 1

        # Atualizar estado para próximo item somente depois do gate final.
        if strategy_invert_depth > 0:
            inversion_active = True
            persistence_counter = STRATEGY_PERSISTENCE_TURNS
        elif persistence_counter == 0:
            inversion_active = False

        strategy_mode = "inverted_extremes" if strategy_invert_depth > 0 else "normal"
        strategy_triggered = strategy_invert_depth > 0
        if strategy_triggered:
            trigger_source = (
                "graph_behavior_active"
                if strategy_inversion_gate.get("activation_source") == "graph_behavior"
                else "falling_regime_active"
            )
            strategy_trigger_reason = f"{trigger_source}:{strategy_inversion_gate.get('reason') or 'allowed'}"
        elif proposed_invert_depth > 0:
            strategy_trigger_reason = f"blocked:{strategy_inversion_gate.get('reason') or 'gate'}"
        else:
            strategy_trigger_reason = ""
        strategy_reference_ranks: List[int] = observed_ranks[-3:]
        strategy_signal_strength = round(regime_score, 2)
        strategy_hit_rank = original_hit_rank
        strategy_plot_rank = item.get("plot_rank")

        # Construir o ranking otimizado: reorganiza ranking_full pela estratégia de inversão
        ranking_full = item.get("ranking_full") or []
        optimized_ranking = _build_optimized_ranking(ranking_full, strategy_invert_depth)
        item["ranking_otimizado"] = optimized_ranking

        if strategy_invert_depth > 0:
            depth_key = str(strategy_invert_depth)
            depth_counts[depth_key] = depth_counts.get(depth_key, 0) + 1
            triggered_items += 1
            next_number = item.get("next_number")
            if isinstance(next_number, int) and next_number in optimized_ranking:
                # Posição real do next_number no ranking otimizado — igual ao fluxo do original
                strategy_hit_rank = optimized_ranking.index(next_number) + 1
                strategy_plot_rank = strategy_hit_rank
            elif isinstance(original_hit_rank, int):
                # Sem next_number ainda: usa a transformação matemática como proxy
                strategy_hit_rank = None
                strategy_plot_rank = STRATEGY_OUTSIDE_RANK
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
        item["strategy_trend_state"] = trend_state
        item["strategy_volatility"] = round(volatility, 3)
        item["strategy_inversion_confidence"] = round(inversion_confidence, 3)
        item["strategy_inverted_rank_preview"] = inverted_rank_preview
        item["strategy_zigzag_gate"] = zigzag_gate
        item["strategy_inversion_gate"] = strategy_inversion_gate
        item["strategy_inversion_zone"] = _rank_zone(
            int(current_graph_rank) if isinstance(current_graph_rank, int) else None,
            strategy_invert_depth or STRATEGY_LARGE_EDGE_SIZE,
        )
        item["strategy_persistence_active"] = inversion_active

        tracker.record(strategy_invert_depth, original_hit_rank, strategy_hit_rank)

        if isinstance(strategy_hit_rank, int):
            strategy_distribution[str(int(strategy_hit_rank))] += 1
            strategy_hit_items.append(item)

        previous_rank = observed_ranks[-1] if observed_ranks else None
        regime_score, improvement_streak = _update_falling_regime_score(
            regime_score=regime_score,
            previous_rank=previous_rank,
            current_rank=int(current_graph_rank) if isinstance(current_graph_rank, int) else None,
            improvement_streak=improvement_streak,
            volatility_bonus=volatility_bonus,
        )
        if isinstance(current_graph_rank, int):
            observed_ranks.append(int(current_graph_rank))

    strategy_resolved_items = [item for item in items if item.get("next_number") is not None]
    strategy_outside = len([item for item in strategy_resolved_items if item.get("strategy_hit_rank") is None])

    return {
        "enabled": True,
        "name": "inverted_extremes_movement_v2_graph_gated",
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
        "feedback_by_depth": tracker.to_dict(),
        "inversion_gate": {
            "enabled": True,
            "mode": "graph_behavior",
            "window": STRATEGY_GRAPH_GATE_WINDOW,
            "min_samples": STRATEGY_GRAPH_GATE_MIN_SAMPLES,
            "min_amplitude": STRATEGY_GRAPH_GATE_MIN_AMPLITUDE,
            "min_avg_rank_gain": STRATEGY_GRAPH_GATE_MIN_AVG_RANK_GAIN,
            "min_tail_rank_gain": STRATEGY_GRAPH_GATE_MIN_TAIL_RANK_GAIN,
            "min_worsening_slope": STRATEGY_GRAPH_GATE_MIN_WORSENING_SLOPE,
            "allowed_items": gate_allowed_items,
            "blocked_counts": gate_block_counts,
        },
        "uses_current_hit_guard": bool(use_current_hit_guard),
    }


_STRATEGY_FIELD_NAMES = (
    "strategy_mode",
    "strategy_triggered",
    "strategy_trigger_reason",
    "strategy_reference_ranks",
    "strategy_invert_depth",
    "strategy_signal_strength",
    "strategy_hit_rank",
    "strategy_plot_rank",
    "strategy_trend_state",
    "strategy_volatility",
    "strategy_inversion_confidence",
    "strategy_inverted_rank_preview",
    "strategy_zigzag_gate",
    "strategy_inversion_gate",
    "strategy_inversion_zone",
    "strategy_persistence_active",
)


def _snapshot_strategy_fields(item: Mapping[str, Any], *, prefix: str) -> None:
    for key in _STRATEGY_FIELD_NAMES:
        item_key = f"{prefix}_{key.removeprefix('strategy_')}"
        if isinstance(item, dict):
            item[item_key] = item.get(key)


def _apply_live_inversion_strategy(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    live_items = [dict(item) for item in items]
    summary = _apply_inversion_strategy(live_items, use_current_hit_guard=False)
    summary["name"] = "inverted_extremes_movement_v2_live_graph_gated"
    summary["uses_current_hit_guard"] = False

    for item, live_item in zip(items, live_items):
        item["ranking_otimizado_live"] = list(live_item.get("ranking_otimizado") or [])
        for key in _STRATEGY_FIELD_NAMES:
            live_key = f"strategy_live_{key.removeprefix('strategy_')}"
            item[live_key] = live_item.get(key)

    return summary


MIRROR_DEFAULT_MIDPOINT = 19
ROLLING_ZIGZAG_DEFAULT_WINDOW = 60
ROLLING_ZIGZAG_GATE_ACF_THRESHOLD = -0.15


def _compute_zigzag_metrics_lite(
    series: List[int],
    *,
    top_end: int,
    bottom_start: int,
) -> Dict[str, Any]:
    # Versão enxuta para uso em janela rolante: só ACF lag 1 + runs test z.
    n = len(series)
    out: Dict[str, Any] = {
        "acf_lag_1": None,
        "runs_z": None,
        "interpretation": "insufficient_data",
        "n_top": 0,
        "n_bot": 0,
    }
    if n < ZIGZAG_MIN_SAMPLE:
        return out

    mean = sum(series) / n
    sq_dev_total = sum((x - mean) ** 2 for x in series)
    if sq_dev_total > 0 and n > 1:
        cov = sum((series[t] - mean) * (series[t + 1] - mean) for t in range(n - 1))
        out["acf_lag_1"] = round(cov / sq_dev_total, 4)

    binarized: List[int] = []
    for x in series:
        if x <= top_end:
            binarized.append(1)
        elif x >= bottom_start:
            binarized.append(0)
    n1 = sum(binarized)
    n2 = len(binarized) - n1
    out["n_top"] = n1
    out["n_bot"] = n2
    if n1 >= 2 and n2 >= 2:
        runs = 1
        for i in range(1, len(binarized)):
            if binarized[i] != binarized[i - 1]:
                runs += 1
        total = n1 + n2
        expected = (2 * n1 * n2) / total + 1
        variance = (2 * n1 * n2 * (2 * n1 * n2 - total)) / ((total ** 2) * (total - 1))
        if variance > 0:
            z = (runs - expected) / (variance ** 0.5)
            out["runs_z"] = round(z, 4)
            if z >= ZIGZAG_RUNS_TEST_Z_THRESHOLD:
                out["interpretation"] = "significant_zigzag"
            elif z <= -ZIGZAG_RUNS_TEST_Z_THRESHOLD:
                out["interpretation"] = "significant_clustering"
            else:
                out["interpretation"] = "no_significant_pattern"
    return out


def _resolve_rolling_zigzag_gate(
    previous_ranks: List[int],
    *,
    window: int = ROLLING_ZIGZAG_DEFAULT_WINDOW,
    top_end: int = ZIGZAG_DEFAULT_TOP_END,
    bottom_start: int = ZIGZAG_DEFAULT_BOTTOM_START,
    gate_acf_threshold: float = ROLLING_ZIGZAG_GATE_ACF_THRESHOLD,
) -> Dict[str, Any]:
    safe_window = max(ZIGZAG_MIN_SAMPLE, min(500, int(window or ROLLING_ZIGZAG_DEFAULT_WINDOW)))
    window_series = [
        int(rank)
        for rank in previous_ranks[-safe_window:]
        if isinstance(rank, int)
    ]
    if len(window_series) < ZIGZAG_MIN_SAMPLE:
        return {
            "window_size": len(window_series),
            "active": False,
            "action": "neutral",
            "reason": "insufficient_data",
        }

    metrics = _compute_zigzag_metrics_lite(
        window_series,
        top_end=top_end,
        bottom_start=bottom_start,
    )
    gate_active = (
        metrics["interpretation"] == "significant_zigzag"
        and metrics["acf_lag_1"] is not None
        and metrics["acf_lag_1"] <= gate_acf_threshold
    )
    last_rank = window_series[-1]
    action = "neutral"
    reason = str(metrics["interpretation"])
    if gate_active:
        if last_rank <= top_end:
            action = "invert"
            reason = "zigzag_after_top_expects_bottom"
        elif last_rank >= bottom_start:
            action = "keep_normal"
            reason = "zigzag_after_bottom_expects_top"

    return {
        "window_size": len(window_series),
        "active": bool(gate_active),
        "action": action,
        "reason": reason,
        "acf_lag_1": metrics["acf_lag_1"],
        "runs_z": metrics["runs_z"],
        "last_rank": last_rank,
        "top_end": int(top_end),
        "bottom_start": int(bottom_start),
    }


def _build_rolling_zigzag_diagnostics(
    items: List[Dict[str, Any]],
    *,
    window: int = ROLLING_ZIGZAG_DEFAULT_WINDOW,
    top_end: int = ZIGZAG_DEFAULT_TOP_END,
    bottom_start: int = ZIGZAG_DEFAULT_BOTTOM_START,
    miss_rank: int = STRATEGY_OUTSIDE_RANK,
    gate_acf_threshold: float = ROLLING_ZIGZAG_GATE_ACF_THRESHOLD,
) -> Dict[str, Any]:
    safe_window = max(ZIGZAG_MIN_SAMPLE, min(500, int(window or ROLLING_ZIGZAG_DEFAULT_WINDOW)))
    series_full: List[int] = []
    series_index_for_item: List[int | None] = []
    for item in items:
        if item.get("next_number") is None:
            series_index_for_item.append(None)
            continue
        rank = item.get("hit_rank")
        series_full.append(int(rank) if isinstance(rank, int) else int(miss_rank))
        series_index_for_item.append(len(series_full) - 1)

    interp_counts = {
        "significant_zigzag": 0,
        "significant_clustering": 0,
        "no_significant_pattern": 0,
        "insufficient_data": 0,
    }
    gate_active_count = 0
    evaluated = 0

    for item, series_idx in zip(items, series_index_for_item):
        if series_idx is None:
            item["rolling_zigzag"] = None
            continue
        start = max(0, series_idx - safe_window)
        window_series = series_full[start:series_idx]
        metrics = _compute_zigzag_metrics_lite(
            window_series,
            top_end=top_end,
            bottom_start=bottom_start,
        )
        gate_active = (
            metrics["interpretation"] == "significant_zigzag"
            and metrics["acf_lag_1"] is not None
            and metrics["acf_lag_1"] <= gate_acf_threshold
        )
        item["rolling_zigzag"] = {
            "window_size": len(window_series),
            "acf_lag_1": metrics["acf_lag_1"],
            "runs_z": metrics["runs_z"],
            "interpretation": metrics["interpretation"],
            "gate_active": bool(gate_active),
            "gate_action": _resolve_rolling_zigzag_gate(
                window_series,
                window=safe_window,
                top_end=top_end,
                bottom_start=bottom_start,
                gate_acf_threshold=gate_acf_threshold,
            ).get("action", "neutral"),
        }
        interp_counts[metrics["interpretation"]] += 1
        evaluated += 1
        if gate_active:
            gate_active_count += 1

    return {
        "window": safe_window,
        "gate_acf_threshold": gate_acf_threshold,
        "evaluated_items": evaluated,
        "interpretation_counts": interp_counts,
        "gate_active_items": gate_active_count,
        "gate_active_rate_percent": (
            round(gate_active_count / evaluated * 100.0, 2) if evaluated else 0.0
        ),
    }


def _apply_alternating_mirror_strategy(
    items: List[Dict[str, Any]],
    *,
    midpoint: int = MIRROR_DEFAULT_MIDPOINT,
) -> Dict[str, Any]:
    # Hipótese: depois de um acerto no topo (rank <= midpoint) o próximo aterrissa
    # na parte de baixo do ranking, e vice-versa. Quando esperamos "bot", espelhamos
    # o ranking (rank' = 38 - rank) para que o número sorteado caia em rank baixo do
    # ranking espelhado. Misses reais entram no estado como rank 38 (extremo inferior).
    safe_midpoint = max(2, min(36, int(midpoint or MIRROR_DEFAULT_MIDPOINT)))
    expect_low = True
    mirror_distribution = {str(rank): 0 for rank in range(1, 38)}
    mirror_hit_items: List[Dict[str, Any]] = []
    mirrored_steps = 0
    kept_steps = 0
    resolved_items = 0
    misses = 0

    for item in items:
        original_hit_rank = item.get("hit_rank")
        is_pending = item.get("next_number") is None
        is_mirrored = not expect_low

        if is_pending:
            mirror_hit_rank = None
            mirror_plot_rank = None
        elif isinstance(original_hit_rank, int):
            mirror_hit_rank = (38 - original_hit_rank) if is_mirrored else int(original_hit_rank)
            mirror_plot_rank = mirror_hit_rank
        else:
            mirror_hit_rank = None
            mirror_plot_rank = STRATEGY_OUTSIDE_RANK

        item["mirror_hit_rank"] = mirror_hit_rank
        item["mirror_plot_rank"] = mirror_plot_rank
        item["mirror_mode"] = "mirrored" if is_mirrored else "kept"
        item["mirror_expect_low"] = expect_low

        if is_pending:
            continue

        resolved_items += 1
        if is_mirrored:
            mirrored_steps += 1
        else:
            kept_steps += 1

        if isinstance(mirror_hit_rank, int) and 1 <= mirror_hit_rank <= 37:
            mirror_distribution[str(mirror_hit_rank)] += 1
            mirror_hit_items.append(item)
        else:
            misses += 1

        effective_rank = (
            int(original_hit_rank)
            if isinstance(original_hit_rank, int)
            else STRATEGY_OUTSIDE_RANK
        )
        expect_low = effective_rank > safe_midpoint

    return {
        "enabled": True,
        "name": "alternating_mirror_v1",
        "midpoint": safe_midpoint,
        "mirrored_steps": mirrored_steps,
        "kept_steps": kept_steps,
        "resolved_items": resolved_items,
        "hits_in_ranking": len(mirror_hit_items),
        "outside_ranking": misses,
        "hit_rate_percent": (
            round(len(mirror_hit_items) / resolved_items * 100.0, 2)
            if resolved_items
            else 0.0
        ),
        "top_1_hits": mirror_distribution["1"],
        "top_3_hits": sum(mirror_distribution[str(rank)] for rank in range(1, 4)),
        "top_5_hits": sum(mirror_distribution[str(rank)] for rank in range(1, 6)),
        "top_10_hits": sum(mirror_distribution[str(rank)] for rank in range(1, 11)),
        "avg_hit_rank": (
            round(
                sum(int(item["mirror_hit_rank"]) for item in mirror_hit_items)
                / len(mirror_hit_items),
                2,
            )
            if mirror_hit_items
            else None
        ),
        "rank_distribution": mirror_distribution,
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


def _build_zigzag_diagnostics(
    items: List[Dict[str, Any]],
    *,
    top_end: int = ZIGZAG_DEFAULT_TOP_END,
    bottom_start: int = ZIGZAG_DEFAULT_BOTTOM_START,
    miss_rank: int = STRATEGY_OUTSIDE_RANK,
) -> Dict[str, Any]:
    # Misses are folded into the series at miss_rank (default 38) so the metric
    # stays aligned with what the chart shows for "fora do ranking" events.
    series: List[int] = []
    for item in items:
        if item.get("next_number") is None:
            continue
        rank = item.get("hit_rank")
        series.append(int(rank) if isinstance(rank, int) else int(miss_rank))

    diagnostics: Dict[str, Any] = {
        "available": False,
        "sample_size": len(series),
        "miss_rank_used": miss_rank,
        "zone_top_end": top_end,
        "zone_bottom_start": bottom_start,
        "min_sample": ZIGZAG_MIN_SAMPLE,
        "autocorrelation": {"lag_1": None, "lag_2": None, "lag_3": None},
        "conditional": {
            "p_top_baseline": None,
            "p_top_given_top": None,
            "p_top_given_bot": None,
            "lift_bot_vs_top": None,
            "n_top_prev": 0,
            "n_bot_prev": 0,
        },
        "runs_test": {
            "n_top": 0,
            "n_bot": 0,
            "runs": 0,
            "expected_runs": None,
            "variance": None,
            "z_score": None,
            "interpretation": "insufficient_data",
        },
    }

    n = len(series)
    if n < ZIGZAG_MIN_SAMPLE:
        return diagnostics
    diagnostics["available"] = True

    mean = sum(series) / n
    sq_dev_total = sum((x - mean) ** 2 for x in series)
    if sq_dev_total > 0:
        for lag in (1, 2, 3):
            if n > lag:
                cov = sum(
                    (series[t] - mean) * (series[t + lag] - mean)
                    for t in range(n - lag)
                )
                diagnostics["autocorrelation"][f"lag_{lag}"] = round(cov / sq_dev_total, 4)

    n_top_prev = 0
    n_bot_prev = 0
    n_top_after_top = 0
    n_top_after_bot = 0
    for t in range(n - 1):
        cur = series[t]
        nxt_is_top = series[t + 1] <= top_end
        if cur <= top_end:
            n_top_prev += 1
            if nxt_is_top:
                n_top_after_top += 1
        elif cur >= bottom_start:
            n_bot_prev += 1
            if nxt_is_top:
                n_top_after_bot += 1

    p_top_given_top = round(n_top_after_top / n_top_prev, 4) if n_top_prev else None
    p_top_given_bot = round(n_top_after_bot / n_bot_prev, 4) if n_bot_prev else None
    p_baseline = round(sum(1 for x in series if x <= top_end) / n, 4)
    lift = None
    if (
        p_top_given_top is not None
        and p_top_given_bot is not None
        and p_top_given_top > 0
    ):
        lift = round(p_top_given_bot / p_top_given_top, 4)

    diagnostics["conditional"] = {
        "p_top_baseline": p_baseline,
        "p_top_given_top": p_top_given_top,
        "p_top_given_bot": p_top_given_bot,
        "lift_bot_vs_top": lift,
        "n_top_prev": n_top_prev,
        "n_bot_prev": n_bot_prev,
    }

    binarized: List[int] = []
    for x in series:
        if x <= top_end:
            binarized.append(1)
        elif x >= bottom_start:
            binarized.append(0)

    n1 = sum(binarized)
    n2 = len(binarized) - n1
    runs = 0
    if binarized:
        runs = 1
        for i in range(1, len(binarized)):
            if binarized[i] != binarized[i - 1]:
                runs += 1

    expected_runs: float | None = None
    variance_runs: float | None = None
    z_score: float | None = None
    interpretation = "insufficient_data"
    if n1 >= 2 and n2 >= 2:
        total = n1 + n2
        expected_runs = (2 * n1 * n2) / total + 1
        variance_runs = (
            (2 * n1 * n2 * (2 * n1 * n2 - total)) / ((total ** 2) * (total - 1))
        )
        if variance_runs > 0:
            z_score = (runs - expected_runs) / (variance_runs ** 0.5)
            if z_score >= ZIGZAG_RUNS_TEST_Z_THRESHOLD:
                interpretation = "significant_zigzag"
            elif z_score <= -ZIGZAG_RUNS_TEST_Z_THRESHOLD:
                interpretation = "significant_clustering"
            else:
                interpretation = "no_significant_pattern"

    diagnostics["runs_test"] = {
        "n_top": n1,
        "n_bot": n2,
        "runs": runs,
        "expected_runs": round(expected_runs, 2) if expected_runs is not None else None,
        "variance": round(variance_runs, 4) if variance_runs is not None else None,
        "z_score": round(z_score, 4) if z_score is not None else None,
        "interpretation": interpretation,
    }

    return diagnostics


def _build_strategy_summary_from_items(
    items: List[Dict[str, Any]],
    *,
    name: str = "inverted_extremes_movement_v2",
    triggered_key: str = "strategy_triggered",
    depth_key: str = "strategy_invert_depth",
    hit_rank_key: str = "strategy_hit_rank",
    use_current_hit_guard: bool | None = None,
) -> Dict[str, Any]:
    """Constrói um resumo de estratégia baseado nos dados já carregados dos itens."""
    triggered_items = sum(1 for item in items if item.get(triggered_key, False))
    strategy_hit_items = [item for item in items if item.get(hit_rank_key) is not None]
    hits_in_ranking = len(strategy_hit_items)

    depth_counts = {str(5): 0, str(8): 0, str(10): 0}
    for item in items:
        depth = item.get(depth_key, 0)
        if depth in [5, 8, 10]:
            depth_counts[str(depth)] += 1

    strategy_distribution = {str(rank): 0 for rank in range(1, 38)}
    for item in strategy_hit_items:
        rank = item.get(hit_rank_key)
        if isinstance(rank, int) and 1 <= rank <= 37:
            strategy_distribution[str(rank)] += 1

    resolved_items = [item for item in items if item.get("next_number") is not None]
    hit_rate = (len(strategy_hit_items) / len(resolved_items) * 100) if resolved_items else 0

    summary = {
        "enabled": True,
        "name": name,
        "depth_options": [
            STRATEGY_SMALL_EDGE_SIZE,
            STRATEGY_MEDIUM_EDGE_SIZE,
            STRATEGY_LARGE_EDGE_SIZE,
        ],
        "triggered_items": triggered_items,
        "resolved_items": len(resolved_items),
        "hits_in_ranking": hits_in_ranking,
        "outside_ranking": len([item for item in resolved_items if item.get(hit_rank_key) is None]),
        "hit_rate_percent": round(hit_rate, 2),
        "depth_counts": depth_counts,
        "top_1_hits": strategy_distribution["1"],
        "top_3_hits": sum(strategy_distribution[str(rank)] for rank in range(1, 4)),
        "top_5_hits": sum(strategy_distribution[str(rank)] for rank in range(1, 6)),
        "top_10_hits": sum(strategy_distribution[str(rank)] for rank in range(1, 11)),
        "avg_hit_rank": round(sum(int(item[hit_rank_key]) for item in strategy_hit_items) / len(strategy_hit_items), 2) if strategy_hit_items else None,
        "rank_distribution": strategy_distribution,
        "feedback_by_depth": {},
    }
    if use_current_hit_guard is not None:
        summary["uses_current_hit_guard"] = bool(use_current_hit_guard)
    return summary


def _build_strategy_data_for_persistence(item: Mapping[str, Any]) -> Dict[str, Any]:
    ranking_replay = _coerce_number_ranking(
        item.get("ranking_otimizado_replay") or item.get("ranking_otimizado")
    )
    ranking_live = _coerce_number_ranking(
        item.get("ranking_otimizado_live") or item.get("ranking_otimizado")
    )

    strategy_data = {
        "strategy_triggered": item.get("strategy_triggered", False),
        "strategy_trigger_reason": item.get("strategy_trigger_reason", ""),
        "strategy_mode": item.get("strategy_mode", "normal"),
        "strategy_invert_depth": item.get("strategy_invert_depth", 0),
        "strategy_signal_strength": item.get("strategy_signal_strength", 0),
        "strategy_trend_state": item.get("strategy_trend_state", "unknown"),
        "strategy_volatility": item.get("strategy_volatility", 0),
        "strategy_inversion_confidence": item.get("strategy_inversion_confidence", 0.5),
        "strategy_inverted_rank_preview": item.get("strategy_inverted_rank_preview"),
        "strategy_zigzag_gate": item.get("strategy_zigzag_gate", {}),
        "strategy_inversion_gate": item.get("strategy_inversion_gate", {}),
        "strategy_inversion_zone": item.get("strategy_inversion_zone", "none"),
        "strategy_persistence_active": item.get("strategy_persistence_active", False),
        "strategy_reference_ranks": item.get("strategy_reference_ranks", []),
        "ranking_otimizado": ranking_live or ranking_replay,
        "ranking_otimizado_live": ranking_live,
        "ranking_otimizado_replay": ranking_replay,
        "strategy_ranking_mode": "live_no_current_hit_guard",
        "strategy_ranking_algorithm": "inverted_extremes_movement_v2_mana_graph_gated",
    }
    for key in _STRATEGY_FIELD_NAMES:
        suffix = key.removeprefix("strategy_")
        if suffix in {"hit_rank", "plot_rank"}:
            continue
        live_key = f"strategy_live_{suffix}"
        replay_key = f"strategy_replay_{suffix}"
        if live_key in item:
            strategy_data[live_key] = item.get(live_key)
        if replay_key in item:
            strategy_data[replay_key] = item.get(replay_key)
    return strategy_data


def _persist_strategy_items_data(roulette_id: str, items: List[Dict[str, Any]]) -> None:
    """Persiste os dados de estratégia para cada snapshot para evitar recálculos."""
    try:
        for item in items:
            snapshot_id = item.get("snapshot_id")
            if not snapshot_id:
                continue

            # Salvar a decisão e o ranking congelado da estratégia.
            # strategy_hit_rank e strategy_plot_rank NÃO são salvos pois dependem do
            # next_number que ainda não é conhecido quando o snapshot é gerado.
            strategy_data = _build_strategy_data_for_persistence(item)

            # Salvar no banco de dados de forma assíncrona (fire-and-forget)
            # Usamos update_one com $set para atualizar apenas os campos de estratégia
            suggestion_snapshots_coll.update_one(
                {"_id": snapshot_id},
                {"$set": {f"strategy_data.{key}": value for key, value in strategy_data.items()}},
                upsert=False,
            )
    except Exception as e:
        # Log silencioso - não deve interromper o fluxo
        print(f"⚠️  Falha ao persisti dados de estratégia: {e}")


async def build_suggestion_snapshot_rank_timeline(
    *,
    roulette_id: str,
    limit: int = 200,
    include_all_configs: bool = False,
    zone_top_end: int = ZIGZAG_DEFAULT_TOP_END,
    zone_bottom_start: int = ZIGZAG_DEFAULT_BOTTOM_START,
    mirror_midpoint: int = MIRROR_DEFAULT_MIDPOINT,
) -> Dict[str, Any]:
    safe_limit = max(20, min(2000, int(limit or 200)))
    safe_top_end = max(1, min(36, int(zone_top_end or ZIGZAG_DEFAULT_TOP_END)))
    safe_bottom_start = max(safe_top_end + 1, min(37, int(zone_bottom_start or ZIGZAG_DEFAULT_BOTTOM_START)))
    safe_mirror_midpoint = max(2, min(36, int(mirror_midpoint or MIRROR_DEFAULT_MIDPOINT)))
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
        anchor_number = int(v) if (v := snapshot_doc.get("anchor_number")) is not None else -1
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

    # PASSO 1: Carregar dados de estratégia já salvos do banco (em lote por snapshot_id)
    snapshot_ids = [item["snapshot_id"] for item in items if item.get("snapshot_id")]
    saved_strategy_map: Dict[str, Dict[str, Any]] = {}
    if snapshot_ids:
        saved_docs = await suggestion_snapshots_coll.find(
            {"_id": {"$in": snapshot_ids}, "strategy_data": {"$exists": True}},
            {"_id": 1, "strategy_data": 1},
        ).to_list(length=len(snapshot_ids))
        for doc in saved_docs:
            sid = str(doc["_id"])
            saved_strategy_map[sid] = doc.get("strategy_data", {})

    # PASSO 2: Calcular replay e live separadamente.
    # Replay mantém a compatibilidade com o MANÁ; live não usa o hit_rank do próprio item.
    _apply_inversion_strategy(items)
    for item in items:
        item["ranking_otimizado_replay"] = list(item.get("ranking_otimizado") or [])
        _snapshot_strategy_fields(item, prefix="strategy_replay")
    _apply_live_inversion_strategy(items)

    # PASSO 3: Para itens com ranking salvo, restaurar o ranking congelado.
    # Dados antigos sem ranking congelado são recalculados e passam a ser persistidos.
    items_to_persist = []
    for item in items:
        sid = item.get("snapshot_id", "")
        saved_strategy = saved_strategy_map.get(sid, {})
        saved_ranking = _coerce_number_ranking(saved_strategy.get("ranking_otimizado"))
        saved_live_ranking = _coerce_number_ranking(
            saved_strategy.get("ranking_otimizado_live") or saved_ranking
        )
        saved_replay_ranking = _coerce_number_ranking(saved_strategy.get("ranking_otimizado_replay"))
        has_frozen_ranking = bool(saved_ranking or saved_live_ranking)

        if has_frozen_ranking:
            for key, value in saved_strategy.items():
                item[key] = value
            if saved_replay_ranking:
                item["ranking_otimizado_replay"] = saved_replay_ranking
            if saved_live_ranking:
                item["ranking_otimizado_live"] = saved_live_ranking
            item["ranking_otimizado"] = saved_ranking or saved_live_ranking
            item["strategy_ranking_frozen"] = True
        else:
            items_to_persist.append(item)
            item["strategy_ranking_frozen"] = False

        invert_depth = item.get("strategy_invert_depth", 0)
        next_number = item.get("next_number")
        ranking_full = item.get("ranking_full") or []
        optimized_ranking = _coerce_number_ranking(item.get("ranking_otimizado"))
        if not optimized_ranking:
            optimized_ranking = _build_optimized_ranking(ranking_full, invert_depth)
            item["ranking_otimizado"] = optimized_ranking

        if invert_depth > 0 and isinstance(next_number, int) and next_number in optimized_ranking:
            strategy_hit_rank = optimized_ranking.index(next_number) + 1
            item["strategy_hit_rank"] = strategy_hit_rank
            item["strategy_plot_rank"] = strategy_hit_rank
        elif invert_depth > 0 and next_number is not None:
            item["strategy_hit_rank"] = None
            item["strategy_plot_rank"] = STRATEGY_OUTSIDE_RANK
        else:
            item["strategy_hit_rank"] = item.get("hit_rank")
            item["strategy_plot_rank"] = item.get("hit_rank") if item.get("hit_rank") is not None else item.get("plot_rank")

        replay_ranking = _coerce_number_ranking(item.get("ranking_otimizado_replay"))
        if replay_ranking and isinstance(next_number, int) and next_number in replay_ranking:
            item["strategy_replay_hit_rank"] = replay_ranking.index(next_number) + 1
            item["strategy_replay_plot_rank"] = item["strategy_replay_hit_rank"]
        elif item.get("strategy_replay_invert_depth", 0) > 0 and next_number is not None:
            item["strategy_replay_hit_rank"] = None
            item["strategy_replay_plot_rank"] = STRATEGY_OUTSIDE_RANK
        else:
            item["strategy_replay_hit_rank"] = item.get("hit_rank")
            item["strategy_replay_plot_rank"] = item.get("hit_rank") if item.get("hit_rank") is not None else item.get("plot_rank")

        live_ranking = _coerce_number_ranking(item.get("ranking_otimizado_live"))
        if live_ranking and isinstance(next_number, int) and next_number in live_ranking:
            item["strategy_live_hit_rank"] = live_ranking.index(next_number) + 1
            item["strategy_live_plot_rank"] = item["strategy_live_hit_rank"]
        elif item.get("strategy_live_invert_depth", 0) > 0 and next_number is not None:
            item["strategy_live_hit_rank"] = None
            item["strategy_live_plot_rank"] = STRATEGY_OUTSIDE_RANK
        else:
            item["strategy_live_hit_rank"] = item.get("hit_rank")
            item["strategy_live_plot_rank"] = item.get("hit_rank") if item.get("hit_rank") is not None else item.get("plot_rank")

    if items_to_persist:
        _persist_strategy_items_data(roulette_id, items_to_persist)

    summary_strategy = _build_strategy_summary_from_items(
        items,
        name="inverted_extremes_movement_v2",
        use_current_hit_guard=True,
    )
    summary_strategy_replay = _build_strategy_summary_from_items(
        items,
        name="inverted_extremes_movement_v2_replay",
        triggered_key="strategy_replay_triggered",
        depth_key="strategy_replay_invert_depth",
        hit_rank_key="strategy_replay_hit_rank",
        use_current_hit_guard=True,
    )
    summary_strategy_live = _build_strategy_summary_from_items(
        items,
        name="inverted_extremes_movement_v2_live",
        triggered_key="strategy_live_triggered",
        depth_key="strategy_live_invert_depth",
        hit_rank_key="strategy_live_hit_rank",
        use_current_hit_guard=False,
    )

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
    summary["strategy"] = summary_strategy
    summary["strategy_replay"] = summary_strategy_replay
    summary["strategy_live"] = summary_strategy_live

    summary["range_prediction"] = _apply_movement_range_prediction(items)
    summary["zigzag_diagnostics"] = _build_zigzag_diagnostics(
        items,
        top_end=safe_top_end,
        bottom_start=safe_bottom_start,
    )
    summary["mirror_strategy"] = _apply_alternating_mirror_strategy(
        items,
        midpoint=safe_mirror_midpoint,
    )
    summary["rolling_zigzag_diagnostics"] = _build_rolling_zigzag_diagnostics(
        items,
        window=ROLLING_ZIGZAG_DEFAULT_WINDOW,
        top_end=safe_top_end,
        bottom_start=safe_bottom_start,
    )

    return {
        "available": True,
        "roulette_id": roulette_id,
        "summary": summary,
        "items": items,
    }


MIRROR_SIM_DEFAULT_K_LIST = (3, 5, 7, 10)


def _mirror_sim_empty_strategy() -> Dict[str, Any]:
    return {
        "signals": 0,
        "hits_by_k": {str(k): 0 for k in MIRROR_SIM_DEFAULT_K_LIST},
        "hit_rate_by_k": {str(k): 0.0 for k in MIRROR_SIM_DEFAULT_K_LIST},
        "avg_effective_rank": None,
        "outside_ranking": 0,
    }


async def simulate_alternating_mirror_walkforward(
    *,
    roulette_id: str,
    limit: int = 1000,
    include_all_configs: bool = False,
    window: int = ROLLING_ZIGZAG_DEFAULT_WINDOW,
    midpoint: int = MIRROR_DEFAULT_MIDPOINT,
    zone_top_end: int = ZIGZAG_DEFAULT_TOP_END,
    zone_bottom_start: int = ZIGZAG_DEFAULT_BOTTOM_START,
    gate_acf_threshold: float = ROLLING_ZIGZAG_GATE_ACF_THRESHOLD,
) -> Dict[str, Any]:
    timeline = await build_suggestion_snapshot_rank_timeline(
        roulette_id=roulette_id,
        limit=limit,
        include_all_configs=include_all_configs,
        zone_top_end=zone_top_end,
        zone_bottom_start=zone_bottom_start,
        mirror_midpoint=midpoint,
    )
    items = timeline.get("items") or []
    safe_window = max(ZIGZAG_MIN_SAMPLE, min(500, int(window or ROLLING_ZIGZAG_DEFAULT_WINDOW)))
    safe_midpoint = max(2, min(36, int(midpoint or MIRROR_DEFAULT_MIDPOINT)))

    # Per-strategy aggregates
    strategies = {
        "baseline": _mirror_sim_empty_strategy(),
        "mirror_always": _mirror_sim_empty_strategy(),
        "mirror_gated": _mirror_sim_empty_strategy(),
    }
    strategies["mirror_gated"]["gated_steps"] = 0
    strategies["mirror_gated"]["gated_hits_by_k"] = {str(k): 0 for k in MIRROR_SIM_DEFAULT_K_LIST}

    expect_low = True
    warmup_skipped = 0
    evaluated = 0
    effective_ranks: Dict[str, List[int]] = {key: [] for key in strategies}

    for item in items:
        if item.get("next_number") is None:
            continue
        # Need rolling diagnostic to be informative for the gate; otherwise treat as warmup
        rolling = item.get("rolling_zigzag") or {}
        window_size = int(rolling.get("window_size") or 0)
        gate_active = bool(rolling.get("gate_active"))
        if window_size < safe_window:
            warmup_skipped += 1
            # Still update mirror state with whatever we have so the strategy isn't cold
            hit_rank_state = item.get("hit_rank")
            effective_for_state = (
                int(hit_rank_state)
                if isinstance(hit_rank_state, int)
                else STRATEGY_OUTSIDE_RANK
            )
            expect_low = effective_for_state > safe_midpoint
            continue

        evaluated += 1
        hit_rank = item.get("hit_rank")
        is_hit = isinstance(hit_rank, int)

        for strategy_name in ("baseline", "mirror_always", "mirror_gated"):
            if strategy_name == "baseline":
                bet_top = True
            elif strategy_name == "mirror_always":
                bet_top = expect_low
            else:  # mirror_gated
                bet_top = (not gate_active) or expect_low

            stats = strategies[strategy_name]
            stats["signals"] += 1
            if not is_hit:
                stats["outside_ranking"] += 1
                effective_ranks[strategy_name].append(STRATEGY_OUTSIDE_RANK)
            else:
                effective_rank = (
                    int(hit_rank) if bet_top else (38 - int(hit_rank))
                )
                effective_ranks[strategy_name].append(effective_rank)
                for k in MIRROR_SIM_DEFAULT_K_LIST:
                    if 1 <= effective_rank <= k:
                        stats["hits_by_k"][str(k)] += 1

            if strategy_name == "mirror_gated" and gate_active:
                stats["gated_steps"] += 1
                if is_hit:
                    bot_rank = 38 - int(hit_rank)
                    for k in MIRROR_SIM_DEFAULT_K_LIST:
                        if 1 <= bot_rank <= k:
                            stats["gated_hits_by_k"][str(k)] += 1

        # Update mirror state for next iteration using the original observation.
        effective_for_state = (
            int(hit_rank) if is_hit else STRATEGY_OUTSIDE_RANK
        )
        expect_low = effective_for_state > safe_midpoint

    for strategy_name, stats in strategies.items():
        signals = stats["signals"]
        for k in MIRROR_SIM_DEFAULT_K_LIST:
            stats["hit_rate_by_k"][str(k)] = (
                round(stats["hits_by_k"][str(k)] / signals * 100.0, 2) if signals else 0.0
            )
        ranks = effective_ranks[strategy_name]
        stats["avg_effective_rank"] = (
            round(sum(ranks) / len(ranks), 2) if ranks else None
        )

    # Lift = (mirror_gated.hit_rate / baseline.hit_rate) per K — quão mais eficiente é
    lift_vs_baseline = {}
    for k in MIRROR_SIM_DEFAULT_K_LIST:
        baseline_rate = strategies["baseline"]["hit_rate_by_k"][str(k)]
        gated_rate = strategies["mirror_gated"]["hit_rate_by_k"][str(k)]
        always_rate = strategies["mirror_always"]["hit_rate_by_k"][str(k)]
        lift_vs_baseline[str(k)] = {
            "baseline_hit_rate_percent": baseline_rate,
            "mirror_always_hit_rate_percent": always_rate,
            "mirror_gated_hit_rate_percent": gated_rate,
            "always_minus_baseline_pp": round(always_rate - baseline_rate, 2),
            "gated_minus_baseline_pp": round(gated_rate - baseline_rate, 2),
        }

    return {
        "available": True,
        "roulette_id": roulette_id,
        "limit": int(limit),
        "window": safe_window,
        "midpoint": safe_midpoint,
        "zone_top_end": int(zone_top_end),
        "zone_bottom_start": int(zone_bottom_start),
        "gate_acf_threshold": float(gate_acf_threshold),
        "k_list": list(MIRROR_SIM_DEFAULT_K_LIST),
        "warmup_skipped": warmup_skipped,
        "evaluated_items": evaluated,
        "strategies": strategies,
        "comparison_by_k": lift_vs_baseline,
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
