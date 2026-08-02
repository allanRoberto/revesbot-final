from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Literal

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from pymongo import DESCENDING

from api.core.db import minute_region_signals_coll
from api.services.minute_region_signal_stats import (
    build_available_coverages_pipeline,
    build_accuracy_pipeline,
    build_attempt_accuracy_rows,
    build_hit_count_rows,
    build_signal_list_pipeline,
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
) -> Dict[str, Any]:
    query: Dict[str, Any] = {"roulette_id": str(roulette_id).strip()}
    if status != "all":
        query["status"] = status
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
    coverage_mode: Literal["up_to", "exact"] = Query("up_to"),
    attempt_horizon: int | None = Query(None, ge=1, le=10),
    include_alternative: bool = Query(False),
    hit_count: int | None = Query(None, ge=0, le=10),
    limit: int = Query(100, ge=1, le=500),
):
    safe_status = _safe_status(status)
    query = _filtered_query(
        roulette_id=roulette_id,
        status=safe_status,
    )
    list_pipeline = build_signal_list_pipeline(
        query,
        include_alternative=include_alternative,
        coverage=coverage,
        coverage_mode=coverage_mode,
        attempt_horizon=attempt_horizon or 10,
        hit_count=hit_count,
        limit=limit,
    )
    result_docs = await minute_region_signals_coll.aggregate(list_pipeline).to_list(
        length=1
    )
    result = result_docs[0] if result_docs else {}
    docs = result.get("items", [])
    total_docs = result.get("total", [])
    total = int(total_docs[0].get("value", 0)) if total_docs else 0
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
    coverage_mode: Literal["up_to", "exact"] = Query("up_to"),
    attempt_horizon: int = Query(10, ge=1, le=10),
    include_alternative: bool = Query(False),
):
    safe_status = _safe_status(status)
    base_query = {"roulette_id": str(roulette_id).strip()}
    evaluation_query = _filtered_query(
        roulette_id=roulette_id,
        status=safe_status,
    )
    breakdown_query = _filtered_query(
        roulette_id=roulette_id,
        status=safe_status,
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
            coverage=coverage,
            coverage_mode=coverage_mode,
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
    available_coverages_cursor = minute_region_signals_coll.aggregate(
        build_available_coverages_pipeline(
            breakdown_query,
            include_alternative=include_alternative,
        )
    )
    (
        active,
        completed,
        totals,
        accuracy_docs,
        breakdown_docs,
        coverage_docs,
        newest,
    ) = await asyncio.gather(
        minute_region_signals_coll.count_documents({**base_query, "status": "active"}),
        minute_region_signals_coll.count_documents({**base_query, "status": "completed"}),
        totals_cursor.to_list(length=1),
        accuracy_cursor.to_list(length=1),
        breakdown_cursor.to_list(length=37),
        available_coverages_cursor.to_list(length=37),
        minute_region_signals_coll.find_one(base_query, sort=[("signal_minute_utc", DESCENDING)]),
    )
    available_coverages = sorted(
        int(item["_id"])
        for item in coverage_docs
        if isinstance(item.get("_id"), (int, float))
        and 1 <= int(item["_id"]) <= 37
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
                "coverage_mode": coverage_mode,
                "attempt_horizon": attempt_horizon,
                "include_alternative": include_alternative,
                "evaluated": evaluated,
                "hits": hits,
                "misses": misses,
                "accuracy": round((hits / evaluated) * 100, 2) if evaluated else 0.0,
            },
            "attempt_accuracy": build_attempt_accuracy_rows(
                accuracy_doc,
                attempt_horizon=attempt_horizon,
            ),
            "hit_count_distribution": build_hit_count_rows(
                accuracy_doc,
                attempt_horizon=attempt_horizon,
            ),
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
