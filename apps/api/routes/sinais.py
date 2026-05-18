from __future__ import annotations

from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from pymongo import DESCENDING

from api.core.db import gatilhos_coll, sinais_coll

router = APIRouter()


def _serialize(doc: Dict[str, Any], gatilho_stats: Dict[Any, Dict] = {}) -> Dict[str, Any]:
    attempts = [
        {
            "attempt": a.get("attempt"),
            "value": a.get("value"),
            "hit": a.get("hit"),
            "timestamp": a["timestamp"].isoformat() if a.get("timestamp") else None,
        }
        for a in (doc.get("attempts") or [])
    ]
    gid = doc.get("gatilho_id")
    stats = gatilho_stats.get(gid, {})
    g_won  = int(stats.get("won",  0))
    g_lost = int(stats.get("lost", 0))
    g_fin  = g_won + g_lost
    g_pct  = round(g_won / g_fin * 100, 1) if g_fin else None

    return {
        "id": str(doc["_id"]),
        "gatilho_id": str(gid or ""),
        "trigger_number": doc.get("trigger_number"),
        "source_roulette_id": doc.get("source_roulette_id"),
        "fired_roulette_id": doc.get("fired_roulette_id"),
        "generation": doc.get("generation"),
        "triplet": list(doc.get("triplet") or []),
        "trigger_pct": doc.get("trigger_pct"),
        "ranking_snapshot": list(doc.get("ranking_snapshot") or [])[:5],
        "bet_numbers": list(doc.get("bet_numbers") or []),
        "original_bet_numbers": list(doc.get("original_bet_numbers") or []),
        "history_at_fire": list(doc.get("history_at_fire") or []),
        "has_sequence": bool(doc.get("has_sequence", False)),
        "sequence_details": list(doc.get("sequence_details") or []),
        "gatilho_won": g_won,
        "gatilho_lost": g_lost,
        "gatilho_pct": g_pct,
        "attempts": attempts,
        "status": doc.get("status"),
        "won_at_attempt": doc.get("won_at_attempt"),
        "resolved_at": doc["resolved_at"].isoformat() if doc.get("resolved_at") else None,
        "competing_signal_ids": [str(s) for s in (doc.get("competing_signal_ids") or [])],
        "minutes_since_gatilho": doc.get("minutes_since_gatilho"),
        "confirmation_spin": doc.get("confirmation_spin"),
        "ctx_overlap_top5": doc.get("ctx_overlap_top5"),
        "ctx_triplet_matches": doc.get("ctx_triplet_matches"),
        "created_at": doc["created_at"].isoformat() if doc.get("created_at") else None,
    }


@router.get("/api/sinais")
async def list_sinais(
    fired_roulette_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    query: Dict[str, Any] = {}
    if status:
        query["status"] = status
    if fired_roulette_id:
        query["fired_roulette_id"] = fired_roulette_id.strip()

    cursor = sinais_coll.find(query).sort([("created_at", DESCENDING)])
    if limit > 0:
        cursor = cursor.limit(limit)
    docs = [doc async for doc in cursor]

    # Batch lookup gatilho stats (signals_won / signals_lost)
    gids = list({doc["gatilho_id"] for doc in docs if doc.get("gatilho_id")})
    gatilho_stats: Dict[Any, Dict] = {}
    if gids:
        async for g in gatilhos_coll.find(
            {"_id": {"$in": gids}},
            {"signals_won": 1, "signals_lost": 1},
        ):
            gatilho_stats[g["_id"]] = {
                "won":  g.get("signals_won",  0),
                "lost": g.get("signals_lost", 0),
            }

    return {"total": len(docs), "sinais": [_serialize(d, gatilho_stats) for d in docs]}


@router.delete("/api/sinais/{sinal_id}")
async def delete_sinal(sinal_id: str) -> Dict[str, Any]:
    try:
        oid = ObjectId(sinal_id)
    except Exception:
        raise HTTPException(status_code=400, detail="sinal_id inválido")
    result = await sinais_coll.delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Sinal não encontrado")
    return {"deleted": sinal_id}


@router.get("/api/sinais/{sinal_id}")
async def get_sinal(sinal_id: str) -> Dict[str, Any]:
    try:
        oid = ObjectId(sinal_id)
    except Exception:
        raise HTTPException(status_code=400, detail="sinal_id inválido")
    doc = await sinais_coll.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Sinal não encontrado")
    gid = doc.get("gatilho_id")
    stats: Dict[Any, Dict] = {}
    if gid:
        g = await gatilhos_coll.find_one({"_id": gid}, {"signals_won": 1, "signals_lost": 1})
        if g:
            stats[gid] = {"won": g.get("signals_won", 0), "lost": g.get("signals_lost", 0)}
    return _serialize(doc, stats)
