"""Read-only dashboard projection for the live trio worker."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


ROULETTE_ID = "pragmatic-auto-roulette"
STATE_ID = f"triple-context-live:{ROULETTE_ID}:ordered:forward:top6:v1"


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value) if value is not None else None


def _signal(document: dict[str, Any]) -> dict[str, Any]:
    ranking = [
        {
            "position": int(row["position"]),
            "number": int(row["number"]),
            "score": float(row.get("score", 0)),
            "direct_hits": int(row.get("direct_hits", 0)),
        }
        for row in document.get("ranking", [])
    ]
    result = document.get("result")
    return {
        "id": str(document["_id"]),
        "status": document["status"],
        "trio": [int(number) for number in document.get("trio", [])],
        "ranking": ranking,
        "top_numbers": [row["number"] for row in ranking],
        "occurrences": int(document.get("occurrences", 0)),
        "context_events": int(document.get("context_events", 0)),
        "skip_reason": document.get("skip_reason"),
        "result": None if not result else {
            "number": int(result["number"]),
            "timestamp": _iso(result.get("timestamp")),
            "hit": bool(result.get("hit")),
        },
        "created_at": _iso(document.get("created_at")),
        "resolved_at": _iso(document.get("resolved_at")),
    }


async def get_live_dashboard(database, *, limit: int = 50) -> dict[str, Any]:
    signals = database["triple_context_live_signals_v1"]
    states = database["triple_context_live_state_v1"]
    state = await states.find_one({"_id": STATE_ID})
    rows = await signals.find(
        {"roulette_id": ROULETTE_ID},
        {
            "status": 1, "trio": 1, "ranking": 1, "occurrences": 1,
            "context_events": 1, "skip_reason": 1, "result": 1,
            "created_at": 1, "resolved_at": 1,
        },
    ).sort("created_at", -1).limit(limit).to_list(length=limit)

    counts = {"won": 0, "lost": 0, "pending": 0, "skipped": 0}
    async for row in signals.aggregate([
        {"$match": {"roulette_id": ROULETTE_ID}},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
    ]):
        if row.get("_id") in counts:
            counts[row["_id"]] = int(row["count"])
    completed = counts["won"] + counts["lost"]
    heartbeat = state.get("worker_heartbeat_at") if state else None
    if isinstance(heartbeat, datetime):
        normalized = heartbeat if heartbeat.tzinfo else heartbeat.replace(tzinfo=timezone.utc)
        heartbeat_age = max(0.0, (datetime.now(timezone.utc) - normalized).total_seconds())
    else:
        heartbeat_age = None
    pending = next((row for row in rows if row.get("status") == "pending"), None)
    buffer = state.get("buffer", []) if state else []
    return {
        "roulette_id": ROULETTE_ID,
        "configuration": {
            "ordered": True, "direction": "forward", "top_n": 6,
            "attempts": 1, "overlap": False, "block_size": 3,
        },
        "worker": {
            "status": "online" if heartbeat_age is not None and heartbeat_age <= 15 else "offline",
            "heartbeat_at": _iso(heartbeat),
            "heartbeat_age_seconds": heartbeat_age,
            "phase": state.get("phase", "starting") if state else "starting",
            "collected_in_block": len(buffer),
            "last_processed_at": _iso((state.get("last_processed") or {}).get("timestamp")) if state else None,
        },
        "current": _signal(pending) if pending else None,
        "summary": {
            **counts,
            "completed": completed,
            "hit_rate": round(counts["won"] * 100 / completed, 2) if completed else None,
        },
        "history": [_signal(row) for row in rows],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
