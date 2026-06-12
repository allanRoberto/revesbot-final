from __future__ import annotations

import asyncio
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

WHEEL = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,
         24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]

JANELA = 5
PESOS_ULTIMOS = [3.0, 2.0, 1.0]
PRIOR_GLOBAL = 0.3

CONFIGS = [
    {"label": "8 fichas / 6 tentativas",  "qtd": 8,  "tentativas": 6},
    {"label": "12 fichas / 3 tentativas", "qtd": 12, "tentativas": 3},
    {"label": "18 fichas / 3 tentativas", "qtd": 18, "tentativas": 3},
    {"label": "26 fichas / 1 tentativa",  "qtd": 26, "tentativas": 1},
]

MIN_HISTORY = 100
_EXECUTOR = ThreadPoolExecutor(max_workers=2)


# ---------------------------------------------------------------------------
# Score computation
# ---------------------------------------------------------------------------

def _mapa_sucessores(crono: List[int], janela: int) -> Dict[int, Counter]:
    succ: Dict[int, Counter] = {i: Counter() for i in range(37)}
    n = len(crono)
    for idx in range(n - janela):
        gatilho = crono[idx]
        for j in range(1, janela + 1):
            succ[gatilho][crono[idx + j]] += 1
    return succ


def _compute_pos_score(lista_reversa: List[int],
                       kernel: tuple = (0.5, 1.0, 0.5)) -> List[float]:
    crono = lista_reversa[::-1]
    n = len(crono)
    succ = _mapa_sucessores(crono, JANELA)
    score: Counter = Counter()
    ultimos = crono[-len(PESOS_ULTIMOS):][::-1]
    for num, peso in zip(ultimos, PESOS_ULTIMOS):
        total = sum(succ[num].values())
        if total:
            for cand, c in succ[num].items():
                score[cand] += peso * c / total
    freq = Counter(crono)
    for cand in range(37):
        score[cand] += PRIOR_GLOBAL * freq[cand] / n

    pos_score = [0.0] * 37
    for i, num in enumerate(WHEEL):
        s = score[num]
        pos_score[(i - 1) % 37] += kernel[0] * s
        pos_score[i] += kernel[1] * s
        pos_score[(i + 1) % 37] += kernel[2] * s
    return pos_score


# ---------------------------------------------------------------------------
# Greedy 2-arc selection  O(37² × qtd)
# ---------------------------------------------------------------------------

def _arc_score(pos_score: List[float], ini: int, tam: int) -> float:
    return sum(pos_score[(ini + i) % 37] for i in range(tam))


def _best_two_arcs(pos_score: List[float], qtd: int) -> Dict[str, Any]:
    best = (-1.0, None)
    for tam1 in range(3, qtd - 2):
        tam2 = qtd - tam1
        if tam2 < 3:
            continue
        for ini1 in range(37):
            s1 = _arc_score(pos_score, ini1, tam1)
            occupied = {(ini1 + i) % 37 for i in range(tam1)}
            best2_score, best2_ini = -1.0, -1
            for ini2 in range(37):
                if any((ini2 + i) % 37 in occupied for i in range(tam2)):
                    continue
                s2 = _arc_score(pos_score, ini2, tam2)
                if s2 > best2_score:
                    best2_score, best2_ini = s2, ini2
            if best2_ini == -1:
                continue
            total_s = s1 + best2_score
            if total_s > best[0]:
                best = (total_s, [(ini1, tam1), (best2_ini, tam2)])

    _, arcos = best
    numeros: List[int] = []
    detalhe: List[List[int]] = []
    for ini, tam in arcos:
        seq = [WHEEL[(ini + i) % 37] for i in range(tam)]
        numeros += seq
        detalhe.append(seq)
    return {"palpites": sorted(numeros), "arcos": detalhe}


# ---------------------------------------------------------------------------
# P&L simulation
# ---------------------------------------------------------------------------

def _simulate_pnl(palpites: List[int], future: List[int],
                  tentativas: int) -> Dict[str, Any]:
    qtd = len(palpites)
    sugg_set = set(palpites)
    invested = 0.0
    for attempt_idx, number in enumerate(future[:tentativas], start=1):
        invested += qtd
        if number in sugg_set:
            return {
                "hit": True,
                "hit_attempt": attempt_idx,
                "hit_number": number,
                "profit": round(36.0 - invested, 2),
                "invested": round(invested, 2),
            }
    return {
        "hit": False, "hit_attempt": 0, "hit_number": None,
        "profit": round(-invested, 2), "invested": round(invested, 2),
    }


# ---------------------------------------------------------------------------
# Walk-forward backtest (runs in thread pool to avoid blocking event loop)
# ---------------------------------------------------------------------------

def _run_backtest_sync(chronological: List[int], anchor_indexes: List[int]) -> List[Dict]:
    """CPU-bound walk-forward — chamado via executor."""
    max_tentativas = max(c["tentativas"] for c in CONFIGS)

    results: Dict[str, Dict] = {
        cfg["label"]: {
            "qtd": cfg["qtd"], "tentativas": cfg["tentativas"],
            "hits": 0, "misses": 0,
            "total_profit": 0.0, "total_invested": 0.0,
            "hit_by_attempt": {i: 0 for i in range(1, cfg["tentativas"] + 1)},
            "entries": [],
        }
        for cfg in CONFIGS
    }

    for anchor_idx in anchor_indexes:
        context_crono = chronological[: anchor_idx + 1]
        if len(context_crono) < MIN_HISTORY:
            continue

        future_numbers = chronological[anchor_idx + 1: anchor_idx + 1 + max_tentativas]
        if len(future_numbers) < max_tentativas:
            continue

        context_desc = list(reversed(context_crono))
        try:
            pos_score = _compute_pos_score(context_desc)
        except Exception:
            continue

        for cfg in CONFIGS:
            label = cfg["label"]
            try:
                pred = _best_two_arcs(pos_score, cfg["qtd"])
            except Exception:
                continue

            palpites = pred["palpites"]
            sim = _simulate_pnl(palpites, future_numbers, cfg["tentativas"])
            r = results[label]
            r["total_invested"] += sim["invested"]
            r["total_profit"] += sim["profit"]

            if sim["hit"]:
                r["hits"] += 1
                r["hit_by_attempt"][sim["hit_attempt"]] += 1
            else:
                r["misses"] += 1

            if len(r["entries"]) < 200:
                r["entries"].append({
                    "anchor": anchor_idx,
                    "context_last": context_crono[-1],
                    "palpites": palpites,
                    "arcos": pred["arcos"],
                    **sim,
                })

    summary = []
    for cfg in CONFIGS:
        label = cfg["label"]
        r = results[label]
        total = r["hits"] + r["misses"]
        hit_rate = r["hits"] / total if total else 0.0
        roi = r["total_profit"] / r["total_invested"] if r["total_invested"] > 0 else 0.0
        summary.append({
            "label": label,
            "qtd": r["qtd"],
            "tentativas": r["tentativas"],
            "total_signals": total,
            "hits": r["hits"],
            "misses": r["misses"],
            "hit_rate": round(hit_rate * 100, 2),
            "total_profit": round(r["total_profit"], 2),
            "total_invested": round(r["total_invested"], 2),
            "roi": round(roi * 100, 2),
            "hit_by_attempt": r["hit_by_attempt"],
            "entries": r["entries"],
        })
    return summary


async def run_previsao_setores_backtest(
    roulette_id: str,
    limit: int = 2000,
    entries_limit: int = 300,
) -> Dict[str, Any]:
    from api.services.assertiveness_replay import fetch_history_desc

    history_desc = await fetch_history_desc(roulette_id, limit)
    max_tent = max(c["tentativas"] for c in CONFIGS)
    if len(history_desc) < MIN_HISTORY + max_tent:
        return {"available": False, "error": "Histórico insuficiente.",
                "history_size": len(history_desc)}

    chronological = list(reversed(history_desc))
    anchor_indexes = list(range(MIN_HISTORY - 1, len(chronological) - max_tent))
    if entries_limit > 0 and len(anchor_indexes) > entries_limit:
        anchor_indexes = anchor_indexes[-entries_limit:]

    loop = asyncio.get_event_loop()
    configs = await loop.run_in_executor(
        _EXECUTOR, _run_backtest_sync, chronological, anchor_indexes
    )

    return {
        "available": True,
        "roulette_id": roulette_id,
        "history_size": len(history_desc),
        "anchors_evaluated": len(anchor_indexes),
        "configs": configs,
    }
