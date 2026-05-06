"""Trend (ZigZag) signal persistence and tracking.

This service detects ZigZag patterns in the suggestion-rank timeline, persists
each generated signal as a Mongo document, and advances pending signals attempt
by attempt as new spins land. The companion worker calls
``process_trend_signal_for_roulette`` after each snapshot is resolved, so the
strategy keeps running even with the front-end closed.
"""

from __future__ import annotations

import copy
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence

from api.core.db import (
    ensure_suggestion_trend_indexes,
    history_coll,
    suggestion_snapshots_coll,
    suggestion_trend_signals_coll,
    suggestion_trend_strategy_configs_coll,
)
from api.services.suggestion_snapshot_service import (
    _serialize_datetime,
    build_suggestion_snapshot_config_key,
    get_or_create_global_suggestion_snapshot_config,
)


logger = logging.getLogger(__name__)


GLOBAL_TREND_STRATEGY_CONFIG_ID = "global-default"

DEFAULT_TREND_STRATEGY_CONFIG: Dict[str, Any] = {
    "config_id": GLOBAL_TREND_STRATEGY_CONFIG_ID,
    "enabled": False,
    "steps": 3,
    "tolerance": 3,
    "window_size": 7,
    "max_attempts": 4,
    "history_lookback": 1000,
}

ROULETTE_PAYOUT_PER_HIT = 36  # European roulette: 35:1 win + 1 chip stake


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def _coerce_int(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    if n < lo:
        return lo
    if n > hi:
        return hi
    return n


def _normalize_trend_config(raw: Mapping[str, Any] | None) -> Dict[str, Any]:
    base = copy.deepcopy(DEFAULT_TREND_STRATEGY_CONFIG)
    if isinstance(raw, Mapping):
        base["enabled"] = bool(raw.get("enabled", base["enabled"]))
        base["steps"] = _coerce_int(raw.get("steps"), base["steps"], 2, 8)
        base["tolerance"] = _coerce_int(raw.get("tolerance"), base["tolerance"], 0, 10)
        base["window_size"] = _coerce_int(raw.get("window_size"), base["window_size"], 3, 18)
        base["max_attempts"] = _coerce_int(raw.get("max_attempts"), base["max_attempts"], 1, 6)
        base["history_lookback"] = _coerce_int(raw.get("history_lookback"), base["history_lookback"], 100, 2000)
    return base


async def get_or_create_trend_strategy_config() -> Dict[str, Any]:
    await ensure_suggestion_trend_indexes()
    existing = await suggestion_trend_strategy_configs_coll.find_one(
        {"config_id": GLOBAL_TREND_STRATEGY_CONFIG_ID}
    )
    if isinstance(existing, Mapping):
        return _normalize_trend_config(existing)

    document = _normalize_trend_config(DEFAULT_TREND_STRATEGY_CONFIG)
    now = datetime.now(timezone.utc)
    document["created_at_utc"] = now
    document["updated_at_utc"] = now
    await suggestion_trend_strategy_configs_coll.update_one(
        {"config_id": GLOBAL_TREND_STRATEGY_CONFIG_ID},
        {"$setOnInsert": document},
        upsert=True,
    )
    saved = await suggestion_trend_strategy_configs_coll.find_one(
        {"config_id": GLOBAL_TREND_STRATEGY_CONFIG_ID}
    )
    if isinstance(saved, Mapping):
        return _normalize_trend_config(saved)
    return document


async def update_trend_strategy_config(updates: Mapping[str, Any]) -> Dict[str, Any]:
    await ensure_suggestion_trend_indexes()
    current = await get_or_create_trend_strategy_config()
    merged = {**current, **{k: v for k, v in updates.items() if v is not None}}
    normalized = _normalize_trend_config(merged)
    normalized["updated_at_utc"] = datetime.now(timezone.utc)
    await suggestion_trend_strategy_configs_coll.update_one(
        {"config_id": GLOBAL_TREND_STRATEGY_CONFIG_ID},
        {"$set": normalized},
        upsert=True,
    )
    return normalized


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------


def detect_trend_direction(seq: Sequence[int]) -> str:
    if not seq or len(seq) < 2:
        return "lateral"
    first = int(seq[0])
    last = int(seq[-1])
    if last > first:
        return "descida"  # rank value increased = chart fell
    if last < first:
        return "subida"
    return "lateral"


def find_historical_next_ranks(
    items: Sequence[Mapping[str, Any]],
    current_seq_start: int,
    current_seq: Sequence[int],
    tolerance: int,
) -> List[int]:
    n = len(current_seq)
    out: List[int] = []
    if n <= 0:
        return out
    upper = min(current_seq_start, len(items))
    for j in range(0, upper - n + 1):
        ok = True
        for k in range(n):
            r = items[j + k].get("hit_rank")
            if r is None:
                ok = False
                break
            if abs(int(r) - int(current_seq[k])) > tolerance:
                ok = False
                break
        if not ok:
            continue
        next_idx = j + n
        if next_idx >= len(items):
            continue
        next_rank = items[next_idx].get("hit_rank")
        if isinstance(next_rank, int) and 1 <= next_rank <= 36:
            out.append(int(next_rank))
    return out


def median(values: Sequence[int]) -> Optional[float]:
    if not values:
        return None
    sorted_vals = sorted(values)
    mid = len(sorted_vals) // 2
    if len(sorted_vals) % 2 == 0:
        return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2
    return float(sorted_vals[mid])


def compute_bet_window(predicted: int, direction: str, window_size: int) -> Dict[str, int]:
    max_rank = 36
    w = max(1, min(max_rank, int(window_size)))
    p = int(round(predicted))
    if direction == "descida":
        low = p
        high = low + w - 1
        if high > max_rank:
            high = max_rank
            low = max_rank - w + 1
        if low < 1:
            low = 1
    elif direction == "subida":
        high = p
        low = high - w + 1
        if low < 1:
            low = 1
            high = w
        if high > max_rank:
            high = max_rank
    else:
        center = p
        low = center - (w - 1) // 2
        high = low + w - 1
        if low < 1:
            low = 1
            high = w
        if high > max_rank:
            high = max_rank
            low = max_rank - w + 1
    return {"low": int(low), "high": int(high)}


def get_numbers_for_window(ranking_full: Sequence[int], low: int, high: int) -> List[int]:
    if not isinstance(ranking_full, (list, tuple)):
        return []
    out: List[int] = []
    for r in range(low, high + 1):
        idx = r - 1
        if 0 <= idx < len(ranking_full):
            value = ranking_full[idx]
            if isinstance(value, int):
                out.append(int(value))
    return out


# ---------------------------------------------------------------------------
# Signal lifecycle
# ---------------------------------------------------------------------------


def _build_signal_id(roulette_id: str, anchor_history_id: str, config_key: str) -> str:
    return f"{roulette_id}|{anchor_history_id}|{config_key}"


def _serialize_signal(doc: Mapping[str, Any]) -> Dict[str, Any]:
    out = dict(doc)
    out["created_at_utc"] = _serialize_datetime(out.get("created_at_utc"))
    out["updated_at_utc"] = _serialize_datetime(out.get("updated_at_utc"))
    out["resolved_at_utc"] = _serialize_datetime(out.get("resolved_at_utc"))
    out["anchor_timestamp_utc"] = _serialize_datetime(out.get("anchor_timestamp_utc"))
    attempts = out.get("attempts") or []
    serialized_attempts: List[Dict[str, Any]] = []
    for attempt in attempts:
        if not isinstance(attempt, Mapping):
            continue
        ser = dict(attempt)
        ser["anchor_timestamp_utc"] = _serialize_datetime(ser.get("anchor_timestamp_utc"))
        ser["next_timestamp_utc"] = _serialize_datetime(ser.get("next_timestamp_utc"))
        ser["evaluated_at_utc"] = _serialize_datetime(ser.get("evaluated_at_utc"))
        serialized_attempts.append(ser)
    out["attempts"] = serialized_attempts
    out.pop("_id", None)
    return out


async def _load_active_signal(roulette_id: str, config_key: str) -> Optional[Dict[str, Any]]:
    doc = await suggestion_trend_signals_coll.find_one(
        {
            "roulette_id": roulette_id,
            "config_key": config_key,
            "status": "pending",
        }
    )
    return dict(doc) if isinstance(doc, Mapping) else None


def _find_anchor_index(items: Sequence[Mapping[str, Any]], anchor_history_id: str) -> Optional[int]:
    if not anchor_history_id:
        return None
    for idx, it in enumerate(items):
        if str(it.get("anchor_history_id") or "") == anchor_history_id:
            return idx
    return None


async def _advance_pending_signal(
    *,
    signal: Dict[str, Any],
    items: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Evaluate any newly-resolved attempts against the locked rank window."""

    rank_low = int(signal.get("rank_low") or 0)
    rank_high = int(signal.get("rank_high") or 0)
    max_attempts = int(signal.get("max_attempts") or 1)
    window_size = int(signal.get("window_size") or 1)

    anchor_idx = _find_anchor_index(items, str(signal.get("anchor_history_id") or ""))
    if anchor_idx is None:
        return signal  # anchor outside current lookback; skip silently

    attempts = list(signal.get("attempts") or [])
    attempts_used = len(attempts)

    changed = False
    while attempts_used < max_attempts:
        idx = anchor_idx + attempts_used
        if idx >= len(items):
            break
        cur = items[idx]
        hit_rank = cur.get("hit_rank")
        if hit_rank is None:
            break  # outcome not yet observed
        ranking_full = cur.get("ranking_full") or []
        bet_numbers = get_numbers_for_window(ranking_full, rank_low, rank_high)
        is_hit = isinstance(hit_rank, int) and rank_low <= hit_rank <= rank_high
        attempts.append(
            {
                "attempt_index": attempts_used + 1,
                "snapshot_id": str(cur.get("snapshot_id") or ""),
                "anchor_history_id": str(cur.get("anchor_history_id") or ""),
                "anchor_number": cur.get("anchor_number"),
                "anchor_timestamp_utc": cur.get("anchor_timestamp_utc"),
                "next_history_id": str(cur.get("next_history_id") or ""),
                "next_number": cur.get("next_number"),
                "next_timestamp_utc": cur.get("next_timestamp_utc"),
                "ranking_at_attempt": list(ranking_full),
                "bet_numbers": bet_numbers,
                "hit_rank": int(hit_rank) if isinstance(hit_rank, int) else None,
                "hit": bool(is_hit),
                "evaluated_at_utc": datetime.now(timezone.utc),
            }
        )
        attempts_used += 1
        changed = True
        if is_hit:
            signal["status"] = "won"
            signal["winning_attempt"] = attempts_used
            signal["resolved_at_utc"] = datetime.now(timezone.utc)
            signal["pl_chips"] = ROULETTE_PAYOUT_PER_HIT - attempts_used * window_size
            break
        if attempts_used >= max_attempts:
            signal["status"] = "lost"
            signal["winning_attempt"] = None
            signal["resolved_at_utc"] = datetime.now(timezone.utc)
            signal["pl_chips"] = -max_attempts * window_size
            break

    if changed:
        signal["attempts"] = attempts
        signal["attempts_used"] = attempts_used
        signal["updated_at_utc"] = datetime.now(timezone.utc)
        await suggestion_trend_signals_coll.update_one(
            {"_id": signal.get("_id") or signal.get("signal_id")},
            {
                "$set": {
                    "status": signal["status"],
                    "winning_attempt": signal.get("winning_attempt"),
                    "resolved_at_utc": signal.get("resolved_at_utc"),
                    "pl_chips": signal.get("pl_chips"),
                    "attempts": attempts,
                    "attempts_used": attempts_used,
                    "updated_at_utc": signal["updated_at_utc"],
                }
            },
        )
        logger.info(
            "Trend signal advanced | signal_id=%s | roulette=%s | status=%s | attempts_used=%s | hit=%s",
            signal.get("signal_id"),
            signal.get("roulette_id"),
            signal.get("status"),
            attempts_used,
            attempts[-1].get("hit") if attempts else None,
        )
    return signal


async def _maybe_create_signal(
    *,
    roulette_id: str,
    items: Sequence[Mapping[str, Any]],
    trend_config: Mapping[str, Any],
    snapshot_config_key: str,
) -> Optional[Dict[str, Any]]:
    n = int(trend_config["steps"])
    tol = int(trend_config["tolerance"])
    window_size = int(trend_config["window_size"])
    max_attempts = int(trend_config["max_attempts"])

    if len(items) < n + 1:
        return None

    anchor_item = items[-1]
    if anchor_item.get("hit_rank") is not None:
        # Anchor candidate already resolved (the next spin landed before the worker
        # could create a signal). Skip — wait for a fresh anchor.
        return None

    anchor_history_id = str(anchor_item.get("anchor_history_id") or "").strip()
    if not anchor_history_id:
        return None

    seq_items = list(items[-(n + 1):-1])
    seq: List[int] = []
    for it in seq_items:
        r = it.get("hit_rank")
        if not isinstance(r, int):
            return None
        seq.append(int(r))

    direction = detect_trend_direction(seq)
    if direction == "lateral":
        return None

    matches = find_historical_next_ranks(items, len(items) - (n + 1), seq, tol)
    if not matches:
        return None

    med = median(matches)
    if med is None:
        return None
    predicted = int(round(med))
    window = compute_bet_window(predicted, direction, window_size)
    ranking_full = list(anchor_item.get("ranking_full") or [])
    initial_bet_numbers = get_numbers_for_window(ranking_full, window["low"], window["high"])

    signal_id = _build_signal_id(roulette_id, anchor_history_id, snapshot_config_key)
    now = datetime.now(timezone.utc)
    document = {
        "_id": signal_id,
        "signal_id": signal_id,
        "roulette_id": roulette_id,
        "config_id": GLOBAL_TREND_STRATEGY_CONFIG_ID,
        "config_key": snapshot_config_key,
        "steps": n,
        "tolerance": tol,
        "window_size": window_size,
        "max_attempts": max_attempts,
        "trend_direction": direction,
        "current_sequence": seq,
        "current_sequence_anchor_history_ids": [
            str(it.get("anchor_history_id") or "") for it in seq_items
        ],
        "historical_matches_count": len(matches),
        "historical_match_next_ranks": matches,
        "predicted_rank_median": med,
        "predicted_rank": predicted,
        "rank_low": window["low"],
        "rank_high": window["high"],
        "anchor_history_id": anchor_history_id,
        "anchor_number": anchor_item.get("anchor_number"),
        "anchor_timestamp_utc": anchor_item.get("anchor_timestamp_utc"),
        "ranking_at_signal": ranking_full,
        "initial_bet_numbers": initial_bet_numbers,
        "status": "pending",
        "attempts": [],
        "attempts_used": 0,
        "winning_attempt": None,
        "pl_chips": None,
        "created_at_utc": now,
        "updated_at_utc": now,
        "resolved_at_utc": None,
    }
    result = await suggestion_trend_signals_coll.update_one(
        {"_id": signal_id},
        {"$setOnInsert": document},
        upsert=True,
    )
    if result.upserted_id is not None:
        logger.info(
            "Trend signal created | signal_id=%s | roulette=%s | direction=%s | seq=%s | predicted=%s | window=%s-%s | matches=%s",
            signal_id,
            roulette_id,
            direction,
            seq,
            predicted,
            window["low"],
            window["high"],
            len(matches),
        )
        return document
    # Already existed: return current persisted version
    saved = await suggestion_trend_signals_coll.find_one({"_id": signal_id})
    return dict(saved) if isinstance(saved, Mapping) else None


# ---------------------------------------------------------------------------
# Worker entry point
# ---------------------------------------------------------------------------


async def _load_trend_timeline(
    *,
    roulette_id: str,
    config_key: str,
    lookback: int,
) -> List[Dict[str, Any]]:
    """Lightweight chronological timeline used by the trend processor.

    Projects only the snapshot fields the trend logic actually reads
    (`anchor_*`, `ordered_suggestion`/`simple_suggestion`), avoiding the
    multi-hundred-KB payload that `build_suggestion_snapshot_rank_timeline`
    pulls. This drops worker memory usage from ~1 GB to a few MB and lets
    the snapshot worker keep up with live spins.
    """

    safe_limit = max(20, min(2000, int(lookback or 200)))
    fetch_limit = min(safe_limit + 10, 2500)
    history_fetch_limit = min(max(fetch_limit * 4, 300), 4000)

    snap_projection = {
        "snapshot_id": 1,
        "anchor_history_id": 1,
        "anchor_number": 1,
        "anchor_timestamp_utc": 1,
        "config_key": 1,
        "payload.simple_payload.ordered_suggestion": 1,
        "payload.simple_suggestion": 1,
    }

    snapshot_docs = await (
        suggestion_snapshots_coll.find(
            {"roulette_id": roulette_id, "config_key": config_key},
            snap_projection,
        )
        .sort("anchor_timestamp_utc", -1)
        .limit(fetch_limit)
        .to_list(length=fetch_limit)
    )
    if not snapshot_docs:
        return []

    history_docs = await (
        history_coll.find(
            {"roulette_id": roulette_id},
            {"_id": 1, "value": 1, "timestamp": 1},
        )
        .sort("timestamp", -1)
        .limit(history_fetch_limit)
        .to_list(length=history_fetch_limit)
    )
    history_index = {str(doc.get("_id")): idx for idx, doc in enumerate(history_docs)}

    items_desc: List[Dict[str, Any]] = []
    for snap in snapshot_docs:
        anchor_history_id = str(snap.get("anchor_history_id") or "").strip()
        if not anchor_history_id:
            continue
        anchor_idx = history_index.get(anchor_history_id)
        if anchor_idx is None:
            continue
        next_doc = history_docs[anchor_idx - 1] if anchor_idx > 0 else None

        payload = snap.get("payload") or {}
        simple_payload = payload.get("simple_payload") or {}
        ranking = (
            simple_payload.get("ordered_suggestion")
            or payload.get("simple_suggestion")
            or []
        )
        ranking_list = list(ranking) if isinstance(ranking, (list, tuple)) else []

        next_number: Optional[int] = None
        next_history_id = ""
        next_timestamp_utc = None
        hit_rank: Optional[int] = None

        if isinstance(next_doc, Mapping):
            raw_value = next_doc.get("value")
            if raw_value is not None:
                try:
                    next_number = int(raw_value)
                except (TypeError, ValueError):
                    next_number = None
            next_history_id = str(next_doc.get("_id") or "")
            next_timestamp_utc = next_doc.get("timestamp")
            if ranking_list and next_number is not None and next_number in ranking_list:
                hit_rank = ranking_list.index(next_number) + 1

        items_desc.append(
            {
                "snapshot_id": str(snap.get("snapshot_id") or snap.get("_id") or ""),
                "anchor_history_id": anchor_history_id,
                "anchor_number": int(snap.get("anchor_number") or -1),
                "anchor_timestamp_utc": snap.get("anchor_timestamp_utc"),
                "next_history_id": next_history_id,
                "next_number": next_number,
                "next_timestamp_utc": next_timestamp_utc,
                "hit_rank": hit_rank,
                "ranking_full": ranking_list,
            }
        )
        if len(items_desc) >= safe_limit:
            break

    return list(reversed(items_desc))


async def process_trend_signal_for_roulette(roulette_id: str) -> Dict[str, Any]:
    """Run by the snapshot worker after each new spin/snapshot.

    Returns a small status dict so the caller can log outcomes.
    """

    await ensure_suggestion_trend_indexes()
    config = await get_or_create_trend_strategy_config()
    if not config.get("enabled"):
        return {"skipped": "disabled"}

    snapshot_config = await get_or_create_global_suggestion_snapshot_config()
    snapshot_config_key = build_suggestion_snapshot_config_key(snapshot_config)

    lookback = int(config.get("history_lookback") or 1000)
    items = await _load_trend_timeline(
        roulette_id=roulette_id,
        config_key=snapshot_config_key,
        lookback=lookback,
    )
    if not items:
        return {"skipped": "no_items"}

    advanced: Optional[Dict[str, Any]] = None
    pending = await _load_active_signal(roulette_id, snapshot_config_key)
    if pending:
        advanced = await _advance_pending_signal(signal=pending, items=items)

    created: Optional[Dict[str, Any]] = None
    pending_after = advanced if advanced and advanced.get("status") == "pending" else None
    if pending_after is None:
        created = await _maybe_create_signal(
            roulette_id=roulette_id,
            items=items,
            trend_config=config,
            snapshot_config_key=snapshot_config_key,
        )

    return {
        "advanced_signal_id": (advanced or {}).get("signal_id") if advanced else None,
        "advanced_status": (advanced or {}).get("status") if advanced else None,
        "created_signal_id": (created or {}).get("signal_id") if created else None,
        "items_count": len(items),
    }


# ---------------------------------------------------------------------------
# Read APIs (consumed by REST routes / front-end)
# ---------------------------------------------------------------------------


async def list_trend_signals(
    *,
    roulette_id: str,
    limit: int = 50,
    status_filter: Optional[str] = None,
) -> Dict[str, Any]:
    await ensure_suggestion_trend_indexes()
    safe_limit = max(1, min(500, int(limit)))
    query: Dict[str, Any] = {"roulette_id": roulette_id}
    if status_filter and status_filter in {"pending", "won", "lost"}:
        query["status"] = status_filter

    cursor = (
        suggestion_trend_signals_coll.find(query)
        .sort("created_at_utc", -1)
        .limit(safe_limit)
    )
    docs = await cursor.to_list(length=safe_limit)
    items = [_serialize_signal(doc) for doc in docs if isinstance(doc, Mapping)]

    counts = {"pending": 0, "won": 0, "lost": 0}
    pl_total = 0
    for it in items:
        status = str(it.get("status") or "")
        if status in counts:
            counts[status] += 1
        if isinstance(it.get("pl_chips"), int):
            pl_total += int(it["pl_chips"])

    config = await get_or_create_trend_strategy_config()
    return {
        "available": True,
        "roulette_id": roulette_id,
        "config": config,
        "counts": counts,
        "pl_total": pl_total,
        "items": items,
    }


async def get_active_trend_signal(roulette_id: str) -> Dict[str, Any]:
    await ensure_suggestion_trend_indexes()
    snapshot_config = await get_or_create_global_suggestion_snapshot_config()
    snapshot_config_key = build_suggestion_snapshot_config_key(snapshot_config)
    pending = await _load_active_signal(roulette_id, snapshot_config_key)
    config = await get_or_create_trend_strategy_config()
    return {
        "available": bool(pending),
        "roulette_id": roulette_id,
        "config": config,
        "signal": _serialize_signal(pending) if pending else None,
    }
