from __future__ import annotations

import hashlib
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping

from pymongo import ReplaceOne

from api.core.db import (
    ensure_pattern_score_indexes,
    history_coll,
    pattern_score_events_coll,
    pattern_score_state_coll,
    suggestion_snapshots_coll,
)
from api.patterns.engine import pattern_engine


PATTERN_SCORE_SOURCE_OPTIMIZED = "optimized_payload"
PATTERN_SCORE_SOURCE_SIMPLE = "simple_payload"
PATTERN_SCORE_PARTICIPATION_TOP_N = 12
PATTERN_SCORE_WEIGHT_FLOOR = 0.65
PATTERN_SCORE_WEIGHT_CEIL = 1.55
PATTERN_SCORE_SAMPLE_TARGET = 30.0
PATTERN_SCORE_EWMA_ALPHA = 0.18
PATTERN_SCORE_TO_WEIGHT = 0.80


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)) or default)
    except Exception:
        value = float(default)
    return max(float(minimum), min(float(maximum), float(value)))


PATTERN_SCORE_WEIGHT_CACHE_TTL_SECONDS = _env_float(
    "PATTERN_SCORE_WEIGHT_CACHE_TTL_SECONDS",
    5.0,
    0.0,
    60.0,
)

_KNOWN_PATTERN_IDS_CACHE: List[str] | None = None
_WEIGHT_PROFILE_CACHE: Dict[str, tuple[float, Dict[str, Any]]] = {}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _clone_weight_profile(profile: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        **dict(profile),
        "weights": dict(profile.get("weights") or {}),
        "top_positive": [dict(item) for item in profile.get("top_positive") or [] if isinstance(item, Mapping)],
        "top_negative": [dict(item) for item in profile.get("top_negative") or [] if isinstance(item, Mapping)],
    }


def _coerce_numbers(values: Any, *, limit: int = 37) -> List[int]:
    if not isinstance(values, list):
        return []
    out: List[int] = []
    seen: set[int] = set()
    for raw in values:
        try:
            number = int(raw)
        except (TypeError, ValueError):
            continue
        if not (0 <= number <= 36) or number in seen:
            continue
        seen.add(number)
        out.append(number)
        if len(out) >= max(1, int(limit)):
            break
    return out


def _known_pattern_ids() -> List[str]:
    global _KNOWN_PATTERN_IDS_CACHE
    if _KNOWN_PATTERN_IDS_CACHE is None:
        try:
            _KNOWN_PATTERN_IDS_CACHE = sorted(
                {str(definition.id).strip() for definition in pattern_engine._load_patterns() if str(definition.id).strip()},
                key=len,
                reverse=True,
            )
        except Exception:
            _KNOWN_PATTERN_IDS_CACHE = []
    return list(_KNOWN_PATTERN_IDS_CACHE)


def _canonical_pattern_id(raw_pattern_id: Any) -> str:
    raw = str(raw_pattern_id or "").strip()
    if not raw:
        return ""
    known_ids = _known_pattern_ids()
    if raw in known_ids:
        return raw
    for pattern_id in known_ids:
        if raw.startswith(f"{pattern_id}_"):
            return pattern_id
    return raw


def _extract_ranking_from_payload(payload: Mapping[str, Any]) -> List[int]:
    for key in ("suggestion", "list", "ordered_suggestion", "base_suggestion", "simple_suggestion"):
        ranking = _coerce_numbers(payload.get(key))
        if ranking:
            return ranking
    simple_payload = payload.get("simple_payload")
    if isinstance(simple_payload, Mapping):
        for key in ("ordered_suggestion", "suggestion", "list"):
            ranking = _coerce_numbers(simple_payload.get(key))
            if ranking:
                return ranking
    return []


def _extract_pattern_contributions(payload: Mapping[str, Any]) -> List[Dict[str, Any]]:
    optimized_payload = payload.get(PATTERN_SCORE_SOURCE_OPTIMIZED)
    simple_payload = payload.get(PATTERN_SCORE_SOURCE_SIMPLE)
    source = PATTERN_SCORE_SOURCE_OPTIMIZED
    raw_contributions = []
    if isinstance(optimized_payload, Mapping):
        raw_contributions = list(optimized_payload.get("contributions") or [])
    if not raw_contributions and isinstance(simple_payload, Mapping):
        source = PATTERN_SCORE_SOURCE_SIMPLE
        raw_contributions = list(simple_payload.get("contributions") or [])

    aggregated: Dict[str, Dict[str, Any]] = {}
    for item in raw_contributions:
        if not isinstance(item, Mapping):
            continue
        pattern_id = str(item.get("pattern_id") or "").strip()
        if not pattern_id:
            continue
        numbers = _coerce_numbers(item.get("numbers"))
        if not numbers:
            continue
        row = aggregated.setdefault(
            pattern_id,
            {
                "pattern_id": pattern_id,
                "base_pattern_id": _canonical_pattern_id(item.get("base_pattern_id") or pattern_id) or pattern_id,
                "pattern_name": str(item.get("pattern_name") or pattern_id),
                "source": source,
                "numbers": [],
                "_seen_numbers": set(),
            },
        )
        seen_numbers: set[int] = row["_seen_numbers"]
        for number in numbers:
            if number in seen_numbers:
                continue
            seen_numbers.add(number)
            row["numbers"].append(number)

    contributions: List[Dict[str, Any]] = []
    for row in aggregated.values():
        numbers = sorted(int(number) for number in row.get("numbers") or [])
        if not numbers:
            continue
        contributions.append(
            {
                "pattern_id": str(row["pattern_id"]),
                "base_pattern_id": str(row["base_pattern_id"]),
                "pattern_name": str(row["pattern_name"]),
                "source": str(row["source"]),
                "numbers": numbers,
            }
        )
    contributions.sort(key=lambda item: (str(item["source"]), str(item["pattern_id"])))
    return contributions


def build_pattern_score_events(
    *,
    snapshot_doc: Mapping[str, Any],
    next_doc: Mapping[str, Any],
    participation_top_n: int = PATTERN_SCORE_PARTICIPATION_TOP_N,
) -> List[Dict[str, Any]]:
    payload = snapshot_doc.get("payload")
    if not isinstance(payload, Mapping):
        return []

    try:
        next_number = int(next_doc.get("value"))
    except (TypeError, ValueError):
        return []
    if not (0 <= next_number <= 36):
        return []

    ranking = _extract_ranking_from_payload(payload)
    if not ranking:
        return []

    snapshot_id = str(snapshot_doc.get("snapshot_id") or snapshot_doc.get("_id") or "").strip()
    roulette_id = str(snapshot_doc.get("roulette_id") or "").strip()
    if not snapshot_id or not roulette_id:
        return []

    rank_by_number = {int(number): index + 1 for index, number in enumerate(ranking)}
    next_rank = rank_by_number.get(next_number)
    top_n = max(1, min(37, int(participation_top_n or PATTERN_SCORE_PARTICIPATION_TOP_N)))
    top_rank_set = set(ranking[:top_n])
    now = _now_utc()

    events: List[Dict[str, Any]] = []
    for contribution in _extract_pattern_contributions(payload):
        numbers = _coerce_numbers(contribution.get("numbers"))
        if not numbers:
            continue

        participating_numbers = [number for number in numbers if number in top_rank_set]
        participated = bool(participating_numbers)
        hit = next_number in set(numbers)
        if hit and isinstance(next_rank, int):
            if next_rank <= 5:
                score_delta = 1.50
            elif next_rank <= 12:
                score_delta = 1.20
            elif next_rank <= 18:
                score_delta = 0.90
            else:
                score_delta = 0.60
        elif hit:
            score_delta = 0.60
        else:
            score_delta = -0.35 if participated else -0.05

        chance_base = len(set(numbers)) / 37.0
        miss_score = -0.35 if participated else -0.05
        expected_score_delta = (chance_base * 1.0) + ((1.0 - chance_base) * miss_score)
        adjusted_score_delta = score_delta - expected_score_delta
        event_id = hashlib.sha1(
            f"{roulette_id}|{snapshot_id}|{contribution['source']}|{contribution['pattern_id']}".encode("utf-8")
        ).hexdigest()

        events.append(
            {
                "_id": event_id,
                "event_id": event_id,
                "roulette_id": roulette_id,
                "snapshot_id": snapshot_id,
                "anchor_history_id": str(snapshot_doc.get("anchor_history_id") or ""),
                "anchor_number": int(snapshot_doc.get("anchor_number")) if snapshot_doc.get("anchor_number") is not None else None,
                "anchor_timestamp_utc": snapshot_doc.get("anchor_timestamp_utc"),
                "next_history_id": str(next_doc.get("_id") or ""),
                "next_number": int(next_number),
                "next_rank": int(next_rank) if isinstance(next_rank, int) else None,
                "ranking_size": len(ranking),
                "participation_top_n": top_n,
                "pattern_id": str(contribution["pattern_id"]),
                "base_pattern_id": str(contribution["base_pattern_id"]),
                "pattern_name": str(contribution["pattern_name"]),
                "source": str(contribution["source"]),
                "suggested_numbers": numbers,
                "suggested_count": len(set(numbers)),
                "participating_numbers": participating_numbers,
                "participated_in_ranking": participated,
                "hit": bool(hit),
                "hit_outside_participation": bool(hit and next_number not in top_rank_set),
                "score_delta": round(float(score_delta), 6),
                "expected_score_delta": round(float(expected_score_delta), 6),
                "adjusted_score_delta": round(float(adjusted_score_delta), 6),
                "created_at_utc": now,
            }
        )
    return events


def _build_next_state_doc(previous: Mapping[str, Any], event_doc: Mapping[str, Any]) -> Dict[str, Any]:
    pattern_id = str(event_doc.get("pattern_id") or "").strip()
    roulette_id = str(event_doc.get("roulette_id") or "").strip()
    if not pattern_id or not roulette_id:
        return {}

    state_id = f"{roulette_id}|{pattern_id}"
    activations = int(previous.get("activations") or 0) + 1
    hits = int(previous.get("hits") or 0) + (1 if event_doc.get("hit") else 0)
    misses = int(previous.get("misses") or 0) + (0 if event_doc.get("hit") else 1)
    participated = int(previous.get("participated") or 0) + (1 if event_doc.get("participated_in_ranking") else 0)
    hit_outside = int(previous.get("hit_outside_participation") or 0) + (
        1 if event_doc.get("hit_outside_participation") else 0
    )
    top5_hits = int(previous.get("top5_hits") or 0) + (
        1 if event_doc.get("hit") and isinstance(event_doc.get("next_rank"), int) and int(event_doc["next_rank"]) <= 5 else 0
    )
    top12_hits = int(previous.get("top12_hits") or 0) + (
        1 if event_doc.get("hit") and isinstance(event_doc.get("next_rank"), int) and int(event_doc["next_rank"]) <= 12 else 0
    )
    suggested_count_sum = int(previous.get("suggested_count_sum") or 0) + int(event_doc.get("suggested_count") or 0)
    raw_score_sum = float(previous.get("raw_score_sum") or 0.0) + float(event_doc.get("score_delta") or 0.0)
    adjusted_score_sum = float(previous.get("adjusted_score_sum") or 0.0) + float(event_doc.get("adjusted_score_delta") or 0.0)

    old_ewma = previous.get("score_ewma")
    adjusted_delta = float(event_doc.get("adjusted_score_delta") or 0.0)
    if old_ewma is None or activations <= 1:
        score_ewma = adjusted_delta
    else:
        score_ewma = (float(old_ewma) * (1.0 - PATTERN_SCORE_EWMA_ALPHA)) + (
            adjusted_delta * PATTERN_SCORE_EWMA_ALPHA
        )

    if event_doc.get("hit"):
        consecutive_hits = int(previous.get("consecutive_hits") or 0) + 1
        consecutive_misses = 0
    else:
        consecutive_hits = 0
        consecutive_misses = int(previous.get("consecutive_misses") or 0) + 1

    avg_adjusted_score = adjusted_score_sum / max(1, activations)
    sample_gate = _clamp(activations / PATTERN_SCORE_SAMPLE_TARGET, 0.0, 1.0)
    blended_score = (score_ewma * 0.65) + (avg_adjusted_score * 0.35)
    streak_penalty = min(0.18, max(0, consecutive_misses - 2) * 0.03)
    current_multiplier = _clamp(
        1.0 + (blended_score * PATTERN_SCORE_TO_WEIGHT * sample_gate) - streak_penalty,
        PATTERN_SCORE_WEIGHT_FLOOR,
        PATTERN_SCORE_WEIGHT_CEIL,
    )
    now = _now_utc()

    state_doc = {
        "_id": state_id,
        "roulette_id": roulette_id,
        "pattern_id": pattern_id,
        "base_pattern_id": str(event_doc.get("base_pattern_id") or pattern_id),
        "pattern_name": str(event_doc.get("pattern_name") or pattern_id),
        "source": str(event_doc.get("source") or ""),
        "activations": int(activations),
        "hits": int(hits),
        "misses": int(misses),
        "participated": int(participated),
        "hit_outside_participation": int(hit_outside),
        "top5_hits": int(top5_hits),
        "top12_hits": int(top12_hits),
        "suggested_count_sum": int(suggested_count_sum),
        "raw_score_sum": round(float(raw_score_sum), 6),
        "adjusted_score_sum": round(float(adjusted_score_sum), 6),
        "avg_adjusted_score": round(float(avg_adjusted_score), 6),
        "score_ewma": round(float(score_ewma), 6),
        "sample_gate": round(float(sample_gate), 6),
        "consecutive_hits": int(consecutive_hits),
        "consecutive_misses": int(consecutive_misses),
        "current_multiplier": round(float(current_multiplier), 6),
        "hit_rate": round(hits / max(1, activations), 6),
        "participation_rate": round(participated / max(1, activations), 6),
        "avg_suggested_count": round(suggested_count_sum / max(1, activations), 4),
        "last_event_id": str(event_doc.get("event_id") or ""),
        "last_snapshot_id": str(event_doc.get("snapshot_id") or ""),
        "last_next_number": event_doc.get("next_number"),
        "last_adjusted_score_delta": round(float(adjusted_delta), 6),
        "created_at_utc": previous.get("created_at_utc") or now,
        "updated_at_utc": now,
    }
    return state_doc


async def _apply_state_delta(event_doc: Mapping[str, Any]) -> Dict[str, Any]:
    pattern_id = str(event_doc.get("pattern_id") or "").strip()
    roulette_id = str(event_doc.get("roulette_id") or "").strip()
    if not pattern_id or not roulette_id:
        return {}

    state_id = f"{roulette_id}|{pattern_id}"
    previous = await pattern_score_state_coll.find_one({"_id": state_id}) or {}
    state_doc = _build_next_state_doc(previous, event_doc)
    if not state_doc:
        return {}
    await pattern_score_state_coll.replace_one({"_id": state_id}, state_doc, upsert=True)
    return state_doc


async def score_snapshot_pattern_outcome(
    *,
    snapshot_doc: Mapping[str, Any],
    next_doc: Mapping[str, Any],
    persist: bool = True,
) -> Dict[str, Any]:
    events = build_pattern_score_events(snapshot_doc=snapshot_doc, next_doc=next_doc)
    if not events:
        return {"available": False, "events": 0, "inserted": 0, "skipped_existing": 0}
    if not persist:
        return {
            "available": True,
            "events": len(events),
            "inserted": 0,
            "skipped_existing": 0,
            "dry_run": True,
        }

    await ensure_pattern_score_indexes()
    inserted = 0
    skipped_existing = 0
    for event_doc in events:
        result = await pattern_score_events_coll.update_one(
            {"_id": event_doc["_id"]},
            {"$setOnInsert": dict(event_doc)},
            upsert=True,
        )
        if result.upserted_id is None:
            skipped_existing += 1
            continue
        inserted += 1
        await _apply_state_delta(event_doc)

    return {
        "available": True,
        "events": len(events),
        "inserted": inserted,
        "skipped_existing": skipped_existing,
    }


async def resolve_previous_snapshot_pattern_scores(
    *,
    roulette_id: str,
    current_anchor_doc: Mapping[str, Any],
    config_key: str,
) -> Dict[str, Any]:
    await ensure_pattern_score_indexes()
    current_timestamp = current_anchor_doc.get("timestamp")
    query: Dict[str, Any] = {"roulette_id": roulette_id}
    if current_timestamp is not None:
        query["timestamp"] = {"$lt": current_timestamp}

    previous_history_docs = await (
        history_coll.find(query)
        .sort("timestamp", -1)
        .limit(5)
        .to_list(length=5)
    )
    for previous_doc in previous_history_docs:
        previous_history_id = str(previous_doc.get("_id") or "").strip()
        if not previous_history_id:
            continue
        snapshot_doc = await suggestion_snapshots_coll.find_one(
            {
                "roulette_id": roulette_id,
                "anchor_history_id": previous_history_id,
                "config_key": config_key,
            }
        )
        if not isinstance(snapshot_doc, Mapping):
            continue
        result = await score_snapshot_pattern_outcome(
            snapshot_doc=snapshot_doc,
            next_doc=current_anchor_doc,
            persist=True,
        )
        result["resolved_snapshot_id"] = str(snapshot_doc.get("snapshot_id") or snapshot_doc.get("_id") or "")
        result["resolved_anchor_history_id"] = previous_history_id
        return result

    return {"available": False, "reason": "previous_snapshot_not_found", "inserted": 0, "skipped_existing": 0}


async def load_pattern_score_weight_profile(
    *,
    roulette_id: str,
    min_activations: int = 5,
    max_weights: int = 250,
) -> Dict[str, Any]:
    cache_key = f"{roulette_id}|{int(min_activations or 1)}|{int(max_weights or 250)}"
    now_monotonic = time.monotonic()
    cached = _WEIGHT_PROFILE_CACHE.get(cache_key)
    if cached is not None:
        expires_at, cached_profile = cached
        if expires_at > now_monotonic:
            cloned = _clone_weight_profile(cached_profile)
            cloned["cache"] = "hit"
            return cloned

    await ensure_pattern_score_indexes()
    safe_min_activations = max(1, int(min_activations or 1))
    safe_max_weights = max(1, min(1000, int(max_weights or 250)))
    cursor = (
        pattern_score_state_coll.find(
            {
                "roulette_id": roulette_id,
                "activations": {"$gte": safe_min_activations},
            },
            projection={
                "pattern_id": 1,
                "pattern_name": 1,
                "activations": 1,
                "hits": 1,
                "misses": 1,
                "hit_rate": 1,
                "avg_adjusted_score": 1,
                "score_ewma": 1,
                "current_multiplier": 1,
                "consecutive_misses": 1,
            },
        )
        .sort("updated_at_utc", -1)
        .limit(safe_max_weights)
    )
    docs = [dict(doc) for doc in await cursor.to_list(length=safe_max_weights) if isinstance(doc, Mapping)]

    weights: Dict[str, float] = {}
    details: List[Dict[str, Any]] = []
    for doc in docs:
        pattern_id = str(doc.get("pattern_id") or "").strip()
        if not pattern_id:
            continue
        multiplier = _clamp(float(doc.get("current_multiplier") or 1.0), PATTERN_SCORE_WEIGHT_FLOOR, PATTERN_SCORE_WEIGHT_CEIL)
        if abs(multiplier - 1.0) < 0.001:
            continue
        weights[pattern_id] = round(float(multiplier), 6)
        details.append(
            {
                "pattern_id": pattern_id,
                "pattern_name": str(doc.get("pattern_name") or pattern_id),
                "weight": round(float(multiplier), 6),
                "activations": int(doc.get("activations") or 0),
                "hit_rate": round(float(doc.get("hit_rate") or 0.0), 6),
                "avg_adjusted_score": round(float(doc.get("avg_adjusted_score") or 0.0), 6),
                "score_ewma": round(float(doc.get("score_ewma") or 0.0), 6),
                "consecutive_misses": int(doc.get("consecutive_misses") or 0),
            }
        )

    top_positive = sorted(details, key=lambda item: (-float(item["weight"]), -int(item["activations"])))[:12]
    top_negative = sorted(details, key=lambda item: (float(item["weight"]), -int(item["activations"])))[:12]
    profile = {
        "enabled": True,
        "applied": bool(weights),
        "min_activations": safe_min_activations,
        "weight_count": len(weights),
        "weights": weights,
        "top_positive": top_positive,
        "top_negative": top_negative,
        "cache": "miss",
    }
    if PATTERN_SCORE_WEIGHT_CACHE_TTL_SECONDS > 0:
        _WEIGHT_PROFILE_CACHE[cache_key] = (
            now_monotonic + PATTERN_SCORE_WEIGHT_CACHE_TTL_SECONDS,
            _clone_weight_profile(profile),
        )
    return profile


def merge_pattern_score_weights(
    base_weights: Mapping[str, Any] | None,
    dynamic_weights: Mapping[str, float] | None,
) -> Dict[str, float]:
    merged = {
        str(pattern_id).strip(): float(weight)
        for pattern_id, weight in dict(base_weights or {}).items()
        if str(pattern_id).strip()
    }
    for pattern_id, multiplier in dict(dynamic_weights or {}).items():
        safe_pattern_id = str(pattern_id or "").strip()
        if not safe_pattern_id:
            continue
        merged[safe_pattern_id] = round(float(merged.get(safe_pattern_id, 1.0)) * float(multiplier), 6)
    return merged


async def backfill_pattern_scores_from_snapshots(
    *,
    roulette_id: str,
    limit: int = 1000,
    config_key: str | None = None,
    reset: bool = False,
    dry_run: bool = True,
) -> Dict[str, Any]:
    safe_limit = max(1, min(10000, int(limit or 1000)))
    await ensure_pattern_score_indexes()
    if reset and not dry_run:
        await pattern_score_events_coll.delete_many({"roulette_id": roulette_id})
        await pattern_score_state_coll.delete_many({"roulette_id": roulette_id})

    snapshot_query: Dict[str, Any] = {"roulette_id": roulette_id}
    if config_key:
        snapshot_query["config_key"] = str(config_key)
    snapshots_desc = await (
        suggestion_snapshots_coll.find(snapshot_query)
        .sort("anchor_timestamp_utc", -1)
        .limit(safe_limit)
        .to_list(length=safe_limit)
    )
    snapshots = list(reversed([dict(doc) for doc in snapshots_desc if isinstance(doc, Mapping)]))
    history_fetch_limit = min(max(len(snapshots) * 8, 1000), 30000)
    history_docs = await (
        history_coll.find({"roulette_id": roulette_id})
        .sort("timestamp", -1)
        .limit(history_fetch_limit)
        .to_list(length=history_fetch_limit)
    )
    history_index = {str(doc.get("_id")): idx for idx, doc in enumerate(history_docs) if isinstance(doc, Mapping)}

    summary: Dict[str, Any] = {
        "roulette_id": roulette_id,
        "snapshots_read": len(snapshots),
        "resolved_snapshots": 0,
        "events": 0,
        "inserted": 0,
        "skipped_existing": 0,
        "dry_run": bool(dry_run),
        "reset": bool(reset and not dry_run),
    }
    dry_stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"events": 0, "hits": 0, "adjusted": 0.0})

    if not dry_run and reset:
        all_events: List[Dict[str, Any]] = []
        states_by_id: Dict[str, Dict[str, Any]] = {}
        for snapshot_doc in snapshots:
            anchor_history_id = str(snapshot_doc.get("anchor_history_id") or "").strip()
            anchor_idx = history_index.get(anchor_history_id)
            if anchor_idx is None or anchor_idx <= 0:
                continue
            events = build_pattern_score_events(snapshot_doc=snapshot_doc, next_doc=history_docs[anchor_idx - 1])
            if not events:
                continue
            summary["resolved_snapshots"] += 1
            summary["events"] += len(events)
            for event_doc in events:
                all_events.append(event_doc)
                state_id = f"{event_doc.get('roulette_id')}|{event_doc.get('pattern_id')}"
                previous_state = states_by_id.get(state_id) or {}
                next_state = _build_next_state_doc(previous_state, event_doc)
                if next_state:
                    states_by_id[state_id] = next_state

        for start in range(0, len(all_events), 1000):
            chunk = all_events[start : start + 1000]
            if chunk:
                await pattern_score_events_coll.insert_many(chunk, ordered=False)
        state_ops = [
            ReplaceOne({"_id": state_doc["_id"]}, state_doc, upsert=True)
            for state_doc in states_by_id.values()
        ]
        for start in range(0, len(state_ops), 1000):
            chunk_ops = state_ops[start : start + 1000]
            if chunk_ops:
                await pattern_score_state_coll.bulk_write(chunk_ops, ordered=False)
        summary["inserted"] = len(all_events)
        profile = await load_pattern_score_weight_profile(roulette_id=roulette_id, min_activations=1)
        summary["weight_count"] = int(profile.get("weight_count") or 0)
        summary["top_positive"] = profile.get("top_positive", [])[:12]
        summary["top_negative"] = profile.get("top_negative", [])[:12]
        return summary

    for snapshot_doc in snapshots:
        anchor_history_id = str(snapshot_doc.get("anchor_history_id") or "").strip()
        anchor_idx = history_index.get(anchor_history_id)
        if anchor_idx is None or anchor_idx <= 0:
            continue
        next_doc = history_docs[anchor_idx - 1]
        if dry_run:
            events = build_pattern_score_events(snapshot_doc=snapshot_doc, next_doc=next_doc)
            if not events:
                continue
            summary["resolved_snapshots"] += 1
            summary["events"] += len(events)
            for event_doc in events:
                row = dry_stats[str(event_doc.get("pattern_id") or "")]
                row["events"] += 1
                row["hits"] += 1 if event_doc.get("hit") else 0
                row["adjusted"] += float(event_doc.get("adjusted_score_delta") or 0.0)
            continue

        result = await score_snapshot_pattern_outcome(
            snapshot_doc=snapshot_doc,
            next_doc=next_doc,
            persist=True,
        )
        if not result.get("available"):
            continue
        summary["resolved_snapshots"] += 1
        summary["events"] += int(result.get("events") or 0)
        summary["inserted"] += int(result.get("inserted") or 0)
        summary["skipped_existing"] += int(result.get("skipped_existing") or 0)

    if dry_run:
        preview = []
        for pattern_id, row in dry_stats.items():
            events_count = int(row["events"])
            if events_count <= 0:
                continue
            preview.append(
                {
                    "pattern_id": pattern_id,
                    "events": events_count,
                    "hits": int(row["hits"]),
                    "hit_rate": round(float(row["hits"]) / events_count, 6),
                    "avg_adjusted_score": round(float(row["adjusted"]) / events_count, 6),
                }
            )
        summary["best_preview"] = sorted(preview, key=lambda item: (-float(item["avg_adjusted_score"]), -int(item["events"])))[:12]
        summary["worst_preview"] = sorted(preview, key=lambda item: (float(item["avg_adjusted_score"]), -int(item["events"])))[:12]
    else:
        profile = await load_pattern_score_weight_profile(roulette_id=roulette_id, min_activations=1)
        summary["weight_count"] = int(profile.get("weight_count") or 0)
        summary["top_positive"] = profile.get("top_positive", [])[:12]
        summary["top_negative"] = profile.get("top_negative", [])[:12]

    return summary
