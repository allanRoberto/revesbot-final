from __future__ import annotations

from datetime import timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from pymongo import DESCENDING

from api.core.db import mongo_db

router = APIRouter()
signals_coll = mongo_db["quadruplet_terminal_signals"]


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
            "attempt":    a.get("attempt"),
            "value":      a.get("value"),
            "hit":        a.get("hit"),
            "multiplier": a.get("multiplier", 1),
            "timestamp":  _fmt_ts(a.get("timestamp")),
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
    pre_window_ts = [_fmt_ts(t) for t in (doc.get("pre_window_ts") or [])]
    return {
        "id":                  str(doc["_id"]),
        "roulette_id":         doc.get("roulette_id", ""),
        "status":              doc.get("status", ""),
        "quadruplet":          doc.get("quadruplet", []),
        "triplet":             doc.get("triplet", []),
        "top3":                doc.get("top3", []),
        "terminal":            doc.get("terminal"),
        "strength":            doc.get("strength", "fraco"),
        "confluence_score":    doc.get("confluence_score", 0),
        "confluence_details":  doc.get("confluence_details", []),
        "direct_count":        doc.get("direct_count", 0),
        "sum_count":           doc.get("sum_count", 0),
        "neighbor_count":      doc.get("neighbor_count", 0),
        "positions":           doc.get("positions", 3),
        "bet":                 doc.get("bet", []),
        "total_occ":           doc.get("total_occ", 0),
        "pre_window":          doc.get("pre_window") or [],
        "pre_window_ts":       pre_window_ts,
        "inversion_paid_before": bool(doc.get("inversion_paid_before", False)),
        "X_timestamp":         _fmt_ts(doc.get("X_timestamp")),
        "attempts":            attempts,
        "post_attempts":       post_attempts,
        "won_at_attempt":      doc.get("won_at_attempt"),
        "pnl":                 doc.get("pnl"),
        "needs_post_track":    bool(doc.get("needs_post_track")),
        "created_at":          _fmt_ts(doc.get("created_at")),
        "resolved_at":         _fmt_ts(doc.get("resolved_at")),
        "config":              doc.get("config", {}),
    }


@router.get("/api/quadruplet-terminal-signals")
async def list_signals(
    roulette_id: Optional[str] = Query(None),
    status:      Optional[str] = Query(None),
    strength:    Optional[str] = Query(None),
    positions:   Optional[int] = Query(None),
    limit:       int           = Query(50, ge=1, le=500),
    skip:        int           = Query(0, ge=0),
) -> Dict[str, Any]:
    filt: Dict[str, Any] = {}
    if roulette_id:
        filt["roulette_id"] = roulette_id
    if status and status != "all":
        filt["status"] = status
    if strength and strength != "all":
        filt["strength"] = strength
    if positions in (1, 3):
        filt["positions"] = positions

    base_filt = {k: v for k, v in filt.items() if k not in ("status", "strength")}

    total      = await signals_coll.count_documents(filt)
    docs       = await signals_coll.find(filt).sort("created_at", DESCENDING).skip(skip).limit(limit).to_list(length=limit)
    won        = await signals_coll.count_documents({**base_filt, "status": "won"})
    lost       = await signals_coll.count_documents({**base_filt, "status": "lost"})
    monitoring = await signals_coll.count_documents({**base_filt, "status": "monitoring"})

    inversion_paid = await signals_coll.count_documents({**base_filt, "inversion_paid_before": True})

    # Breakdown by strength
    strength_counts: Dict[str, Dict[str, int]] = {}
    for s in ("muito_forte", "forte", "mediano", "fraco"):
        s_filt = {**base_filt, "strength": s}
        s_won  = await signals_coll.count_documents({**s_filt, "status": "won"})
        s_lost = await signals_coll.count_documents({**s_filt, "status": "lost"})
        s_mon  = await signals_coll.count_documents({**s_filt, "status": "monitoring"})
        s_tot  = s_won + s_lost + s_mon
        s_res  = s_won + s_lost
        strength_counts[s] = {
            "total":   s_tot,
            "won":     s_won,
            "lost":    s_lost,
            "monitoring": s_mon,
            "assertiveness": round(s_won / s_res * 100, 2) if s_res > 0 else 0.0,
        }

    avg_attempts_to_win = 0.0
    distribution_attempts: Dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0}
    won_docs = await signals_coll.find(
        {**base_filt, "status": "won"}, {"won_at_attempt": 1}
    ).to_list(length=None)
    if won_docs:
        total_att = sum(int(d.get("won_at_attempt") or 0) for d in won_docs)
        avg_attempts_to_win = round(total_att / len(won_docs), 2)
        for d in won_docs:
            att = int(d.get("won_at_attempt") or 0)
            if att in distribution_attempts:
                distribution_attempts[att] += 1

    resolved = won + lost
    assertiveness_pct = round(won / resolved * 100, 2) if resolved > 0 else 0.0
    inversion_pay_rate = round(inversion_paid / total * 100, 2) if total > 0 else 0.0

    # Breakdown by positions (1 vs 3)
    positions_counts: Dict[str, Any] = {}
    for pos in (1, 3):
        p_filt = {**base_filt, "positions": pos}
        p_won  = await signals_coll.count_documents({**p_filt, "status": "won"})
        p_lost = await signals_coll.count_documents({**p_filt, "status": "lost"})
        p_mon  = await signals_coll.count_documents({**p_filt, "status": "monitoring"})
        p_res  = p_won + p_lost
        p_won_docs = await signals_coll.find({**p_filt, "status": "won"}, {"won_at_attempt": 1}).to_list(length=None)
        p_avg = round(sum(int(d.get("won_at_attempt") or 0) for d in p_won_docs) / len(p_won_docs), 2) if p_won_docs else 0.0
        positions_counts[str(pos)] = {
            "total":         p_won + p_lost + p_mon,
            "won":           p_won,
            "lost":          p_lost,
            "monitoring":    p_mon,
            "assertiveness": round(p_won / p_res * 100, 2) if p_res > 0 else 0.0,
            "avg_attempts":  p_avg,
        }

    return {
        "filters":           {"roulette_id": roulette_id, "status": status, "strength": strength, "positions": positions},
        "total":             total,
        "won":               won,
        "lost":              lost,
        "monitoring":        monitoring,
        "resolved":          resolved,
        "assertiveness_pct": assertiveness_pct,
        "avg_attempts_to_win": avg_attempts_to_win,
        "win_distribution":  distribution_attempts,
        "strength_breakdown":   strength_counts,
        "positions_breakdown":  positions_counts,
        "inversion": {
            "paid":     inversion_paid,
            "pay_rate": inversion_pay_rate,
        },
        "signals": [_serialize(d) for d in docs],
    }


@router.get("/api/quadruplet-terminal-signals/{signal_id}")
async def get_signal(signal_id: str) -> Dict[str, Any]:
    try:
        oid = ObjectId(signal_id)
    except Exception:
        raise HTTPException(status_code=400, detail="signal_id invalido")
    doc = await signals_coll.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="sinal nao encontrado")
    return _serialize(doc)
