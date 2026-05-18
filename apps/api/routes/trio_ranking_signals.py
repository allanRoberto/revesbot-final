from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import timezone

from bson import ObjectId
from fastapi import APIRouter, Query
from pymongo import DESCENDING

from api.core.db import mongo_db

router = APIRouter()
signals_coll = mongo_db["trio_ranking_signals"]


def _fmt_ts(ts) -> Optional[str]:
    if ts is None:
        return None
    if hasattr(ts, "isoformat"):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.isoformat()
    return str(ts)


def _serialize(doc: Dict[str, Any]) -> Dict[str, Any]:
    attempts = [
        {
            "attempt":   a.get("attempt"),
            "value":     a.get("value"),
            "hit":       a.get("hit"),
            "timestamp": _fmt_ts(a.get("timestamp")),
        }
        for a in (doc.get("attempts") or [])
    ]
    post_attempts = [
        {
            "spin":      p.get("spin"),
            "value":     p.get("value"),
            "hit":       p.get("hit"),
            "timestamp": _fmt_ts(p.get("timestamp")),
        }
        for p in (doc.get("post_attempts") or [])
    ]
    return {
        "id":                str(doc["_id"]),
        "roulette_id":       doc.get("roulette_id", ""),
        "status":            doc.get("status", ""),
        "history_numbers":   doc.get("history_numbers", []),
        "last_spin":         doc.get("last_spin"),
        "top_n":             doc.get("top_n", []),
        "ranking":           (doc.get("ranking") or [])[:10],
        "inversion":         bool(doc.get("inversion")),
        "inversion_numbers": doc.get("inversion_numbers", []),
        "attempts":          attempts,
        "post_attempts":     post_attempts,
        "won_at_attempt":    doc.get("won_at_attempt"),
        "created_at":        _fmt_ts(doc.get("created_at")),
        "resolved_at":       _fmt_ts(doc.get("resolved_at")),
        "config":            doc.get("config", {}),
    }


@router.get("/api/trio-ranking-signals")
async def list_signals(
    status: Optional[str] = Query(None),
    limit:  int           = Query(50, ge=1, le=200),
    skip:   int           = Query(0, ge=0),
) -> Dict[str, Any]:
    filt: Dict[str, Any] = {}
    if status and status != "all":
        filt["status"] = status

    total = await signals_coll.count_documents(filt)
    docs  = await signals_coll.find(filt).sort("created_at", DESCENDING).skip(skip).limit(limit).to_list(length=limit)

    won  = await signals_coll.count_documents({"status": "won"})
    lost = await signals_coll.count_documents({"status": "lost"})
    mon  = await signals_coll.count_documents({"status": "monitoring"})

    return {
        "total":      total,
        "won":        won,
        "lost":       lost,
        "monitoring": mon,
        "signals":    [_serialize(d) for d in docs],
    }


@router.get("/api/trio-ranking-signals/{signal_id}")
async def get_signal(signal_id: str) -> Dict[str, Any]:
    doc = await signals_coll.find_one({"_id": ObjectId(signal_id)})
    if not doc:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Signal not found")
    return _serialize(doc)
