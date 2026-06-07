from __future__ import annotations

from datetime import timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from pymongo import DESCENDING

from api.core.db import mongo_db

router = APIRouter()
signals_coll = mongo_db["puxadas_sinal_signals"]


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
        {"attempt": a.get("attempt"), "value": a.get("value"),
         "hit": a.get("hit"), "timestamp": _fmt_ts(a.get("timestamp"))}
        for a in (doc.get("attempts") or [])
    ]
    pt = doc.get("post_tracking") or {}
    post_rounds = [
        {"round": r.get("round"), "value": r.get("value"),
         "hit": r.get("hit"), "timestamp": _fmt_ts(r.get("timestamp"))}
        for r in (pt.get("rounds") or [])
    ]
    inv = doc.get("inversao") or {}
    return {
        "id":              str(doc["_id"]),
        "roulette_id":     doc.get("roulette_id", ""),
        "status":          doc.get("status", ""),
        "trigger_value":   doc.get("trigger_value"),
        "trigger_ts":      _fmt_ts(doc.get("trigger_ts")),
        "ranking":         doc.get("ranking", []),
        "bet":             doc.get("bet", []),
        "bet_chips":       doc.get("bet_chips", 12),
        "inversao": {
            "paid":        bool(inv.get("paid")),
            "hits":        inv.get("hits", []),
            "hit_count":   inv.get("hit_count", 0),
            "window":      inv.get("window", []),
            "window_size": inv.get("window_size", 5),
        },
        "attempts":        attempts,
        "won_at_attempt":  doc.get("won_at_attempt"),
        "pnl":             doc.get("pnl"),
        "post_tracking": {
            "active":    bool(pt.get("active")),
            "rounds":    post_rounds,
            "hits":      pt.get("hits", 0),
            "completed": bool(pt.get("completed")),
            "started_at": _fmt_ts(pt.get("started_at")),
        },
        "created_at":  _fmt_ts(doc.get("created_at")),
        "resolved_at": _fmt_ts(doc.get("resolved_at")),
        "config":      doc.get("config", {}),
    }


@router.get("/api/puxadas-sinal/signals")
async def list_signals(
    roulette_id:    Optional[str] = Query(None),
    status:         Optional[str] = Query(None),
    inversao_paid:  Optional[str] = Query(None),   # "true" | "false"
    limit:          int           = Query(50, ge=1, le=500),
    skip:           int           = Query(0, ge=0),
) -> Dict[str, Any]:
    filt: Dict[str, Any] = {}
    if roulette_id:
        filt["roulette_id"] = roulette_id
    if status and status != "all":
        filt["status"] = status
    if inversao_paid in ("true", "false"):
        filt["inversao.paid"] = (inversao_paid == "true")

    base = {k: v for k, v in filt.items() if k not in ("status",)}

    total      = await signals_coll.count_documents(filt)
    docs       = await signals_coll.find(filt).sort("created_at", DESCENDING).skip(skip).limit(limit).to_list(length=limit)
    won        = await signals_coll.count_documents({**base, "status": "won"})
    lost       = await signals_coll.count_documents({**base, "status": "lost"})
    monitoring = await signals_coll.count_documents({**base, "status": "monitoring"})
    resolved   = won + lost
    assertiveness = round(won / resolved * 100, 1) if resolved else 0.0

    # Distribuição de tentativas
    win_dist: Dict[str, int] = {"1": 0, "2": 0, "3": 0, "4": 0}
    avg_att = None
    if won:
        async for d in signals_coll.find({**base, "status": "won"}, {"won_at_attempt": 1}):
            k = str(d.get("won_at_attempt") or 0)
            if k in win_dist:
                win_dist[k] += 1
        total_att = sum(int(k) * v for k, v in win_dist.items())
        avg_att = round(total_att / won, 2)

    # P&L total
    pnl_total = 0.0
    async for d in signals_coll.find(
        {**base, "status": {"$in": ["won", "lost"]}}, {"pnl": 1}
    ):
        pnl_total += float(d.get("pnl") or 0)

    # Média de hits pós-tracking
    post_hits: List[int] = []
    async for d in signals_coll.find(
        {**base, "post_tracking.completed": True}, {"post_tracking.hits": 1}
    ):
        h = (d.get("post_tracking") or {}).get("hits", 0)
        post_hits.append(int(h))
    avg_post_hits = round(sum(post_hits) / len(post_hits), 2) if post_hits else None

    # Inversão: taxa de paid + assertividade quando paid vs not-paid
    inv_paid_total = await signals_coll.count_documents({**base, "inversao.paid": True})
    inv_paid_won   = await signals_coll.count_documents({**base, "inversao.paid": True, "status": "won"})
    inv_paid_lost  = await signals_coll.count_documents({**base, "inversao.paid": True, "status": "lost"})
    inv_no_total   = await signals_coll.count_documents({**base, "inversao.paid": False})
    inv_no_won     = await signals_coll.count_documents({**base, "inversao.paid": False, "status": "won"})
    inv_no_lost    = await signals_coll.count_documents({**base, "inversao.paid": False, "status": "lost"})

    def _pct(w, l):
        return round(w / (w + l) * 100, 1) if (w + l) > 0 else 0.0

    return {
        "total":               total,
        "won":                 won,
        "lost":                lost,
        "monitoring":          monitoring,
        "resolved":            resolved,
        "assertiveness_pct":   assertiveness,
        "avg_attempts_to_win": avg_att,
        "win_distribution":    win_dist,
        "pnl_total":           round(pnl_total, 2),
        "avg_post_hits":       avg_post_hits,
        "inversao": {
            "paid_total":   inv_paid_total,
            "paid_won":     inv_paid_won,
            "paid_lost":    inv_paid_lost,
            "paid_pct":     _pct(inv_paid_won, inv_paid_lost),
            "no_paid_total": inv_no_total,
            "no_paid_won":  inv_no_won,
            "no_paid_lost": inv_no_lost,
            "no_paid_pct":  _pct(inv_no_won, inv_no_lost),
        },
        "skip":    skip,
        "limit":   limit,
        "signals": [_serialize(d) for d in docs],
    }


@router.get("/api/puxadas-sinal/signals/{signal_id}")
async def get_signal(signal_id: str) -> Dict[str, Any]:
    try:
        oid = ObjectId(signal_id)
    except Exception:
        raise HTTPException(status_code=400, detail="ID inválido")
    doc = await signals_coll.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Sinal não encontrado")
    return _serialize(doc)
