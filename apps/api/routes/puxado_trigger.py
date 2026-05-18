from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from pymongo import DESCENDING

from api.core.db import puxado_trigger_signals_coll, puxado_trigger_assertiveness_coll


router = APIRouter()

ALL_STATUSES = ["pending", "fired", "won", "lost", "expired"]


def _serialize(doc: Dict[str, Any], assertiveness_map: Dict[int, Any]) -> Dict[str, Any]:
    tn = doc.get("trigger_number")
    assr = assertiveness_map.get(tn) if tn is not None else None
    return {
        "id": str(doc["_id"]),
        "roulette_id": doc.get("roulette_id"),
        "triplet": list(doc.get("triplet") or []),
        "trigger_number": tn,
        "trigger_pct": doc.get("trigger_pct"),
        "total_occurrences": doc.get("total_occurrences"),
        "bet_numbers": list(doc.get("bet_numbers") or []),
        "status": doc.get("status"),
        "fired_at": doc["fired_at"].isoformat() if doc.get("fired_at") else None,
        "fired_on_roulette": doc.get("fired_on_roulette"),
        "attempts": list(doc.get("attempts") or []),
        "won_at_attempt": doc.get("won_at_attempt"),
        "resolved_at": doc["resolved_at"].isoformat() if doc.get("resolved_at") else None,
        "created_at": doc["created_at"].isoformat() if doc.get("created_at") else None,
        "assertiveness": {
            "won": assr["won"] if assr else None,
            "lost": assr["lost"] if assr else None,
            "total_resolved": assr["total_resolved"] if assr else None,
            "assertiveness": assr["assertiveness"] if assr else None,
        },
    }


@router.get("/api/puxado-triggers")
async def list_puxado_triggers(
    roulette_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
) -> Dict[str, Any]:
    query: Dict[str, Any] = {}
    if status and status in ALL_STATUSES:
        query["status"] = status
    elif not status:
        query["status"] = {"$in": ALL_STATUSES}
    if roulette_id:
        query["roulette_id"] = roulette_id.strip()

    cursor = (
        puxado_trigger_signals_coll
        .find(query)
        .sort([("created_at", DESCENDING)])
        .limit(limit)
    )
    docs = [doc async for doc in cursor]

    trigger_numbers = list({doc.get("trigger_number") for doc in docs if doc.get("trigger_number") is not None})
    assr_cursor = puxado_trigger_assertiveness_coll.find({"_id": {"$in": trigger_numbers}})
    assr_docs = [doc async for doc in assr_cursor]
    assertiveness_map: Dict[int, Any] = {int(doc["_id"]): doc for doc in assr_docs}

    return {
        "total": len(docs),
        "triggers": [_serialize(doc, assertiveness_map) for doc in docs],
    }
