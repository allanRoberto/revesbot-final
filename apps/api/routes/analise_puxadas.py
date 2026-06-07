from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Query
from pydantic import BaseModel
from pymongo import DESCENDING, ASCENDING

from api.core.db import history_coll

router = APIRouter(prefix="/puxadas")

# ── Roulette relationship constants ──────────────────────────────────────────
WHEEL = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23,
         10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26]
POS = {n: i for i, n in enumerate(WHEEL)}
ESP = {1: 10, 10: 1, 2: 20, 20: 2, 3: 30, 30: 3, 6: 9, 9: 6,
       12: 21, 21: 12, 13: 31, 31: 13, 16: 19, 19: 16, 23: 32, 32: 23, 26: 29, 29: 26}
TWINS = {11, 22, 33}
CAV = {**{d: 'A' for d in (0, 3, 6, 9)}, **{d: 'B' for d in (1, 4, 7)}, **{d: 'C' for d in (2, 5, 8)}}


def droot(n: int) -> int:
    if n == 0:
        return 0
    r = n % 9
    return 9 if r == 0 else r


def get_relatives(n: int) -> Dict[int, List[str]]:
    rels: Dict[int, List[str]] = {}

    def add(x: int, r: str):
        if 0 <= x <= 36 and x != n:
            rels.setdefault(x, []).append(r)

    i = POS[n]
    add(WHEEL[(i - 1) % 37], 'vizinho')
    add(WHEEL[(i + 1) % 37], 'vizinho')
    if n in ESP:
        add(ESP[n], 'espelho')
    if n > 0:
        add(n - 1, 'sequencia')
    if n < 36:
        add(n + 1, 'sequencia')
    dr = droot(n)
    if dr:
        for x in range(37):
            if x != n and droot(x) == dr:
                add(x, 'soma')
    t = n % 10
    for x in range(37):
        if x != n and x % 10 == t:
            add(x, 'terminal')
    c = CAV[n % 10]
    for x in range(37):
        if x != n and CAV[x % 10] == c:
            add(x, 'cavalo')
    if n in TWINS:
        for tw in TWINS:
            if tw != n:
                add(tw, 'gemeo')
    return rels


# ── API Endpoints ─────────────────────────────────────────────────────────────

@router.get("/api/mesas")
async def api_mesas():
    """Lista todas as mesas disponíveis no banco."""
    try:
        ids = await history_coll.distinct('roulette_id')
        return [
            {
                'id': r,
                'name': r.replace('pragmatic-', '').replace('playtech-', '')
                         .replace('evolution-', '').replace('-', ' ').title()
            }
            for r in sorted(ids) if not r.startswith('_')
        ]
    except Exception as e:
        logging.error(f"Erro ao listar mesas: {e}")
        return []


@router.get("/api/historia")
async def api_historia(
    mesa: str = Query('', description="ID da roleta"),
    limit: int = Query(200, ge=1, le=500)
):
    """Retorna os últimos N giros de uma mesa (mais recente primeiro)."""
    try:
        docs = await history_coll.find(
            {'roulette_id': mesa},
            {'value': 1, 'timestamp': 1, '_id': 0}
        ).sort('timestamp', DESCENDING).limit(limit).to_list(length=limit)
        return [{'v': d['value'], 't': d['timestamp'].isoformat()} for d in docs]
    except Exception as e:
        logging.error(f"Erro ao buscar história: {e}")
        return []


@router.get("/api/ocorrencias")
async def api_ocorrencias(
    mesa: str = Query('', description="ID da roleta"),
    numero: int = Query(0, ge=0, le=36),
    ocorrencias: int = Query(5, ge=1, le=10),
    antes: int = Query(3, ge=1, le=6),
    depois: int = Query(3, ge=1, le=6),
):
    """
    Para um número alvo, retorna as N ocorrências mais recentes com o contexto
    (X giros antes e Y giros depois de cada ocorrência).
    Queries otimizadas: 1 busca de timestamps + 2 por ocorrência = rápido.
    """
    try:
        coll = history_coll
        trel = get_relatives(numero)

        # 1) Busca só os timestamps das N ocorrências (query com índice)
        occ_docs = await coll.find(
            {'roulette_id': mesa, 'value': numero},
            {'timestamp': 1, '_id': 0}
        ).sort('timestamp', DESCENDING).limit(ocorrencias).to_list(length=ocorrencias)

        result = []
        for i, occ_doc in enumerate(occ_docs):
            ts = occ_doc['timestamp']

            # 2) Contexto ANTES: documentos com timestamp < ts (mais próximos primeiro)
            before_docs = await coll.find(
                {'roulette_id': mesa, 'timestamp': {'$lt': ts}},
                {'value': 1, 'timestamp': 1, '_id': 0}
            ).sort('timestamp', DESCENDING).limit(antes).to_list(length=antes)

            # 3) Contexto DEPOIS: documentos com timestamp > ts (mais próximos primeiro)
            after_docs = await coll.find(
                {'roulette_id': mesa, 'timestamp': {'$gt': ts}},
                {'value': 1, 'timestamp': 1, '_id': 0}
            ).sort('timestamp', ASCENDING).limit(depois).to_list(length=depois)

            ctx_antes = [
                {'pos': -(j + 1), 'v': d['value'], 't': d['timestamp'].isoformat(),
                 'rels': trel.get(d['value'], [])}
                for j, d in enumerate(before_docs)
            ]
            ctx_depois = [
                {'pos': (j + 1), 'v': d['value'], 't': d['timestamp'].isoformat(),
                 'rels': trel.get(d['value'], [])}
                for j, d in enumerate(after_docs)
            ]

            result.append({
                'occ_idx': i,
                'target': numero,
                'timestamp': ts.isoformat(),
                'antes': ctx_antes,
                'depois': ctx_depois,
            })

        return result
    except Exception as e:
        logging.error(f"Erro ao buscar ocorrências: {e}")
        return []


class RankingRequest(BaseModel):
    ocorrencias: List[Dict[str, Any]]
    occ_weights: List[float]
    before_weights: Dict[str, float]
    after_weights: Dict[str, float]
    sub_weights: Dict[str, float]


@router.post("/api/ranking")
async def api_ranking(body: RankingRequest):
    """
    Calcula o ranking ponderado de tendência a partir das ocorrências e pesos fornecidos.
    """
    scores = [0.0] * 37

    def apply(n: int, w: float):
        scores[n] += w
        for rn, rts in get_relatives(n).items():
            for rt in rts:
                scores[rn] += w * float(body.sub_weights.get(rt, 0))

    for oi, occ in enumerate(body.ocorrencias):
        if oi >= len(body.occ_weights):
            break
        wo = float(body.occ_weights[oi])
        for item in occ.get('antes', []):
            wp = float(body.before_weights.get(str(item['pos']), 0))
            if wo * wp > 0:
                apply(item['v'], wo * wp)
        for item in occ.get('depois', []):
            wp = float(body.after_weights.get(str(item['pos']), 0))
            if wo * wp > 0:
                apply(item['v'], wo * wp)

    mx = max(scores) or 1
    ranked = sorted(range(37), key=lambda x: -scores[x])
    return {
        'ranking': ranked[:12],
        'all_scores': [
            {'n': n, 's': round(scores[n], 2), 'pct': round(scores[n] / mx * 100, 1)}
            for n in ranked
        ]
    }
