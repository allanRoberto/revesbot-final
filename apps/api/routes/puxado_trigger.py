from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pymongo import DESCENDING

from api.core.db import puxado_trigger_signals_coll


router = APIRouter()


def _serialize(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "roulette_id": doc.get("roulette_id"),
        "triplet": list(doc.get("triplet") or []),
        "trigger_number": doc.get("trigger_number"),
        "trigger_pct": doc.get("trigger_pct"),
        "total_occurrences": doc.get("total_occurrences"),
        "bet_numbers": list(doc.get("bet_numbers") or []),
        "ranking_snapshot": list(doc.get("ranking_snapshot") or []),
        "last_21": list(doc.get("last_21") or []),
        "status": doc.get("status"),
        "created_at": doc["created_at"].isoformat() if doc.get("created_at") else None,
    }


@router.get("/api/puxado-triggers")
async def list_puxado_triggers(
    roulette_id: Optional[str] = Query(default=None),
    status: str = Query(default="pending"),
    limit: int = Query(default=50, ge=1, le=200),
) -> Dict[str, Any]:
    query: Dict[str, Any] = {"status": status}
    if roulette_id:
        query["roulette_id"] = roulette_id.strip()

    cursor = (
        puxado_trigger_signals_coll
        .find(query)
        .sort([("trigger_pct", DESCENDING), ("created_at", DESCENDING)])
        .limit(limit)
    )
    docs = [doc async for doc in cursor]

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for doc in docs:
        rid = str(doc.get("roulette_id") or "unknown")
        grouped.setdefault(rid, []).append(_serialize(doc))

    return {
        "status_filter": status,
        "total": len(docs),
        "roulettes": grouped,
    }
