"""Read-only Redis projection for the live trio dashboard."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import json_util


ROULETTE_ID = "pragmatic-auto-roulette"
PREFIX = "triple_context_live:v1"
STATE_KEY = f"{PREFIX}:state:{ROULETTE_ID}"
HISTORY_KEY = f"{PREFIX}:history:{ROULETTE_ID}"
SUMMARY_KEY = f"{PREFIX}:summary:{ROULETTE_ID}"


def _decode(value: str | bytes | None) -> Any:
    return json_util.loads(value) if value else None


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value) if value is not None else None


def _signal(document: dict[str, Any]) -> dict[str, Any]:
    ranking = [
        {
            "position": int(row["position"]), "number": int(row["number"]),
            "score": float(row.get("score", 0)),
            "direct_hits": int(row.get("direct_hits", 0)),
        }
        for row in document.get("ranking", [])
    ]
    result = document.get("result")
    return {
        "id": str(document.get("id") or document.get("trigger_history_id")),
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


async def get_live_dashboard(redis_client, *, limit: int = 50) -> dict[str, Any]:
    pipeline = redis_client.pipeline(transaction=False)
    pipeline.get(STATE_KEY)
    pipeline.lrange(HISTORY_KEY, 0, limit - 1)
    pipeline.hgetall(SUMMARY_KEY)
    state_raw, rows_raw, summary_raw = await pipeline.execute()
    state = _decode(state_raw) or {}
    rows = [_decode(row) for row in rows_raw]
    counts = {
        name: int(summary_raw.get(name, 0))
        for name in ("won", "lost", "skipped")
    }
    pending = state.get("pending_signal")
    counts["pending"] = 1 if pending else 0
    completed = counts["won"] + counts["lost"]
    heartbeat = state.get("worker_heartbeat_at")
    if isinstance(heartbeat, datetime):
        normalized = heartbeat if heartbeat.tzinfo else heartbeat.replace(tzinfo=timezone.utc)
        heartbeat_age = max(0.0, (datetime.now(timezone.utc) - normalized).total_seconds())
    else:
        heartbeat_age = None
    buffer = state.get("buffer", [])
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
            "phase": state.get("phase", "starting"),
            "collected_in_block": len(buffer),
            "last_processed_at": _iso((state.get("last_processed") or {}).get("timestamp")),
        },
        "current": _signal(pending) if pending else None,
        "summary": {
            **counts, "completed": completed,
            "hit_rate": round(counts["won"] * 100 / completed, 2) if completed else None,
        },
        "history": [_signal(row) for row in rows],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
