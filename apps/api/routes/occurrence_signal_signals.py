from __future__ import annotations

from datetime import timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query

from api.core.db import mongo_db

router = APIRouter()
signals_coll = mongo_db["occurrence_signal_signals"]
SNAPSHOT_DEFAULT = "occurrence_signal_signals_snapshot_20260521"


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
    pre_window_ts_raw = doc.get("pre_window_ts") or []
    pre_window_ts = [_fmt_ts(t) for t in pre_window_ts_raw]
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
        "pre_window":          doc.get("pre_window") or [],
        "pre_window_ts":       pre_window_ts,
        "inversion_paid_before": bool(doc.get("inversion_paid_before", False)),
        "recent3_validation":  doc.get("recent3_validation") or {},
        "attempts":            attempts,
        "post_attempts":       post_attempts,
        "won_at_attempt":      doc.get("won_at_attempt"),
        "needs_post_track":    bool(doc.get("needs_post_track")),
        "created_at":          _fmt_ts(doc.get("created_at")),
        "resolved_at":         _fmt_ts(doc.get("resolved_at")),
        "config":              doc.get("config", {}),
        "source":              doc.get("__source", "live"),
    }


def _parse_confirmers(raw: Optional[str]) -> Optional[List[int]]:
    if not raw:
        return None
    out: List[int] = []
    for tok in raw.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            n = int(tok)
            if 0 <= n <= 4:
                out.append(n)
        except ValueError:
            pass
    return out if out else None


@router.get("/api/occurrence-signal-signals")
async def list_signals(
    roulette_id: Optional[str] = Query(None),
    status: Optional[str]      = Query(None),
    limit:  int                = Query(50, ge=1, le=500),
    skip:   int                = Query(0, ge=0),
    include_snapshot: bool     = Query(True, description="Inclui a colecao de snapshot na busca"),
    snapshot:        str       = Query(SNAPSHOT_DEFAULT, description="Nome da colecao de snapshot"),
    confirmers: Optional[str]  = Query(None, description="Classes de confirmadores recent3 separadas por virgula, ex: '3,4'"),
) -> Dict[str, Any]:
    # Marcadores de origem para o frontend (evita perder informacao apos o union)
    src_live = [{"$addFields": {"__source": "live"}}]
    src_snap = [
        {"$addFields": {"__source": "snapshot"}},
    ]

    base_match: Dict[str, Any] = {}
    if roulette_id:
        base_match["roulette_id"] = roulette_id

    full_match = dict(base_match)
    if status and status != "all":
        full_match["status"] = status

    confirmers_list = _parse_confirmers(confirmers)
    confirmers_match: Dict[str, Any] = {}
    if confirmers_list is not None:
        confirmers_match = {"recent3_validation.confirmers_count": {"$in": confirmers_list}}

    # Pipeline base que une live + snapshot e aplica filtros que valem para tudo
    union_prefix: List[Dict[str, Any]] = list(src_live)
    if include_snapshot and snapshot:
        union_prefix.append({
            "$unionWith": {
                "coll": snapshot,
                "pipeline": src_snap,
            }
        })

    # ---- Aggregate de stats (sem filtro de status, conta tudo da uniao) ----
    stats_pipeline = list(union_prefix)
    if base_match:
        stats_pipeline.append({"$match": base_match})
    if confirmers_match:
        stats_pipeline.append({"$match": confirmers_match})
    stats_pipeline.append({"$facet": {
        "total":            [{"$count": "n"}],
        "won":              [{"$match": {"status": "won"}}, {"$count": "n"}],
        "lost":             [{"$match": {"status": "lost"}}, {"$count": "n"}],
        "monitoring":       [{"$match": {"status": "monitoring"}}, {"$count": "n"}],
        "inversion_paid":   [{"$match": {"inversion_paid_before": True}}, {"$count": "n"}],
        "win_dist": [
            {"$match": {"status": "won"}},
            {"$group": {
                "_id": "$won_at_attempt",
                "n": {"$sum": 1},
                "total_att": {"$sum": "$won_at_attempt"},
            }},
        ],
        "by_source": [
            {"$group": {"_id": "$__source", "n": {"$sum": 1}}},
        ],
        "by_confclass": [
            {"$group": {
                "_id": {"$ifNull": ["$recent3_validation.confirmers_count", 0]},
                "n": {"$sum": 1},
            }},
        ],
    }})

    stats_docs = await signals_coll.aggregate(stats_pipeline, allowDiskUse=True).to_list(length=1)
    facet = stats_docs[0] if stats_docs else {}

    def _facet_count(key: str) -> int:
        arr = facet.get(key) or []
        if arr and isinstance(arr, list) and arr[0].get("n") is not None:
            return int(arr[0]["n"])
        return 0

    total_count        = _facet_count("total")
    won_count          = _facet_count("won")
    lost_count         = _facet_count("lost")
    monitoring_count   = _facet_count("monitoring")
    inversion_paid     = _facet_count("inversion_paid")

    # win distribution + avg attempts
    distribution_attempts: Dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0}
    total_attempts_sum = 0
    win_dist_rows = facet.get("win_dist") or []
    for row in win_dist_rows:
        k = row.get("_id")
        n = int(row.get("n", 0))
        if isinstance(k, int) and k in distribution_attempts:
            distribution_attempts[k] += n
        total_attempts_sum += int(row.get("total_att", 0))
    avg_attempts_to_win = round(total_attempts_sum / won_count, 2) if won_count else 0.0

    by_source = {row["_id"]: int(row.get("n", 0)) for row in (facet.get("by_source") or []) if row.get("_id")}
    by_confclass: Dict[int, int] = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
    for row in (facet.get("by_confclass") or []):
        k = row.get("_id")
        if isinstance(k, int) and 0 <= k <= 4:
            by_confclass[k] += int(row.get("n", 0))

    resolved = won_count + lost_count
    assertiveness_pct = round(won_count / resolved * 100, 2) if resolved > 0 else 0.0
    inversion_pay_rate = round(inversion_paid / total_count * 100, 2) if total_count > 0 else 0.0

    # ---- Aggregate da pagina (com filtro de status para visualizacao) ----
    page_pipeline = list(union_prefix)
    page_match = {**base_match}
    if status and status != "all":
        page_match["status"] = status
    if page_match:
        page_pipeline.append({"$match": page_match})
    if confirmers_match:
        page_pipeline.append({"$match": confirmers_match})
    page_pipeline.extend([
        {"$sort": {"created_at": -1}},
        {"$skip": int(skip)},
        {"$limit": int(limit)},
    ])
    docs = await signals_coll.aggregate(page_pipeline, allowDiskUse=True).to_list(length=limit)

    # Total filtrado (para paginacao)
    if status and status != "all":
        filtered_total = won_count if status == "won" else lost_count if status == "lost" else monitoring_count
    else:
        filtered_total = total_count

    return {
        "filters": {
            "roulette_id": roulette_id,
            "status": status,
            "include_snapshot": include_snapshot,
            "confirmers": confirmers_list,
        },
        "pagination": {
            "skip": skip,
            "limit": limit,
            "filtered_total": filtered_total,
            "has_more": (skip + len(docs)) < filtered_total,
        },
        "total":             total_count,
        "won":               won_count,
        "lost":              lost_count,
        "monitoring":        monitoring_count,
        "resolved":          resolved,
        "assertiveness_pct": assertiveness_pct,
        "avg_attempts_to_win": avg_attempts_to_win,
        "win_distribution":  distribution_attempts,
        "inversion": {
            "paid":     inversion_paid,
            "pending":  0,
            "pay_rate": inversion_pay_rate,
        },
        "by_source":   by_source,
        "by_confclass": by_confclass,
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
        # tenta no snapshot
        doc = await mongo_db[SNAPSHOT_DEFAULT].find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="sinal nao encontrado")
    return _serialize(doc)
