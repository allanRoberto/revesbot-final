from __future__ import annotations

from typing import Any, Dict, List, Optional

from api.core.db import triplet_strategy_bets_coll
from api.services.triplet_strategy_constants import (
    MAX_ATTEMPTS,
    MONITORED_ROULETTES,
    PAYOUT_BY_ROULETTE,
    PER_ATTEMPT_PER_NUMBER_STAKE,
    TOP_N,
)


def _serialize_bet(bet: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if bet is None:
        return None
    out: Dict[str, Any] = {
        "id": str(bet["_id"]),
        "roulette_id": bet.get("roulette_id"),
        "trigger_triplet": list(bet.get("trigger_triplet") or []),
        "trigger_timestamp": bet["trigger_timestamp"].isoformat() if bet.get("trigger_timestamp") else None,
        "bet_numbers": list(bet.get("bet_numbers") or []),
        "ranking_snapshot": list(bet.get("ranking_snapshot") or []),
        "attempts": [
            {
                "attempt": a.get("attempt"),
                "value": a.get("value"),
                "hit": bool(a.get("hit")),
                "timestamp": a["timestamp"].isoformat() if a.get("timestamp") else None,
            }
            for a in (bet.get("attempts") or [])
        ],
        "status": bet.get("status"),
        "won_at_attempt": bet.get("won_at_attempt"),
        "resolved_at": bet["resolved_at"].isoformat() if bet.get("resolved_at") else None,
        "created_at": bet["created_at"].isoformat() if bet.get("created_at") else None,
    }
    return out


async def _aggregate_stats(roulette_id: str) -> Dict[str, int]:
    pipeline = [
        {"$match": {"roulette_id": roulette_id, "status": {"$in": ["won", "lost"]}}},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
    ]
    rows = [doc async for doc in triplet_strategy_bets_coll.aggregate(pipeline)]
    counts = {row["_id"]: int(row["count"]) for row in rows}
    return {
        "won": counts.get("won", 0),
        "lost": counts.get("lost", 0),
    }


async def _win_distribution(roulette_id: str) -> Dict[str, int]:
    pipeline = [
        {"$match": {"roulette_id": roulette_id, "status": "won"}},
        {"$group": {"_id": "$won_at_attempt", "count": {"$sum": 1}}},
    ]
    rows = [doc async for doc in triplet_strategy_bets_coll.aggregate(pipeline)]
    return {str(int(row["_id"])): int(row["count"]) for row in rows if row.get("_id") is not None}


def _compute_assertiveness(won: int, lost: int) -> float:
    total = won + lost
    return round(won / total * 100, 2) if total else 0.0


async def get_strategy_summary() -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    for rid in MONITORED_ROULETTES:
        stats = await _aggregate_stats(rid)
        current = await triplet_strategy_bets_coll.find_one(
            {"roulette_id": rid, "status": "pending"}
        )
        last_resolved = await triplet_strategy_bets_coll.find_one(
            {"roulette_id": rid, "status": {"$in": ["won", "lost"]}},
            sort=[("resolved_at", -1)],
        )
        items.append({
            "roulette_id": rid,
            "won": stats["won"],
            "lost": stats["lost"],
            "total_resolved": stats["won"] + stats["lost"],
            "assertiveness": _compute_assertiveness(stats["won"], stats["lost"]),
            "has_open_bet": current is not None,
            "current_attempts": len((current or {}).get("attempts") or []),
            "last_status": (last_resolved or {}).get("status"),
            "last_resolved_at": (last_resolved or {}).get("resolved_at").isoformat() if last_resolved and last_resolved.get("resolved_at") else None,
        })
    return {
        "roulettes": items,
        "config": {
            "top_n": TOP_N,
            "max_attempts": MAX_ATTEMPTS,
            "payout_by_roulette": PAYOUT_BY_ROULETTE,
            "per_attempt_per_number_stake": PER_ATTEMPT_PER_NUMBER_STAKE,
        },
    }


async def get_resolved_series() -> Dict[str, Any]:
    pipeline = [
        {"$match": {
            "roulette_id": {"$in": MONITORED_ROULETTES},
            "status": {"$in": ["won", "lost"]},
        }},
        {"$sort": {"resolved_at": 1}},
        {"$project": {
            "_id": 0,
            "roulette_id": 1,
            "status": 1,
            "won_at_attempt": 1,
            "bet_size": {"$size": {"$ifNull": ["$bet_numbers", []]}},
        }},
    ]
    rows = [doc async for doc in triplet_strategy_bets_coll.aggregate(pipeline)]
    bets = [
        {
            "roulette_id": r["roulette_id"],
            "status": r["status"],
            "won_at_attempt": r.get("won_at_attempt"),
            "bet_size": int(r.get("bet_size", 0) or 0),
        }
        for r in rows
    ]
    return {
        "bets": bets,
        "config": {
            "payout_by_roulette": PAYOUT_BY_ROULETTE,
            "per_attempt_per_number_stake": PER_ATTEMPT_PER_NUMBER_STAKE,
            "max_attempts": MAX_ATTEMPTS,
        },
    }


async def get_roulette_current(roulette_id: str) -> Dict[str, Any]:
    if roulette_id not in MONITORED_ROULETTES:
        raise LookupError(f"Roleta '{roulette_id}' nao monitorada")
    stats = await _aggregate_stats(roulette_id)
    distribution = await _win_distribution(roulette_id)
    current = await triplet_strategy_bets_coll.find_one(
        {"roulette_id": roulette_id, "status": "pending"}
    )
    return {
        "roulette_id": roulette_id,
        "current_bet": _serialize_bet(current),
        "won": stats["won"],
        "lost": stats["lost"],
        "total_resolved": stats["won"] + stats["lost"],
        "assertiveness": _compute_assertiveness(stats["won"], stats["lost"]),
        "win_distribution": distribution,
        "max_attempts": MAX_ATTEMPTS,
    }


async def get_roulette_history(roulette_id: str, page: int = 1, size: int = 20) -> Dict[str, Any]:
    if roulette_id not in MONITORED_ROULETTES:
        raise LookupError(f"Roleta '{roulette_id}' nao monitorada")
    page = max(page, 1)
    size = max(min(size, 100), 1)
    match: Dict[str, Any] = {"roulette_id": roulette_id, "status": {"$in": ["won", "lost"]}}
    total = await triplet_strategy_bets_coll.count_documents(match)
    cursor = triplet_strategy_bets_coll.find(match).sort("resolved_at", -1).skip((page - 1) * size).limit(size)
    bets = [_serialize_bet(b) for b in [doc async for doc in cursor]]
    total_pages = (total + size - 1) // size if total else 0
    return {
        "roulette_id": roulette_id,
        "page": page,
        "size": size,
        "total": total,
        "total_pages": total_pages,
        "bets": bets,
    }
