from __future__ import annotations

from datetime import timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from pymongo import DESCENDING

from api.core.db import mongo_db

router = APIRouter()
signals_coll = mongo_db["occurrence_signal_signals"]


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
        "id":                  str(doc["_id"]),
        "roulette_id":         doc.get("roulette_id", ""),
        "status":              doc.get("status", ""),
        "X":                   doc.get("X"),
        "X_timestamp":         _fmt_ts(doc.get("X_timestamp")),
        "trio":                doc.get("trio", []),
        "top4":                doc.get("top4", []),
        "bet":                 doc.get("bet", []),
        "ranking_top10":       doc.get("ranking_top10", []),
        "triplet_match_count": doc.get("triplet_match_count"),
        "attempts":            attempts,
        "post_attempts":       post_attempts,
        "won_at_attempt":      doc.get("won_at_attempt"),
        "needs_post_track":    bool(doc.get("needs_post_track")),
        "created_at":          _fmt_ts(doc.get("created_at")),
        "resolved_at":         _fmt_ts(doc.get("resolved_at")),
        "config":              doc.get("config", {}),
    }


@router.get("/api/occurrence-signal-signals")
async def list_signals(
    roulette_id: Optional[str] = Query(None),
    status: Optional[str]      = Query(None),
    limit:  int                = Query(50, ge=1, le=200),
    skip:   int                = Query(0, ge=0),
) -> Dict[str, Any]:
    filt: Dict[str, Any] = {}
    if roulette_id:
        filt["roulette_id"] = roulette_id
    if status and status != "all":
        filt["status"] = status

    base_filt = {k: v for k, v in filt.items() if k != "status"}

    total      = await signals_coll.count_documents(filt)
    docs       = await signals_coll.find(filt).sort("created_at", DESCENDING).skip(skip).limit(limit).to_list(length=limit)
    won        = await signals_coll.count_documents({**base_filt, "status": "won"})
    lost       = await signals_coll.count_documents({**base_filt, "status": "lost"})
    monitoring = await signals_coll.count_documents({**base_filt, "status": "monitoring"})

    # Inversao paga: sinais perdidos cuja janela pos-derrota teve hit
    inversion_paid = await signals_coll.count_documents({
        **base_filt,
        "status": "lost",
        "post_attempts.hit": True,
    })
    inversion_pending = await signals_coll.count_documents({
        **base_filt,
        "status": "lost",
        "needs_post_track": True,
    })

    # Media de tentativas para vencer
    avg_attempts_to_win = 0.0
    distribution_attempts: Dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0}
    won_docs = await signals_coll.find(
        {**base_filt, "status": "won"},
        {"won_at_attempt": 1},
    ).to_list(length=None)
    if won_docs:
        total_attempts = 0
        for d in won_docs:
            att = int(d.get("won_at_attempt") or 0)
            total_attempts += att
            if att in distribution_attempts:
                distribution_attempts[att] += 1
        avg_attempts_to_win = round(total_attempts / len(won_docs), 2)

    resolved = won + lost
    assertiveness_pct = round(won / resolved * 100, 2) if resolved > 0 else 0.0
    inversion_pay_rate = round(inversion_paid / lost * 100, 2) if lost > 0 else 0.0

    return {
        "filters": {"roulette_id": roulette_id, "status": status},
        "total":             total,
        "won":               won,
        "lost":              lost,
        "monitoring":        monitoring,
        "resolved":          resolved,
        "assertiveness_pct": assertiveness_pct,
        "avg_attempts_to_win": avg_attempts_to_win,
        "win_distribution":  distribution_attempts,
        "inversion": {
            "paid":     inversion_paid,
            "pending":  inversion_pending,
            "pay_rate": inversion_pay_rate,
        },
        "signals": [_serialize(d) for d in docs],
    }


@router.get("/api/occurrence-signal-signals/{signal_id}")
async def get_signal(signal_id: str) -> Dict[str, Any]:
    try:
        oid = ObjectId(signal_id)
    except Exception:
        raise HTTPException(status_code=400, detail="signal_id invalido")
    doc = await signals_coll.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="sinal nao encontrado")
    return _serialize(doc)
