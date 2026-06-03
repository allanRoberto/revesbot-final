from __future__ import annotations

from datetime import timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from pymongo import DESCENDING

from api.core.db import mongo_db

router = APIRouter()
signals_coll = mongo_db["hidra_signals"]

STRATEGY_ORDER = ["cor", "parimpar", "colunas", "duzias"]
STRATEGY_NAMES = {
    "cor": "Cor",
    "parimpar": "Par/Ímpar",
    "colunas": "Colunas",
    "duzias": "Dúzias",
}


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
            "side": a.get("side"),
            "hit": a.get("hit"),
            "bet_amount": a.get("bet_amount"),
            "timestamp": _fmt_ts(a.get("timestamp")),
        }
        for a in (doc.get("attempts") or [])
    ]
    return {
        "id": str(doc["_id"]),
        "roulette_id": doc.get("roulette_id", ""),
        "strategy": doc.get("strategy", ""),
        "strategy_name": doc.get("strategy_name", STRATEGY_NAMES.get(doc.get("strategy", ""), "")),
        "status": doc.get("status", ""),
        "window_snapshot": doc.get("window_snapshot", []),
        "dominant_side": doc.get("dominant_side"),
        "dominant_count": doc.get("dominant_count", 0),
        "bet_sides": doc.get("bet_sides", []),
        "coverage": doc.get("coverage", 1),
        "threshold": doc.get("threshold", 0),
        "window_size": doc.get("window_size", 0),
        "max_attempts": doc.get("max_attempts", 0),
        "bets": doc.get("bets", []),
        "risk": doc.get("risk", 0),
        "X_timestamp": _fmt_ts(doc.get("X_timestamp")),
        "attempts": attempts,
        "won_at_attempt": doc.get("won_at_attempt"),
        "pnl": doc.get("pnl"),
        "created_at": _fmt_ts(doc.get("created_at")),
        "resolved_at": _fmt_ts(doc.get("resolved_at")),
        "config": doc.get("config", {}),
    }


async def _net_for(filt: Dict[str, Any]) -> float:
    """Soma dos pnl (NET) para um filtro — won contribui +2, lost -(risco)."""
    cursor = signals_coll.find(
        {**filt, "status": {"$in": ["won", "lost"]}},
        {"pnl": 1},
    )
    total = 0.0
    async for d in cursor:
        total += float(d.get("pnl") or 0)
    return round(total, 2)


@router.get("/api/hidra-signals")
async def list_signals(
    roulette_id: Optional[str] = Query(None),
    strategy: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    skip: int = Query(0, ge=0),
) -> Dict[str, Any]:
    filt: Dict[str, Any] = {}
    if roulette_id:
        filt["roulette_id"] = roulette_id
    if strategy and strategy != "all":
        filt["strategy"] = strategy
    if status and status != "all":
        filt["status"] = status

    # base_filt ignora status para os contadores agregados
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

    # distribuicao de vitorias por gale + media de gales p/ vencer
    avg_attempts_to_win = 0.0
    distribution_attempts: Dict[int, int] = {}
    won_docs = await signals_coll.find(
        {**base_filt, "status": "won"}, {"won_at_attempt": 1}
    ).to_list(length=None)
    if won_docs:
        total_att = sum(int(d.get("won_at_attempt") or 0) for d in won_docs)
        avg_attempts_to_win = round(total_att / len(won_docs), 2)
        for d in won_docs:
            att = int(d.get("won_at_attempt") or 0)
            distribution_attempts[att] = distribution_attempts.get(att, 0) + 1

    # breakdown por estrategia
    strategy_breakdown: Dict[str, Any] = {}
    for strat in STRATEGY_ORDER:
        s_base = {k: v for k, v in base_filt.items()}
        s_base["strategy"] = strat
        s_won = await signals_coll.count_documents({**s_base, "status": "won"})
        s_lost = await signals_coll.count_documents({**s_base, "status": "lost"})
        s_mon = await signals_coll.count_documents({**s_base, "status": "monitoring"})
        s_res = s_won + s_lost
        s_net = await _net_for(s_base)
        strategy_breakdown[strat] = {
            "name": STRATEGY_NAMES.get(strat, strat),
            "total": s_won + s_lost + s_mon,
            "won": s_won,
            "lost": s_lost,
            "monitoring": s_mon,
            "assertiveness": round(s_won / s_res * 100, 2) if s_res > 0 else 0.0,
            "net": s_net,
        }

    return {
        "filters": {"roulette_id": roulette_id, "strategy": strategy, "status": status},
        "total": total,
        "won": won,
        "lost": lost,
        "monitoring": monitoring,
        "resolved": resolved,
        "assertiveness_pct": assertiveness_pct,
        "net": net,
        "avg_attempts_to_win": avg_attempts_to_win,
        "win_distribution": distribution_attempts,
        "strategy_breakdown": strategy_breakdown,
        "signals": [_serialize(d) for d in docs],
    }


@router.get("/api/hidra-signals/{signal_id}")
async def get_signal(signal_id: str) -> Dict[str, Any]:
    try:
        oid = ObjectId(signal_id)
    except Exception:
        raise HTTPException(status_code=400, detail="signal_id invalido")
    doc = await signals_coll.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="sinal nao encontrado")
    return _serialize(doc)
