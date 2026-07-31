from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from pymongo import DESCENDING

from api.core.db import minute_region_signals_coll
from api.services.minute_region_signal_stats import (
    build_accuracy_pipeline,
    evaluate_signal,
)


router = APIRouter(prefix="/api/minute-region-signals", tags=["minute-region-signals"])
DEFAULT_ROULETTE_ID = "pragmatic-auto-roulette"


def _safe_status(status: str) -> str:
    safe_status = str(status or "all").strip().lower()
    if safe_status not in {"all", "active", "completed"}:
        raise HTTPException(status_code=400, detail="status precisa ser all, active ou completed")
    return safe_status


def _filtered_query(
    *,
    roulette_id: str,
    status: str,
    coverage: int | None,
    attempt_horizon: int | None,
) -> Dict[str, Any]:
    query: Dict[str, Any] = {"roulette_id": str(roulette_id).strip()}
    if status != "all":
        query["status"] = status
    if coverage is not None:
        query["coverage"] = int(coverage)
    if attempt_horizon is not None:
        query["attempt_count"] = {"$gte": int(attempt_horizon)}
    return query


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
    coverage: int | None = Query(None, ge=1, le=37),
    attempt_horizon: int | None = Query(None, ge=1, le=10),
    include_alternative: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
):
    safe_status = _safe_status(status)
    query = _filtered_query(
        roulette_id=roulette_id,
        status=safe_status,
        coverage=coverage,
        attempt_horizon=attempt_horizon,
    )
    docs_cursor = (
        minute_region_signals_coll.find(query)
        .sort("signal_minute_utc", DESCENDING)
        .limit(limit)
    )
    total, docs = await asyncio.gather(
        minute_region_signals_coll.count_documents(query),
        docs_cursor.to_list(length=limit),
    )
    if attempt_horizon is not None:
        for doc in docs:
            doc["evaluation"] = evaluate_signal(
                doc,
                attempt_horizon=attempt_horizon,
                include_alternative=include_alternative,
            )
    return {"items": _serialize(docs), "count": len(docs), "total": total}


@router.get("/stats")
async def minute_region_signal_stats(
    roulette_id: str = Query(DEFAULT_ROULETTE_ID, min_length=1),
    status: str = Query("all"),
    coverage: int | None = Query(None, ge=1, le=37),
    attempt_horizon: int = Query(10, ge=1, le=10),
    include_alternative: bool = Query(False),
):
    safe_status = _safe_status(status)
    base_query = {"roulette_id": str(roulette_id).strip()}
    evaluation_query = _filtered_query(
        roulette_id=roulette_id,
        status=safe_status,
        coverage=coverage,
        attempt_horizon=None,
    )
    breakdown_query = _filtered_query(
        roulette_id=roulette_id,
        status=safe_status,
        coverage=None,
        attempt_horizon=None,
    )
    totals_cursor = minute_region_signals_coll.aggregate(
        [
            {"$match": base_query},
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
    )
    accuracy_cursor = minute_region_signals_coll.aggregate(
        build_accuracy_pipeline(
            evaluation_query,
            attempt_horizon=attempt_horizon,
            include_alternative=include_alternative,
        )
    )
    breakdown_cursor = minute_region_signals_coll.aggregate(
        build_accuracy_pipeline(
            breakdown_query,
            attempt_horizon=attempt_horizon,
            include_alternative=include_alternative,
            group_by_coverage=True,
        )
    )
    (
        active,
        completed,
        totals,
        accuracy_docs,
        breakdown_docs,
        coverage_values,
        newest,
    ) = await asyncio.gather(
        minute_region_signals_coll.count_documents({**base_query, "status": "active"}),
        minute_region_signals_coll.count_documents({**base_query, "status": "completed"}),
        totals_cursor.to_list(length=1),
        accuracy_cursor.to_list(length=1),
        breakdown_cursor.to_list(length=37),
        minute_region_signals_coll.distinct("coverage", base_query),
        minute_region_signals_coll.find_one(base_query, sort=[("signal_minute_utc", DESCENDING)]),
    )
    available_coverages = sorted(
        int(item)
        for item in coverage_values
        if isinstance(item, (int, float)) and 1 <= int(item) <= 37
    )
    totals_doc = totals[0] if totals else {}
    accuracy_doc = accuracy_docs[0] if accuracy_docs else {}
    evaluated = int(accuracy_doc.get("evaluated", 0))
    hits = int(accuracy_doc.get("hits", 0))
    misses = max(0, evaluated - hits)
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
            "roulette_id": base_query["roulette_id"],
            "active": active,
            "completed": completed,
            "signals": int(totals_doc.get("signals", 0)),
            "attempts": int(totals_doc.get("attempts", 0)),
            "payments": int(totals_doc.get("payments", 0)),
            "previous_region_hits": int(totals_doc.get("previous_region_hits", 0)),
            "worker_status": worker_status,
            "latest_signal_minute_utc": newest_minute,
            "latest_signal_age_seconds": age_seconds,
            "evaluation": {
                "coverage": coverage,
                "attempt_horizon": attempt_horizon,
                "include_alternative": include_alternative,
                "evaluated": evaluated,
                "hits": hits,
                "misses": misses,
                "accuracy": round((hits / evaluated) * 100, 2) if evaluated else 0.0,
            },
            "coverage_breakdown": [
                {
                    "coverage": int(item["_id"]),
                    "evaluated": int(item.get("evaluated", 0)),
                    "hits": int(item.get("hits", 0)),
                    "misses": max(0, int(item.get("evaluated", 0)) - int(item.get("hits", 0))),
                    "accuracy": round(
                        (int(item.get("hits", 0)) / int(item.get("evaluated", 0))) * 100,
                        2,
                    )
                    if int(item.get("evaluated", 0))
                    else 0.0,
                }
                for item in breakdown_docs
                if item.get("_id") is not None
            ],
            "available_coverages": available_coverages,
        }
    )
