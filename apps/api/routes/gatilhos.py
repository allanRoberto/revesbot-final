from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from pymongo import DESCENDING

from api.core.db import gatilhos_coll, sinais_coll

router = APIRouter()


def _serialize(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "roulette_id": doc.get("roulette_id"),
        "generation": doc.get("generation"),
        "triplet": list(doc.get("triplet") or []),
        "trigger_number": doc.get("trigger_number"),
        "trigger_pct": doc.get("trigger_pct"),
        "total_occurrences": doc.get("total_occurrences"),
        "ranking_snapshot": list(doc.get("ranking_snapshot") or [])[:5],
        "bet_numbers": list(doc.get("bet_numbers") or []),
        "status": doc.get("status"),
        "signals_won": doc.get("signals_won", 0),
        "signals_lost": doc.get("signals_lost", 0),
        "signal_count": len(doc.get("signal_ids") or []),
        "confirmation_numbers": list(doc.get("confirmation_numbers") or []),
        "confirmation_spins_seen": doc.get("confirmation_spins_seen", 0),
        "confirmed_at": doc["confirmed_at"].isoformat() if doc.get("confirmed_at") else None,
        "first_signal_at": doc["first_signal_at"].isoformat() if doc.get("first_signal_at") else None,
        "last_won_at": doc["last_won_at"].isoformat() if doc.get("last_won_at") else None,
        "created_at": doc["created_at"].isoformat() if doc.get("created_at") else None,
        "expired_at": doc["expired_at"].isoformat() if doc.get("expired_at") else None,
    }


class BetNumbersUpdate(BaseModel):
    bet_numbers: List[int]


@router.get("/api/gatilhos")
async def list_gatilhos(
    roulette_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default="pending"),
    limit: int = Query(default=200, ge=1, le=500),
) -> Dict[str, Any]:
    query: Dict[str, Any] = {}
    if status == "pending":
        query["status"] = {"$in": ["pending", "pending_confirmation"]}
    elif status:
        query["status"] = status
    if roulette_id:
        query["roulette_id"] = roulette_id.strip()

    cursor = (
        gatilhos_coll
        .find(query)
        .sort([("created_at", DESCENDING)])
        .limit(limit)
    )
    docs = [doc async for doc in cursor]
    return {"total": len(docs), "gatilhos": [_serialize(d) for d in docs]}


@router.put("/api/gatilhos/{gatilho_id}/bet-numbers")
async def update_bet_numbers(gatilho_id: str, body: BetNumbersUpdate) -> Dict[str, Any]:
    try:
        oid = ObjectId(gatilho_id)
    except Exception:
        raise HTTPException(status_code=400, detail="gatilho_id inválido")
    nums = sorted(set(n for n in body.bet_numbers if 0 <= n <= 36))
    if not nums:
        raise HTTPException(status_code=400, detail="bet_numbers não pode ser vazio")
    result = await gatilhos_coll.update_one(
        {"_id": oid},
        {"$set": {"bet_numbers": nums, "updated_at": datetime.datetime.utcnow()}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Gatilho não encontrado")
    return {"id": gatilho_id, "bet_numbers": nums}


@router.delete("/api/gatilhos/{gatilho_id}")
async def delete_gatilho(gatilho_id: str) -> Dict[str, Any]:
    try:
        oid = ObjectId(gatilho_id)
    except Exception:
        raise HTTPException(status_code=400, detail="gatilho_id inválido")
    await sinais_coll.delete_many({"gatilho_id": oid})
    result = await gatilhos_coll.delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Gatilho não encontrado")
    return {"deleted": gatilho_id}
