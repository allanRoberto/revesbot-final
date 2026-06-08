from __future__ import annotations

import logging
from typing import Dict, List

from fastapi import APIRouter, Query
from pymongo import DESCENDING, ASCENDING

from api.core.db import history_coll
# Reaproveita as constantes de relações já definidas no analisador de puxadas
from api.routes.analise_puxadas import WHEEL, POS, ESP

router = APIRouter(prefix="/multi-pivo")

# Configuração fixa da estratégia (confirmada com o usuário)
N_PIVOS = 5        # os 5 últimos números sorteados
N_OCORRENCIAS = 5  # ocorrências passadas por pivô
N_ANTES = 2        # números imediatamente anteriores que entram na base
N_DEPOIS = 4       # números à frente (apenas salvos, validação/uso futuro)


def expand_base(n: int) -> List[Dict]:
    """
    Expande um número-base nas relações usadas na lista final:
    vizinho (1 de cada lado), espelho e sequência (n-1, n+1).
    Retorna lista ordenada de {v, rel}, sem repetir o próprio número.
    """
    out: List[Dict] = []
    seen = set()

    def add(x: int, rel: str):
        if 0 <= x <= 36 and x != n and (x, rel) not in seen:
            seen.add((x, rel))
            out.append({'v': x, 'rel': rel})

    i = POS[n]
    add(WHEEL[(i - 1) % 37], 'vizinho')
    add(WHEEL[(i + 1) % 37], 'vizinho')
    if n in ESP:
        add(ESP[n], 'espelho')
    if n > 0:
        add(n - 1, 'sequencia')
    if n < 36:
        add(n + 1, 'sequencia')
    return out


async def _analisar_pivo(mesa: str, pivo: int, ts_pivo, ocorrencias: int,
                         incluir_frente: int = 0) -> Dict:
    """
    Para um pivô ancorado em ts_pivo, busca N ocorrências anteriores e monta:
      - ocorrencias: trilha [-2,-1] → PIVÔ → [+1..+4] de cada ocorrência
      - lista_final: base (2 de trás) + expansões, deduplicado, em ordem de ocorrência
        Se incluir_frente > 0, também adiciona os N primeiros números à frente
        (pos +1..) de cada ocorrência + expansões.
    """
    coll = history_coll

    # 1) Timestamps das ocorrências ANTERIORES do pivô (não conta a posição atual)
    occ_docs = await coll.find(
        {'roulette_id': mesa, 'value': pivo, 'timestamp': {'$lt': ts_pivo}},
        {'timestamp': 1, '_id': 0}
    ).sort('timestamp', DESCENDING).limit(ocorrencias).to_list(length=ocorrencias)

    ocorrencias_out: List[Dict] = []
    # lista_final deduplicada por número, preservando ordem de 1ª aparição
    final_order: List[int] = []
    final_map: Dict[int, Dict] = {}

    def push_final(v: int, rel: str):
        if v not in final_map:
            final_map[v] = {'v': v, 'rels': [rel], 'peso': 1}
            final_order.append(v)
        else:
            entry = final_map[v]
            entry['peso'] += 1
            if rel not in entry['rels']:
                entry['rels'].append(rel)

    for i, occ_doc in enumerate(occ_docs):
        ts = occ_doc['timestamp']

        # 2 imediatamente antes (mais próximo primeiro: -1, -2)
        before_docs = await coll.find(
            {'roulette_id': mesa, 'timestamp': {'$lt': ts}},
            {'value': 1, 'timestamp': 1, '_id': 0}
        ).sort('timestamp', DESCENDING).limit(N_ANTES).to_list(length=N_ANTES)

        # até 4 à frente (mais próximo primeiro: +1..+4) — apenas salvos
        after_docs = await coll.find(
            {'roulette_id': mesa, 'timestamp': {'$gt': ts}},
            {'value': 1, 'timestamp': 1, '_id': 0}
        ).sort('timestamp', ASCENDING).limit(N_DEPOIS).to_list(length=N_DEPOIS)

        antes = [{'pos': -(j + 1), 'v': d['value']} for j, d in enumerate(before_docs)]
        depois = [{'pos': (j + 1), 'v': d['value']} for j, d in enumerate(after_docs)]

        # Base = os 2 de trás (pos -1 antes de -2); cada base entra na lista final
        # junto das suas expansões.
        base_out: List[Dict] = []
        for item in antes:
            v = item['v']
            push_final(v, 'base')
            expan = expand_base(v)
            for e in expan:
                push_final(e['v'], e['rel'])
            base_out.append({'pos': item['pos'], 'v': v, 'expansao': expan})

        # Base à FRENTE: os N primeiros números à frente (pos +1..) também entram
        # na lista final quando incluir_frente > 0.
        base_frente_out: List[Dict] = []
        for item in depois[:incluir_frente]:
            v = item['v']
            push_final(v, 'frente')
            expan = expand_base(v)
            for e in expan:
                push_final(e['v'], e['rel'])
            base_frente_out.append({'pos': item['pos'], 'v': v, 'expansao': expan})

        ocorrencias_out.append({
            'occ_idx': i,
            'timestamp': ts.isoformat(),
            'antes': antes,
            'depois': depois,
            'base': base_out,
            'base_frente': base_frente_out,
        })

    lista_final = [final_map[v] for v in final_order]

    return {
        'pivo': pivo,
        'ts': ts_pivo.isoformat(),
        'ocorrencias': ocorrencias_out,
        'lista_final': lista_final,
        'incluir_frente': incluir_frente,
    }


@router.get("/api/analise")
async def api_analise(
    mesa: str = Query('', description="ID da roleta"),
    pivos: int = Query(N_PIVOS, ge=1, le=10),
    ocorrencias: int = Query(N_OCORRENCIAS, ge=1, le=10),
    incluir_frente: int = Query(0, ge=0, le=4,
                                description="Qtde de números à frente que também entram na lista"),
):
    """
    Análise multi-pivô: para os N últimos números sorteados, monta a lista final
    (base + vizinho/espelho/sequência) de cada um e cruza as listas para ver
    quais números mais se repetem entre elas. Se incluir_frente > 0, os N primeiros
    números à frente de cada ocorrência também alimentam a lista.
    """
    try:
        # Últimos N sorteios = pivôs (mais recente primeiro)
        pivot_docs = await history_coll.find(
            {'roulette_id': mesa},
            {'value': 1, 'timestamp': 1, '_id': 0}
        ).sort('timestamp', DESCENDING).limit(pivos).to_list(length=pivos)

        pivos_out: List[Dict] = []
        for doc in pivot_docs:
            res = await _analisar_pivo(mesa, doc['value'], doc['timestamp'],
                                       ocorrencias, incluir_frente)
            pivos_out.append(res)

        # Agregação: quantas das listas finais contêm cada número + total de aparições
        listas_count = [0] * 37
        total_count = [0] * 37
        for p in pivos_out:
            for entry in p['lista_final']:
                n = entry['v']
                listas_count[n] += 1
                total_count[n] += entry['peso']

        agregado = [
            {'n': n, 'listas': listas_count[n], 'total': total_count[n]}
            for n in range(37) if listas_count[n] > 0
        ]
        agregado.sort(key=lambda x: (-x['listas'], -x['total'], x['n']))

        return {'pivos': pivos_out, 'agregado': agregado}
    except Exception as e:
        logging.error(f"Erro na análise multi-pivô: {e}")
        return {'pivos': [], 'agregado': [], 'erro': str(e)}
