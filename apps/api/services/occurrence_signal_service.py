from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from pymongo import DESCENDING

from api.core.db import history_coll, history_triplets_coll


SPINS_TO_FETCH = 1000  # suficiente para encontrar 3 ocorrencias anteriores
ZERO_WINDOW = 7
ATTEMPTS = 4
TOP_N = 4


async def precompute_occurrence_signal(
    history: List[int],
    *,
    zero_window: int = ZERO_WINDOW,
    top_n: int = TOP_N,
    positions: int = 3,
) -> Optional[Dict[str, Any]]:
    """Para o padrao 'occurrence_signal' do engine de sugestao.
    Recebe `history` em ordem MAIS RECENTE PRIMEIRO (convencao do engine) e devolve
    {top4, X, trio} se o sinal estiver ativo; None caso nao atenda alguma pre-condicao.
    Faz a query no `history_triplets` em todas as roletas (sem filtro de roleta).
    """
    if positions not in (1, 2, 3):
        positions = 3
    if not history or len(history) < 10:
        return None

    chrono = list(reversed([int(n) for n in history]))  # oldest -> newest
    L = len(chrono) - 1
    X = chrono[L]

    zero_start = max(0, L - zero_window + 1)
    if 0 in chrono[zero_start : L + 1]:
        return None

    prior = [i for i in range(L) if chrono[i] == X]
    if len(prior) < 3:
        return None

    occ_oldest_idx, occ_middle_idx, occ_recent_idx = prior[-3:]
    if occ_oldest_idx == 0 or occ_oldest_idx >= L:
        return None

    prev_n = chrono[occ_oldest_idx - 1]
    next_n = chrono[occ_oldest_idx + 1]
    trio = [prev_n, X, next_n]

    match = {"a": prev_n, "b": X, "c": next_n}
    total_matches = await history_triplets_coll.count_documents(match)
    if total_matches == 0:
        return None

    next_fields = [f"$next{i}" for i in range(1, positions + 1)]
    pipeline = [
        {"$match": match},
        {"$project": {"nums": next_fields}},
        {"$unwind": "$nums"},
        {"$match": {"nums": {"$ne": None, "$gte": 0, "$lte": 36}}},
        {"$group": {"_id": "$nums", "count": {"$sum": 1}}},
        {"$sort": {"count": -1, "_id": 1}},
        {"$limit": max(1, top_n)},
    ]
    rows = [d async for d in history_triplets_coll.aggregate(pipeline)]
    if not rows:
        return None

    top = [int(r["_id"]) for r in rows]

    def window_after(idx: int) -> List[int]:
        out: List[int] = []
        for offset in range(1, 4):
            j = idx + offset
            if j >= L:
                break
            out.append(chrono[j])
        return out

    check_values = window_after(occ_middle_idx) + window_after(occ_recent_idx)
    if any(v in top for v in check_values):
        return None  # top ja apareceu na janela de verificacao -> sinal inativo

    return {
        "precomputed_top4": top,
        "precomputed_X": X,
        "precomputed_trio": trio,
        "precomputed_match_count": total_matches,
    }


def _fmt_ts(ts: Any) -> Optional[str]:
    if ts is None:
        return None
    if hasattr(ts, "isoformat"):
        return ts.isoformat()
    return str(ts)


async def validate_occurrence_signal(roulette_id: str, positions: int = 3) -> Dict[str, Any]:
    """Valida o padrao:
    1. X = ultimo numero da roleta.
    2. Bloqueia se 0 nas ultimas 7 rodadas (incluindo X).
    3. Acha as 3 ocorrencias anteriores de X. A mais antiga vira occ_oldest.
    4. Pega o numero antes (prev) e depois (next) de occ_oldest -> trio [prev, X, next].
    5. Busca history_triplets onde a=prev, b=X, c=next. Soma next1/next2/next3 -> ranking.
    6. Top 4 do ranking.
    7. Janela de verificacao: 3 spins apos occ_middle e 3 apos occ_recent (exclui o proprio X).
       Se algum desses 6 spins tiver um numero do top 4 -> sinal inativo. Senao -> ATIVO.
    8. Aposta: top4 uniao {0} com 4 tentativas.
    """
    if not roulette_id:
        raise ValueError("roulette_id obrigatorio")
    if positions not in (1, 2, 3):
        raise ValueError("positions deve ser 1, 2 ou 3")

    t0 = time.perf_counter()

    docs = await history_coll.find(
        {"roulette_id": roulette_id},
        {"value": 1, "timestamp": 1},
    ).sort("timestamp", DESCENDING).limit(SPINS_TO_FETCH).to_list(length=SPINS_TO_FETCH)

    if not docs:
        return {
            "status": "no_data",
            "roulette_id": roulette_id,
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
        }

    docs.reverse()
    spins = [{"value": int(d["value"]), "timestamp": d["timestamp"]} for d in docs]
    L = len(spins) - 1
    X = spins[L]["value"]
    X_ts = _fmt_ts(spins[L]["timestamp"])

    # Janela do 0
    zero_start = max(0, L - ZERO_WINDOW + 1)
    zero_window = [
        {"index": i, "value": spins[i]["value"], "timestamp": _fmt_ts(spins[i]["timestamp"])}
        for i in range(zero_start, L + 1)
    ]
    has_zero = any(s["value"] == 0 for s in zero_window)

    common: Dict[str, Any] = {
        "roulette_id": roulette_id,
        "positions": positions,
        "X": X,
        "X_timestamp": X_ts,
        "X_index": L,
        "zero_window": zero_window,
        "has_zero_in_last_7": has_zero,
    }

    if has_zero:
        return {
            **common,
            "status": "blocked_by_zero",
            "signal_active": False,
            "signal_reason": "0 apareceu nas ultimas 7 rodadas",
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
        }

    # 3 ocorrencias anteriores de X
    prior_indices = [i for i in range(L) if spins[i]["value"] == X]

    if len(prior_indices) < 3:
        return {
            **common,
            "status": "not_enough_occurrences",
            "signal_active": False,
            "signal_reason": f"so foram encontradas {len(prior_indices)} ocorrencias anteriores de X={X} (precisa de 3)",
            "prior_occurrences_count": len(prior_indices),
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
        }

    last3 = prior_indices[-3:]
    occ_oldest_idx = last3[0]
    occ_middle_idx = last3[1]
    occ_recent_idx = last3[2]

    occurrences = {
        "oldest": {"value": X, "index": occ_oldest_idx, "timestamp": _fmt_ts(spins[occ_oldest_idx]["timestamp"])},
        "middle": {"value": X, "index": occ_middle_idx, "timestamp": _fmt_ts(spins[occ_middle_idx]["timestamp"])},
        "recent": {"value": X, "index": occ_recent_idx, "timestamp": _fmt_ts(spins[occ_recent_idx]["timestamp"])},
    }

    if occ_oldest_idx == 0 or occ_oldest_idx >= L:
        return {
            **common,
            "status": "no_context_at_oldest",
            "signal_active": False,
            "signal_reason": "nao ha numeros antes/depois da occ_oldest",
            "occurrences": occurrences,
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
        }

    prev_n = spins[occ_oldest_idx - 1]["value"]
    next_n = spins[occ_oldest_idx + 1]["value"]
    context_around_oldest = {
        "prev": {"value": prev_n, "index": occ_oldest_idx - 1, "timestamp": _fmt_ts(spins[occ_oldest_idx - 1]["timestamp"])},
        "X": {"value": X, "index": occ_oldest_idx, "timestamp": _fmt_ts(spins[occ_oldest_idx]["timestamp"])},
        "next": {"value": next_n, "index": occ_oldest_idx + 1, "timestamp": _fmt_ts(spins[occ_oldest_idx + 1]["timestamp"])},
    }

    # Busca em history_triplets
    match = {"a": prev_n, "b": X, "c": next_n}
    total_matches = await history_triplets_coll.count_documents(match)

    ranking_rows: List[Dict[str, Any]] = []
    top_numbers: List[int] = []

    next_fields = [f"$next{i}" for i in range(1, positions + 1)]
    if total_matches > 0:
        pipeline = [
            {"$match": match},
            {"$project": {"nums": next_fields}},
            {"$unwind": "$nums"},
            {"$match": {"nums": {"$ne": None, "$gte": 0, "$lte": 36}}},
            {"$group": {"_id": "$nums", "count": {"$sum": 1}}},
            {"$sort": {"count": -1, "_id": 1}},
        ]
        rows = [d async for d in history_triplets_coll.aggregate(pipeline)]
        total_appearances = sum(int(r["count"]) for r in rows) or 1
        ranking_rows = [
            {
                "number": int(r["_id"]),
                "count": int(r["count"]),
                "percentage": round(int(r["count"]) / total_appearances * 100, 2),
            }
            for r in rows
        ]
        top_numbers = [r["number"] for r in ranking_rows[:TOP_N]]

    # Janela de verificacao: 3 spins apos cada uma das 2 ocorrencias intermediarias,
    # excluindo o proprio X (indice L).
    def window_after(idx: int) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for offset in range(1, 4):
            j = idx + offset
            if j >= L:
                break
            out.append({
                "position": offset,
                "index": j,
                "value": spins[j]["value"],
                "timestamp": _fmt_ts(spins[j]["timestamp"]),
                "is_hit": spins[j]["value"] in top_numbers,
            })
        return out

    middle_window = window_after(occ_middle_idx)
    recent_window = window_after(occ_recent_idx)
    hits = [w["value"] for w in (middle_window + recent_window) if w["is_hit"]]

    if not top_numbers:
        signal_active = False
        signal_reason = "Sem historico para o trio [prev,X,next] em history_triplets"
    elif hits:
        signal_active = False
        signal_reason = f"Top 4 ({top_numbers}) ja apareceu na janela de verificacao: {hits}"
    else:
        signal_active = True
        signal_reason = "Janela de verificacao limpa, sinal ativo"

    bet_numbers = sorted(set(top_numbers + [0]))

    return {
        **common,
        "status": "active" if signal_active else "inactive",
        "signal_active": signal_active,
        "signal_reason": signal_reason,
        "occurrences": occurrences,
        "context_around_oldest": context_around_oldest,
        "triplet": [prev_n, X, next_n],
        "triplet_match_count": total_matches,
        "ranking": ranking_rows[:10],
        "top4": top_numbers,
        "check_windows": {
            "middle": middle_window,
            "recent": recent_window,
        },
        "hits_in_check_window": hits,
        "bet_numbers": bet_numbers,
        "attempts": ATTEMPTS,
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
    }
