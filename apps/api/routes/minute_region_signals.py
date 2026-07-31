from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from pymongo import DESCENDING

from api.core.db import minute_region_signals_coll


router = APIRouter(prefix="/api/minute-region-signals", tags=["minute-region-signals"])
DEFAULT_ROULETTE_ID = "pragmatic-auto-roulette"


def _serialize(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


@router.get("")
async def list_minute_region_signals(
    roulette_id: str = Query(DEFAULT_ROULETTE_ID, min_length=1),
    status: str = Query("all"),
    limit: int = Query(100, ge=1, le=500),
):
    safe_status = str(status or "all").strip().lower()
    if safe_status not in {"all", "active", "completed"}:
        raise HTTPException(status_code=400, detail="status precisa ser all, active ou completed")

    query: Dict[str, Any] = {"roulette_id": str(roulette_id).strip()}
    if safe_status != "all":
        query["status"] = safe_status
    docs = await (
        minute_region_signals_coll.find(query)
        .sort("signal_minute_utc", DESCENDING)
        .limit(limit)
        .to_list(length=limit)
    )
    return {"items": _serialize(docs), "count": len(docs)}


@router.get("/stats")
async def minute_region_signal_stats(
    roulette_id: str = Query(DEFAULT_ROULETTE_ID, min_length=1),
):
    query = {"roulette_id": str(roulette_id).strip()}
    active = await minute_region_signals_coll.count_documents({**query, "status": "active"})
    completed = await minute_region_signals_coll.count_documents({**query, "status": "completed"})
    totals = await minute_region_signals_coll.aggregate(
        [
            {"$match": query},
            {
                "$group": {
                    "_id": None,
                    "signals": {"$sum": 1},
                    "attempts": {"$sum": "$attempt_count"},
                    "payments": {"$sum": "$payment_count"},
                    "previous_region_hits": {
                        "$sum": {"$cond": ["$previous_region_hit", 1, 0]}
                    },
                }
            },
        ]
    ).to_list(length=1)
    newest = await minute_region_signals_coll.find_one(query, sort=[("signal_minute_utc", DESCENDING)])
    totals_doc = totals[0] if totals else {}
    newest_minute = newest.get("signal_minute_utc") if newest else None
    if isinstance(newest_minute, datetime):
        if newest_minute.tzinfo is None:
            newest_minute = newest_minute.replace(tzinfo=timezone.utc)
        age_seconds = max(0, int((datetime.now(timezone.utc) - newest_minute).total_seconds()))
    else:
        age_seconds = None
    worker_status = "online" if age_seconds is not None and age_seconds <= 120 else "offline"

    return _serialize(
        {
            "roulette_id": query["roulette_id"],
            "active": active,
            "completed": completed,
            "signals": int(totals_doc.get("signals", 0)),
            "attempts": int(totals_doc.get("attempts", 0)),
            "payments": int(totals_doc.get("payments", 0)),
            "previous_region_hits": int(totals_doc.get("previous_region_hits", 0)),
            "worker_status": worker_status,
            "latest_signal_minute_utc": newest_minute,
            "latest_signal_age_seconds": age_seconds,
        }
    )
