from __future__ import annotations

from datetime import timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from pymongo import DESCENDING

from api.core.db import mongo_db

router = APIRouter()
signals_coll = mongo_db["numeros_fortes_inversao_signals"]
live_coll = mongo_db["numeros_fortes_inversao_live"]

STRENGTHS = ("muito_forte", "forte", "mediano", "fraco")


def _fmt_ts(ts: Any) -> Optional[str]:
    if ts is None:
        return None
    if hasattr(ts, "isoformat"):
        if getattr(ts, "tzinfo", None) is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.isoformat()
    return str(ts)


def _serialize_post(pr: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Serializa o bloco de acompanhamento pós-resultado (10 rodadas)."""
    if not pr:
        return None
    rounds = [
        {
            "round":     r.get("round"),
            "value":     r.get("value"),
            "hit":       r.get("hit"),
            "timestamp": _fmt_ts(r.get("timestamp")),
        }
        for r in (pr.get("rounds") or [])
    ]
    return {
        "active":     bool(pr.get("active")),
        "target":     pr.get("target", 0),
        "rounds":     rounds,
        "hits":       pr.get("hits", 0),
        "completed":  bool(pr.get("completed")),
        "started_at": _fmt_ts(pr.get("started_at")),
    }


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
    return {
        "id":                str(doc["_id"]),
        "roulette_id":       doc.get("roulette_id", ""),
        "status":            doc.get("status", ""),
        "trigger_window":    doc.get("trigger_window", []),
        "trigger_hits":      doc.get("trigger_hits", []),
        "trigger_count":     doc.get("trigger_count", 0),
        "trigger_min":       doc.get("trigger_min", 3),
        "numeros_fortes":    doc.get("numeros_fortes", []),
        "gatilhos_snapshot": doc.get("gatilhos_snapshot", []),
        "bet":               doc.get("bet", []),
        "bet_count":         doc.get("bet_count", len(doc.get("bet", []))),
        "strength":          doc.get("strength", "fraco"),
        "score_top":         doc.get("score_top", []),
        "last_numbers":      doc.get("last_numbers", []),
        "window_size":       doc.get("window_size", 0),
        "X_timestamp":       _fmt_ts(doc.get("X_timestamp")),
        "attempts":          attempts,
        "won_at_attempt":    doc.get("won_at_attempt"),
        "pnl":               doc.get("pnl"),
        "inversion":         doc.get("inversion"),
        "post_resolution":   _serialize_post(doc.get("post_resolution")),
        "created_at":        _fmt_ts(doc.get("created_at")),
        "resolved_at":       _fmt_ts(doc.get("resolved_at")),
        "config":            doc.get("config", {}),
    }


@router.get("/api/numeros-fortes-inversao-signals")
async def list_signals(
    roulette_id: Optional[str] = Query(None),
    status:      Optional[str] = Query(None),
    strength:    Optional[str] = Query(None),
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

    base_filt = {k: v for k, v in filt.items() if k not in ("status", "strength")}

    total      = await signals_coll.count_documents(filt)
    docs       = await signals_coll.find(filt).sort("created_at", DESCENDING).skip(skip).limit(limit).to_list(length=limit)
    won        = await signals_coll.count_documents({**base_filt, "status": "won"})
    lost       = await signals_coll.count_documents({**base_filt, "status": "lost"})
    monitoring = await signals_coll.count_documents({**base_filt, "status": "monitoring"})

    # Breakdown por força
    strength_counts: Dict[str, Dict[str, Any]] = {}
    for s in STRENGTHS:
        s_filt = {**base_filt, "strength": s}
        s_won = await signals_coll.count_documents({**s_filt, "status": "won"})
        s_lost = await signals_coll.count_documents({**s_filt, "status": "lost"})
        s_mon = await signals_coll.count_documents({**s_filt, "status": "monitoring"})
        s_res = s_won + s_lost
        strength_counts[s] = {
            "total":         s_won + s_lost + s_mon,
            "won":           s_won,
            "lost":          s_lost,
            "monitoring":    s_mon,
            "assertiveness": round(s_won / s_res * 100, 2) if s_res > 0 else 0.0,
        }

    # Média de tentativas até ganhar + distribuição + PnL acumulado
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

    pnl_docs = await signals_coll.find(
        {**base_filt, "status": {"$in": ["won", "lost"]}}, {"pnl": 1}
    ).to_list(length=None)
    pnl_total = round(sum(float(d.get("pnl") or 0) for d in pnl_docs), 2)

    # Inversão: nº da aposta (gatilhos) que apareceu ANTES do gatilho disparar
    inv_total = await signals_coll.count_documents({**base_filt, "inversion": {"$exists": True}})
    inv_paid  = await signals_coll.count_documents({**base_filt, "inversion.paid": True})
    inversion_stats = {
        "total":     inv_total,
        "paid":      inv_paid,
        "paid_rate": round(inv_paid / inv_total * 100, 2) if inv_total > 0 else 0.0,
    }

    # Pós-resultado: a aposta "paga de novo" nas N rodadas após o sinal resolver
    post_docs = await signals_coll.find(
        {**base_filt, "post_resolution.started_at": {"$ne": None}},
        {"post_resolution": 1},
    ).to_list(length=None)
    post_tracked = len(post_docs)
    post_completed = 0
    post_paid_again = 0
    total_post_hits = 0
    post_target = 0
    for d in post_docs:
        pr = d.get("post_resolution") or {}
        hits = int(pr.get("hits") or 0)
        total_post_hits += hits
        if hits > 0:
            post_paid_again += 1
        if pr.get("completed"):
            post_completed += 1
        post_target = max(post_target, int(pr.get("target") or 0))
    post_resolution_stats = {
        "tracked":         post_tracked,
        "completed":       post_completed,
        "paid_again":      post_paid_again,
        "paid_again_rate": round(post_paid_again / post_tracked * 100, 2) if post_tracked > 0 else 0.0,
        "avg_hits":        round(total_post_hits / post_tracked, 2) if post_tracked > 0 else 0.0,
        "target":          post_target or 10,
    }

    resolved = won + lost
    assertiveness_pct = round(won / resolved * 100, 2) if resolved > 0 else 0.0

    return {
        "filters":             {"roulette_id": roulette_id, "status": status, "strength": strength},
        "total":               total,
        "won":                 won,
        "lost":                lost,
        "monitoring":          monitoring,
        "resolved":            resolved,
        "assertiveness_pct":   assertiveness_pct,
        "avg_attempts_to_win": avg_attempts_to_win,
        "win_distribution":    distribution_attempts,
        "pnl_total":           pnl_total,
        "inversion_stats":     inversion_stats,
        "post_resolution_stats": post_resolution_stats,
        "strength_breakdown":  strength_counts,
        "signals":             [_serialize(d) for d in docs],
    }


@router.get("/api/numeros-fortes-inversao-live")
async def live_analysis(roulette_id: Optional[str] = Query(None)) -> Dict[str, Any]:
    filt: Dict[str, Any] = {}
    if roulette_id:
        filt["roulette_id"] = roulette_id
    docs = await live_coll.find(filt).to_list(length=50)
    out = []
    for d in docs:
        out.append({
            "roulette_id":       d.get("roulette_id", str(d.get("_id", ""))),
            "numeros_fortes":    d.get("numeros_fortes", []),
            "gatilhos":          d.get("gatilhos", []),
            "score_top":         d.get("score_top", []),
            "last_numbers":      d.get("last_numbers", []),
            "trigger_window":    d.get("trigger_window", []),
            "trigger_hits":      d.get("trigger_hits", []),
            "trigger_count":     d.get("trigger_count", 0),
            "trigger_min":       d.get("trigger_min", 3),
            "trigger_ready":     bool(d.get("trigger_ready")),
            "has_active_signal": bool(d.get("has_active_signal")),
            "updated_at":        _fmt_ts(d.get("updated_at")),
        })
    out.sort(key=lambda x: x["roulette_id"])
    return {"live": out}


@router.get("/api/numeros-fortes-inversao-signals/{signal_id}")
async def get_signal(signal_id: str) -> Dict[str, Any]:
    try:
        oid = ObjectId(signal_id)
    except Exception:
        raise HTTPException(status_code=400, detail="signal_id invalido")
    doc = await signals_coll.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="sinal nao encontrado")
    return _serialize(doc)
