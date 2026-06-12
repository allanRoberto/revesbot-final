from __future__ import annotations

import sys
import os
from collections import Counter
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Reutiliza as funções core de previsao_roleta.py sem importar como módulo
# (o arquivo está em apps/api, fora do pacote api)
# ---------------------------------------------------------------------------

WHEEL = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,
         24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]

JANELA = 5
PESOS_ULTIMOS = [3.0, 2.0, 1.0]
PRIOR_GLOBAL = 0.3


def _mapa_sucessores(crono: List[int], janela: int) -> Dict[int, Counter]:
    succ: Dict[int, Counter] = {i: Counter() for i in range(37)}
    n = len(crono)
    for idx in range(n - janela):
        gatilho = crono[idx]
        for j in range(1, janela + 1):
            succ[gatilho][crono[idx + j]] += 1
    return succ


def _scores_base(lista_reversa: List[int], janela: int = JANELA) -> Counter:
    crono = lista_reversa[::-1]
    n = len(crono)
    succ = _mapa_sucessores(crono, janela)
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
    return score


def _gerar_palpites_setores(lista_reversa: List[int], qtd: int = 12,
                             n_arcos: tuple = (2, 3),
                             kernel: tuple = (0.5, 1.0, 0.5),
                             janela: int = JANELA) -> Dict[str, Any]:
    score = _scores_base(lista_reversa, janela)
    pos_score = [0.0] * 37
    for i, num in enumerate(WHEEL):
        s = score[num]
        pos_score[(i - 1) % 37] += kernel[0] * s
        pos_score[i] += kernel[1] * s
        pos_score[(i + 1) % 37] += kernel[2] * s

    def parts(total, k, minimo=3):
        if k == 1:
            if total >= minimo:
                yield (total,)
            return
        for primeiro in range(minimo, total - minimo * (k - 1) + 1):
            for resto in parts(total - primeiro, k - 1, minimo):
                yield (primeiro,) + resto

    def arcos_validos(tamanhos):
        if len(tamanhos) == 1:
            for s0 in range(37):
                yield [(s0, tamanhos[0])]
        elif len(tamanhos) == 2:
            for s0 in range(37):
                for s1 in range(37):
                    a = {(s0 + i) % 37 for i in range(tamanhos[0])}
                    b = {(s1 + i) % 37 for i in range(tamanhos[1])}
                    if not a & b:
                        yield [(s0, tamanhos[0]), (s1, tamanhos[1])]
        else:
            for s0 in range(37):
                for s1 in range(37):
                    for s2 in range(37):
                        a = {(s0 + i) % 37 for i in range(tamanhos[0])}
                        b = {(s1 + i) % 37 for i in range(tamanhos[1])}
                        c = {(s2 + i) % 37 for i in range(tamanhos[2])}
                        if not (a & b or a & c or b & c):
                            yield [(s0, tamanhos[0]), (s1, tamanhos[1]),
                                   (s2, tamanhos[2])]

    melhor = (-1.0, None)
    for k in n_arcos:
        for tamanhos in parts(qtd, k):
            for arcos in arcos_validos(tamanhos):
                posicoes = set()
                for ini, tam in arcos:
                    posicoes |= {(ini + i) % 37 for i in range(tam)}
                total_s = sum(pos_score[p] for p in posicoes)
                if total_s > melhor[0]:
                    melhor = (total_s, arcos)

    _, arcos = melhor
    numeros: List[int] = []
    detalhe: List[List[int]] = []
    for ini, tam in arcos:
        seq = [WHEEL[(ini + i) % 37] for i in range(tam)]
        numeros += seq
        detalhe.append(seq)
    return {"palpites": sorted(numeros), "arcos": detalhe}


# ---------------------------------------------------------------------------
# Configurações fixas de backtest
# ---------------------------------------------------------------------------
CONFIGS = [
    {"label": "8 fichas / 6 tentativas",  "qtd": 8,  "tentativas": 6},
    {"label": "12 fichas / 3 tentativas", "qtd": 12, "tentativas": 3},
    {"label": "18 fichas / 3 tentativas", "qtd": 18, "tentativas": 3},
    {"label": "26 fichas / 1 tentativa",  "qtd": 26, "tentativas": 1},
]

MIN_HISTORY = 100  # mínimo para gerar previsão confiável


def _simulate_pnl(palpites: List[int], future: List[int],
                  tentativas: int) -> Dict[str, Any]:
    """
    Simula P&L para uma entrada.
    Cada rodada aposta 1 ficha em cada número dos palpites.
    Ganho quando acerta: 36 - qtd_apostada_acumulada
    Perda total: qtd * tentativas jogadas
    """
    qtd = len(palpites)
    sugg_set = set(palpites)
    invested = 0.0
    for attempt_idx, number in enumerate(future[:tentativas], start=1):
        invested += qtd
        if number in sugg_set:
            profit = 36.0 - invested
            return {
                "hit": True,
                "hit_attempt": attempt_idx,
                "hit_number": number,
                "profit": round(profit, 2),
                "invested": round(invested, 2),
            }
    return {
        "hit": False,
        "hit_attempt": 0,
        "hit_number": None,
        "profit": round(-invested, 2),
        "invested": round(invested, 2),
    }


async def run_previsao_setores_backtest(
    roulette_id: str,
    limit: int = 2000,
    entries_limit: int = 500,
) -> Dict[str, Any]:
    from api.services.assertiveness_replay import fetch_history_desc

    history_desc = await fetch_history_desc(roulette_id, limit)
    if len(history_desc) < MIN_HISTORY + max(c["tentativas"] for c in CONFIGS):
        return {
            "available": False,
            "error": "Histórico insuficiente.",
            "history_size": len(history_desc),
        }

    chronological = list(reversed(history_desc))
    max_tentativas = max(c["tentativas"] for c in CONFIGS)

    anchor_indexes = list(range(MIN_HISTORY - 1, len(chronological) - max_tentativas))
    if entries_limit > 0 and len(anchor_indexes) > entries_limit:
        anchor_indexes = anchor_indexes[-entries_limit:]

    # Resultados por configuração
    results_by_config: Dict[str, Dict] = {}
    for cfg in CONFIGS:
        results_by_config[cfg["label"]] = {
            "qtd": cfg["qtd"],
            "tentativas": cfg["tentativas"],
            "hits": 0,
            "misses": 0,
            "total_profit": 0.0,
            "total_invested": 0.0,
            "hit_by_attempt": {i: 0 for i in range(1, cfg["tentativas"] + 1)},
            "entries": [],
        }

    for anchor_idx in anchor_indexes:
        context_crono = chronological[: anchor_idx + 1]
        context_desc = list(reversed(context_crono))

        if len(context_desc) < MIN_HISTORY:
            continue

        # Gera palpites com setores (qtd mínimo para o contexto)
        # Usa qtd=8 como base e reutiliza para todas as configs
        try:
            # Para cada config, precisamos de qtds diferentes — gera separado
            future_numbers = chronological[anchor_idx + 1: anchor_idx + 1 + max_tentativas]
            if len(future_numbers) < max_tentativas:
                continue

            for cfg in CONFIGS:
                label = cfg["label"]
                tentativas = cfg["tentativas"]
                qtd = cfg["qtd"]

                res_cfg = results_by_config[label]

                try:
                    pred = _gerar_palpites_setores(context_desc, qtd=qtd)
                except Exception:
                    continue

                palpites = pred["palpites"]
                sim = _simulate_pnl(palpites, future_numbers, tentativas)

                res_cfg["total_invested"] += sim["invested"]
                res_cfg["total_profit"] += sim["profit"]

                entry: Dict[str, Any] = {
                    "anchor": anchor_idx,
                    "context_last": context_crono[-1],
                    "palpites": palpites,
                    "arcos": pred["arcos"],
                    **sim,
                }

                if sim["hit"]:
                    res_cfg["hits"] += 1
                    res_cfg["hit_by_attempt"][sim["hit_attempt"]] += 1
                else:
                    res_cfg["misses"] += 1

                if len(res_cfg["entries"]) < 200:
                    res_cfg["entries"].append(entry)

        except Exception:
            continue

    # Calcula métricas finais
    summary = []
    for cfg in CONFIGS:
        label = cfg["label"]
        r = results_by_config[label]
        total_signals = r["hits"] + r["misses"]
        hit_rate = r["hits"] / total_signals if total_signals else 0.0
        roi = r["total_profit"] / r["total_invested"] if r["total_invested"] > 0 else 0.0

        summary.append({
            "label": label,
            "qtd": r["qtd"],
            "tentativas": r["tentativas"],
            "total_signals": total_signals,
            "hits": r["hits"],
            "misses": r["misses"],
            "hit_rate": round(hit_rate * 100, 2),
            "total_profit": round(r["total_profit"], 2),
            "total_invested": round(r["total_invested"], 2),
            "roi": round(roi * 100, 2),
            "hit_by_attempt": r["hit_by_attempt"],
            "entries": r["entries"],
        })

    return {
        "available": True,
        "roulette_id": roulette_id,
        "history_size": len(history_desc),
        "anchors_evaluated": len(anchor_indexes),
        "configs": summary,
    }
