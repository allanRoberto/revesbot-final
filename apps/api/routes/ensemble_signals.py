from __future__ import annotations

from datetime import timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from pymongo import DESCENDING

from api.core.db import mongo_db

router = APIRouter()
signals_coll = mongo_db["ensemble_signals"]


def _fmt_ts(ts: Any) -> Optional[str]:
    if ts is None:
        return None
    if hasattr(ts, "isoformat"):
        if getattr(ts, "tzinfo", None) is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.isoformat()
    return str(ts)


def _serialize(doc: Dict[str, Any]) -> Dict[str, Any]:
    attempts = [
        {
            "attempt": a.get("attempt"),
            "value": a.get("value"),
            "hit": a.get("hit"),
            "multiplier": a.get("multiplier", 1),
            "timestamp": _fmt_ts(a.get("timestamp")),
        }
        for a in (doc.get("attempts") or [])
    ]
    return {
        "id": str(doc["_id"]),
        "roulette_id": doc.get("roulette_id", ""),
        "status": doc.get("status", ""),
        "bet": doc.get("bet", []),
        "bet_size": doc.get("bet_size", len(doc.get("bet", []))),
        "ranking": doc.get("ranking", []),
        "n_sources": doc.get("n_sources", 0),
        "sources": doc.get("sources", {}),
        "X_timestamp": _fmt_ts(doc.get("X_timestamp")),
        "attempts": attempts,
        "won_at_attempt": doc.get("won_at_attempt"),
        "pnl": doc.get("pnl"),
        "created_at": _fmt_ts(doc.get("created_at")),
        "resolved_at": _fmt_ts(doc.get("resolved_at")),
        "config": doc.get("config", {}),
    }


async def _net_for(filt: Dict[str, Any]) -> float:
    cursor = signals_coll.find({**filt, "status": {"$in": ["won", "lost"]}}, {"pnl": 1})
    total = 0.0
    async for d in cursor:
        total += float(d.get("pnl") or 0)
    return round(total, 2)


@router.get("/api/ensemble-signals")
async def list_signals(
    roulette_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    min_sources: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    skip: int = Query(0, ge=0),
) -> Dict[str, Any]:
    filt: Dict[str, Any] = {}
    if roulette_id:
        filt["roulette_id"] = roulette_id
    if status and status != "all":
        filt["status"] = status
    if min_sources:
        filt["n_sources"] = {"$gte": int(min_sources)}

    base_filt = {k: v for k, v in filt.items() if k != "status"}

    total = await signals_coll.count_documents(filt)
    docs = (
        await signals_coll.find(filt)
        .sort("created_at", DESCENDING)
        .skip(skip)
        .limit(limit)
        .to_list(length=limit)
    )
    won = await signals_coll.count_documents({**base_filt, "status": "won"})
    lost = await signals_coll.count_documents({**base_filt, "status": "lost"})
    monitoring = await signals_coll.count_documents({**base_filt, "status": "monitoring"})

    resolved = won + lost
    assertiveness_pct = round(won / resolved * 100, 2) if resolved > 0 else 0.0
    net = await _net_for(base_filt)

    avg_attempts_to_win = 0.0
    distribution_attempts: Dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0}
    won_docs = await signals_coll.find({**base_filt, "status": "won"}, {"won_at_attempt": 1}).to_list(length=None)
    if won_docs:
        total_att = sum(int(d.get("won_at_attempt") or 0) for d in won_docs)
        avg_attempts_to_win = round(total_att / len(won_docs), 2)
        for d in won_docs:
            att = int(d.get("won_at_attempt") or 0)
            if att in distribution_attempts:
                distribution_attempts[att] += 1

    # breakdown por nº de fontes (consenso)
    buckets = [(1, 2), (3, 4), (5, 6), (7, 8), (9, 99)]
    sources_breakdown: List[Dict[str, Any]] = []
    for lo, hi in buckets:
        f = {**base_filt, "n_sources": {"$gte": lo, "$lte": hi}}
        b_won = await signals_coll.count_documents({**f, "status": "won"})
        b_lost = await signals_coll.count_documents({**f, "status": "lost"})
        b_mon = await signals_coll.count_documents({**f, "status": "monitoring"})
        b_res = b_won + b_lost
        if b_won + b_lost + b_mon == 0:
            continue
        sources_breakdown.append({
            "range": f"{lo}-{hi}" if hi < 99 else f"{lo}+",
            "total": b_won + b_lost + b_mon,
            "won": b_won,
            "lost": b_lost,
            "monitoring": b_mon,
            "assertiveness": round(b_won / b_res * 100, 2) if b_res > 0 else 0.0,
            "net": await _net_for(f),
        })

    return {
        "filters": {"roulette_id": roulette_id, "status": status, "min_sources": min_sources},
        "total": total,
        "won": won,
        "lost": lost,
        "monitoring": monitoring,
        "resolved": resolved,
        "assertiveness_pct": assertiveness_pct,
        "net": net,
        "avg_attempts_to_win": avg_attempts_to_win,
        "win_distribution": distribution_attempts,
        "sources_breakdown": sources_breakdown,
        "signals": [_serialize(d) for d in docs],
    }


@router.get("/api/ensemble-signals/{signal_id}")
async def get_signal(signal_id: str) -> Dict[str, Any]:
    try:
        oid = ObjectId(signal_id)
    except Exception:
        raise HTTPException(status_code=400, detail="signal_id invalido")
    doc = await signals_coll.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="sinal nao encontrado")
    return _serialize(doc)
