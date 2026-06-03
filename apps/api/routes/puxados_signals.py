from __future__ import annotations

from datetime import timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from pymongo import DESCENDING

from api.core.db import mongo_db

router = APIRouter()
signals_coll  = mongo_db["puxados_signals"]
sequence_coll = mongo_db["puxados_sequence"]


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
    freq_raw = doc.get("frequency") or {}
    frequency = {k: v for k, v in freq_raw.items()}

    inv = doc.get("inversion") or {}
    seq = doc.get("sequence_info") or {}

    return {
        "id":             str(doc["_id"]),
        "roulette_id":    doc.get("roulette_id", ""),
        "status":         doc.get("status", ""),
        "trigger":        doc.get("trigger"),
        "trigger_ts":     _fmt_ts(doc.get("trigger_ts")),
        "occurrences":    doc.get("occurrences", 0),
        "bet":            doc.get("bet", []),
        "bet_size":       doc.get("bet_size", 0),
        "frequency":      frequency,
        "top1":           doc.get("top1"),
        "inversion": {
            "window":      inv.get("window", []),
            "window_size": inv.get("window_size", 4),
            "hits":        inv.get("hits", []),
            "hit_count":   inv.get("hit_count", 0),
            "paid":        inv.get("paid", False),
        },
        "sequence_info": {
            "trigger":     seq.get("trigger"),
            "curr_top1":   seq.get("curr_top1"),
            "prev_top1":   seq.get("prev_top1"),
            "type":        seq.get("type", "primeiro"),
            "is_neighbor": seq.get("is_neighbor", False),
            "history_len": seq.get("history_len", 0),
        },
        "attempts":       attempts,
        "won_at_attempt": doc.get("won_at_attempt"),
        "pnl":            doc.get("pnl"),
        "created_at":     _fmt_ts(doc.get("created_at")),
        "resolved_at":    _fmt_ts(doc.get("resolved_at")),
        "config":         doc.get("config", {}),
    }


# ── GET /api/puxados/signals ──────────────────────────────────

@router.get("/api/puxados/signals")
async def get_puxados_signals(
    roulette_id: Optional[str] = Query(None),
    status:      Optional[str] = Query(None),
    trigger:     Optional[int] = Query(None),
    seq_type:    Optional[str] = Query(None),
    limit:       int           = Query(50, ge=1, le=500),
    skip:        int           = Query(0, ge=0),
):
    filt: Dict[str, Any] = {}
    if roulette_id:
        filt["roulette_id"] = roulette_id
    if status and status != "all":
        filt["status"] = status
    if trigger is not None:
        filt["trigger"] = trigger
    if seq_type and seq_type != "all":
        filt["sequence_info.type"] = seq_type

    total = await signals_coll.count_documents(filt)
    cursor = signals_coll.find(filt).sort("created_at", DESCENDING).skip(skip).limit(limit)
    docs = [_serialize(d) async for d in cursor]

    # ── Estatísticas globais (ignora skip/limit) ──
    resolved_filt = {**filt, "status": {"$in": ["won", "lost"]}}
    won_filt      = {**filt, "status": "won"}
    lost_filt     = {**filt, "status": "lost"}
    mon_filt      = {**filt, "status": "monitoring"}

    won_count  = await signals_coll.count_documents(won_filt)
    lost_count = await signals_coll.count_documents(lost_filt)
    mon_count  = await signals_coll.count_documents(mon_filt)
    resolved   = won_count + lost_count
    assertiveness_pct = round(100 * won_count / resolved, 1) if resolved else 0.0

    # Distribuição de tentativas
    win_dist: Dict[str, int] = {"1": 0, "2": 0, "3": 0, "4": 0}
    won_att_cursor = signals_coll.find(won_filt, {"won_at_attempt": 1})
    async for d in won_att_cursor:
        k = str(d.get("won_at_attempt") or 0)
        if k in win_dist:
            win_dist[k] += 1

    avg_att = None
    if won_count:
        total_att = sum(int(k) * v for k, v in win_dist.items())
        avg_att   = round(total_att / won_count, 2)

    # Inversão
    inv_filt = {**filt, "inversion.paid": True}
    inv_paid = await signals_coll.count_documents(inv_filt)
    inv_rate = round(100 * inv_paid / total, 1) if total else 0.0

    # Sequências
    seq_counts: Dict[str, int] = {}
    seq_cursor = signals_coll.find(filt, {"sequence_info.type": 1})
    async for d in seq_cursor:
        t = (d.get("sequence_info") or {}).get("type", "outro")
        seq_counts[t] = seq_counts.get(t, 0) + 1

    # Média de bet_size
    avg_bet_size = None
    bet_cursor   = signals_coll.find(filt, {"bet_size": 1})
    sizes: List[int] = []
    async for d in bet_cursor:
        bs = d.get("bet_size")
        if bs:
            sizes.append(bs)
    if sizes:
        avg_bet_size = round(sum(sizes) / len(sizes), 1)

    # P&L total
    pnl_cursor = signals_coll.find(resolved_filt, {"pnl": 1})
    pnl_total  = 0.0
    async for d in pnl_cursor:
        pnl_total += float(d.get("pnl") or 0)

    return {
        "total":             total,
        "won":               won_count,
        "lost":              lost_count,
        "monitoring":        mon_count,
        "resolved":          resolved,
        "assertiveness_pct": assertiveness_pct,
        "avg_attempts_to_win": avg_att,
        "win_distribution":  win_dist,
        "inversion": {
            "paid":     inv_paid,
            "pay_rate": inv_rate,
        },
        "sequences":      seq_counts,
        "avg_bet_size":   avg_bet_size,
        "pnl_total":      round(pnl_total, 2),
        "skip":           skip,
        "limit":          limit,
        "signals":        docs,
    }


# ── GET /api/puxados/signals/{id} ────────────────────────────

@router.get("/api/puxados/signals/{signal_id}")
async def get_puxados_signal(signal_id: str):
    try:
        oid = ObjectId(signal_id)
    except Exception:
        raise HTTPException(status_code=400, detail="ID inválido")
    doc = await signals_coll.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Sinal não encontrado")
    return _serialize(doc)


# ── GET /api/puxados/sequences ────────────────────────────────

@router.get("/api/puxados/sequences")
async def get_puxados_sequences(
    roulette_id: Optional[str] = Query(None),
    trigger:     Optional[int] = Query(None),
):
    filt: Dict[str, Any] = {}
    if roulette_id:
        filt["roulette_id"] = roulette_id
    if trigger is not None:
        filt["trigger"] = trigger

    cursor = sequence_coll.find(filt).sort([("roulette_id", 1), ("trigger", 1)])
    out = []
    async for d in cursor:
        history = d.get("history", [])
        out.append({
            "roulette_id": d.get("roulette_id"),
            "trigger":     d.get("trigger"),
            "history_len": len(history),
            "history":     [
                {
                    "signal_id": h.get("signal_id"),
                    "top1":      h.get("top1"),
                    "ts":        _fmt_ts(h.get("ts")),
                }
                for h in history[-10:]
            ],
            "updated_at":  _fmt_ts(d.get("updated_at")),
        })
    return {"sequences": out, "total": len(out)}
