from __future__ import annotations

import time
from collections import Counter
from itertools import permutations
from typing import Any, Dict, List, Optional

from api.core.db import history_triplets_coll
from api.services.base_suggestion import MIRROR_MAP, WHEEL_ORDER, WHEEL_INDEX


# Ordem completa do esquema do history_triplets (9 posicoes por documento).
# Quando o usuario preenche k campos (2..6), casamos os k primeiros e fazemos
# o ranking nas posicoes seguintes (1..horizonte, limitado a 9-k posicoes).
SCHEMA_FIELDS: List[str] = [
    "prev_3", "prev_2", "prev_1", "a", "b", "c", "next1", "next2", "next3",
]
# Mantido por compatibilidade: as k+1 primeiras posicoes do esquema.
DB_FIELD_SEQ: List[str] = SCHEMA_FIELDS[:7]
VALID_MODES = {"exato", "vizinhos", "sequencia", "espelho", "soma"}


def _digit_sum(n: int) -> int:
    return sum(int(d) for d in str(abs(int(n))))


def candidates_for(value: int, modes: List[str]) -> List[int]:
    """Retorna os candidatos de busca para um campo unindo todos os modos selecionados.
    Cada modo contribui apenas com seus proprios numeros derivados; o numero digitado
    so entra se 'exato' estiver na lista. Lista vazia -> ['exato'] por seguranca."""
    n = int(value)
    cleaned = [m for m in (modes or []) if m in VALID_MODES]
    if not cleaned:
        cleaned = ["exato"]
    s: set = set()
    for mode in cleaned:
        if mode == "exato":
            s.add(n)
        elif mode == "vizinhos":
            if n in WHEEL_INDEX:
                idx = WHEEL_INDEX[n]
                s.add(WHEEL_ORDER[(idx - 1) % len(WHEEL_ORDER)])
                s.add(WHEEL_ORDER[(idx + 1) % len(WHEEL_ORDER)])
        elif mode == "sequencia":
            if n - 1 >= 0:
                s.add(n - 1)
            if n + 1 <= 36:
                s.add(n + 1)
        elif mode == "espelho":
            for m in MIRROR_MAP.get(n, []):
                s.add(int(m))
        elif mode == "soma":
            target = _digit_sum(n)
            for x in range(37):
                if x != n and _digit_sum(x) == target:
                    s.add(x)
    return sorted(s)


OCCURRENCES_LIMIT_DEFAULT = 200
OCCURRENCES_LIMIT_MAX = 1000


async def sequence_search(
    fields: List[Dict[str, Any]],
    roulette_id: Optional[str] = None,
    shuffled: bool = False,
    horizon: int = 1,
    occurrences_limit: int = OCCURRENCES_LIMIT_DEFAULT,
) -> Dict[str, Any]:
    """Busca documentos em history_triplets casando os k primeiros campos do esquema
    e monta o ranking nas posicoes seguintes. fields = [{value:int, mode:str}, ...] (2..6 itens).

    horizon = quantas posicoes a frente agregar no ranking (1..7). O efetivo e
    limitado a 9-k (tamanho do esquema menos os campos casados).

    occurrences_limit = quantas ocorrencias detalhadas retornar na listagem
    (mais recentes primeiro). O resumo por roleta cobre 100% das ocorrencias.

    Se shuffled=True, os valores casam contra os k primeiros campos do esquema em
    QUALQUER ordem (matching bipartite: cada campo do usuario precisa achar uma
    posicao do esquema cujo valor esteja nos seus candidates)."""
    k = len(fields)
    if k < 2 or k > 6:
        raise ValueError("preencha entre 2 e 6 campos")

    try:
        horizon = int(horizon)
    except (TypeError, ValueError):
        horizon = 1
    if horizon < 1:
        horizon = 1

    try:
        occurrences_limit = int(occurrences_limit)
    except (TypeError, ValueError):
        occurrences_limit = OCCURRENCES_LIMIT_DEFAULT
    if occurrences_limit < 0:
        occurrences_limit = 0
    if occurrences_limit > OCCURRENCES_LIMIT_MAX:
        occurrences_limit = OCCURRENCES_LIMIT_MAX

    for f in fields:
        v = f.get("value")
        if not isinstance(v, int) or v < 0 or v > 36:
            raise ValueError("todos os valores devem estar entre 0 e 36")
        modes = f.get("modes") or ["exato"]
        if not isinstance(modes, list):
            raise ValueError("modes deve ser uma lista")
        for m in modes:
            if m not in VALID_MODES:
                raise ValueError(f"modo invalido: {m}")

    t0 = time.perf_counter()

    match_db_fields = SCHEMA_FIELDS[:k]
    # Posicoes a frente disponiveis no esquema: 9-k. Clampa o horizonte.
    max_horizon = len(SCHEMA_FIELDS) - k
    effective_horizon = min(horizon, max_horizon)
    target_fields = SCHEMA_FIELDS[k:k + effective_horizon]
    # Compat: primeira posicao a frente.
    target_field = target_fields[0] if target_fields else None

    cands_per_field: List[List[int]] = [
        candidates_for(int(f["value"]), f.get("modes") or ["exato"]) for f in fields
    ]

    # Se algum campo tem 0 candidatos (ex: 'espelho' sozinho num numero sem espelho),
    # nada pode casar: retorna ranking vazio sem fazer query.
    if any(len(c) == 0 for c in cands_per_field):
        return {
            "filled": k,
            "target_field": target_field,
            "target_fields": target_fields,
            "match_fields": match_db_fields,
            "candidates_per_field": cands_per_field,
            "fields": fields,
            "roulette_id": roulette_id,
            "shuffled": shuffled,
            "horizon": horizon,
            "effective_horizon": effective_horizon,
            "max_horizon": max_horizon,
            "total_occurrences": 0,
            "ranking": [],
            "missing": list(range(37)),
            "by_roulette": [],
            "occurrences": [],
            "occurrences_shown": 0,
            "occurrences_limit": occurrences_limit,
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
        }

    if shuffled:
        result = await _search_shuffled(
            match_db_fields,
            target_fields,
            cands_per_field,
            roulette_id,
            occurrences_limit,
        )
    else:
        result = await _search_ordered(
            match_db_fields,
            target_fields,
            cands_per_field,
            roulette_id,
            occurrences_limit,
        )

    ranking = result["ranking"]
    total_occ = result["total"]
    seen = {r["number"] for r in ranking}
    missing = sorted(set(range(37)) - seen)

    return {
        "filled": k,
        "target_field": target_field,
        "target_fields": target_fields,
        "match_fields": match_db_fields,
        "candidates_per_field": cands_per_field,
        "fields": fields,
        "roulette_id": roulette_id,
        "shuffled": shuffled,
        "horizon": horizon,
        "effective_horizon": effective_horizon,
        "max_horizon": max_horizon,
        "total_occurrences": total_occ,
        "ranking": ranking,
        "missing": missing,
        "by_roulette": result["by_roulette"],
        "occurrences": result["occurrences"],
        "occurrences_shown": len(result["occurrences"]),
        "occurrences_limit": occurrences_limit,
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
    }


def _serialize_ts(ts: Any) -> Any:
    """Converte timestamp para algo JSON-serializavel (ISO se for datetime)."""
    if ts is None:
        return None
    if hasattr(ts, "isoformat"):
        return ts.isoformat()
    return ts


def _occurrence_from_doc(
    doc: Dict[str, Any],
    match_db_fields: List[str],
    target_fields: List[str],
) -> Dict[str, Any]:
    """Monta um item da listagem de ocorrencias: roleta, timestamp, a sequencia
    casada (posicoes do esquema) e os numeros a frente (horizonte)."""
    return {
        "roulette_id": doc.get("roulette_id"),
        "timestamp": _serialize_ts(doc.get("timestamp")),
        "sequence": [doc.get(f) for f in match_db_fields],
        "ahead": [doc.get(f) for f in target_fields],
    }


async def _search_ordered(
    match_db_fields: List[str],
    target_fields: List[str],
    cands_per_field: List[List[int]],
    roulette_id: Optional[str],
    occurrences_limit: int,
) -> Dict[str, Any]:
    match: Dict[str, Any] = {}
    for db_field, cands in zip(match_db_fields, cands_per_field):
        if len(cands) == 1:
            match[db_field] = cands[0]
        else:
            match[db_field] = {"$in": cands}
    if roulette_id:
        match["roulette_id"] = roulette_id

    total_occ = await history_triplets_coll.count_documents(match)
    empty = {"ranking": [], "total": total_occ, "by_roulette": [], "occurrences": []}
    if total_occ == 0 or not target_fields:
        return empty

    # Agrega o ranking ao longo de todas as posicoes do horizonte: monta um
    # array com os valores das target_fields, desenrola e agrupa.
    pipeline = [
        {"$match": match},
        {"$project": {"_vals": [f"${tf}" for tf in target_fields]}},
        {"$unwind": "$_vals"},
        {"$match": {"_vals": {"$ne": None}}},
        {"$group": {"_id": "$_vals", "count": {"$sum": 1}}},
        {"$sort": {"count": -1, "_id": 1}},
    ]
    rows = [doc async for doc in history_triplets_coll.aggregate(pipeline)]
    total_appearances = sum(int(r["count"]) for r in rows) or 1
    ranking = [
        {
            "number": int(r["_id"]),
            "count": int(r["count"]),
            "percentage": round(int(r["count"]) / total_appearances * 100, 2),
        }
        for r in rows
    ]

    # Resumo por roleta (cobre 100% das ocorrencias).
    br_pipeline = [
        {"$match": match},
        {"$group": {"_id": "$roulette_id", "count": {"$sum": 1}}},
        {"$sort": {"count": -1, "_id": 1}},
    ]
    by_roulette = [
        {"roulette_id": r["_id"], "count": int(r["count"])}
        async for r in history_triplets_coll.aggregate(br_pipeline)
    ]

    # Listagem detalhada das ocorrencias (mais recentes primeiro, limitada).
    occurrences: List[Dict[str, Any]] = []
    if occurrences_limit > 0:
        proj = {f: 1 for f in match_db_fields}
        for tf in target_fields:
            proj[tf] = 1
        proj["roulette_id"] = 1
        proj["timestamp"] = 1
        proj["_id"] = 0
        cursor = (
            history_triplets_coll.find(match, proj)
            .sort("timestamp", -1)
            .limit(occurrences_limit)
        )
        occurrences = [
            _occurrence_from_doc(d, match_db_fields, target_fields)
            async for d in cursor
        ]

    return {
        "ranking": ranking,
        "total": total_occ,
        "by_roulette": by_roulette,
        "occurrences": occurrences,
    }


async def _search_shuffled(
    match_db_fields: List[str],
    target_fields: List[str],
    cands_per_field: List[List[int]],
    roulette_id: Optional[str],
    occurrences_limit: int,
) -> Dict[str, Any]:
    """Busca permitindo que os k campos do usuario casem em qualquer ordem
    contra as k primeiras posicoes do esquema (prev_3..c). O ranking agrega
    todas as posicoes do horizonte (target_fields)."""
    k = len(match_db_fields)
    if not target_fields:
        return {"ranking": [], "total": 0, "by_roulette": [], "occurrences": []}

    # Pre-filtro DB: cada uma das k posicoes tem que estar na UNIAO de todos
    # os candidatos.
    union_cands = sorted({c for cands in cands_per_field for c in cands})
    match: Dict[str, Any] = {}
    for db_field in match_db_fields:
        match[db_field] = {"$in": union_cands}
    if roulette_id:
        match["roulette_id"] = roulette_id

    # Conjunto de candidatos por campo do usuario (para o teste bipartite).
    field_cand_sets: List[set] = [set(c) for c in cands_per_field]

    projection = {f: 1 for f in match_db_fields}
    for tf in target_fields:
        projection[tf] = 1
    projection["roulette_id"] = 1
    projection["timestamp"] = 1
    projection["_id"] = 0

    # Permutacoes pre-computadas (k <= 6 -> 720 worst case).
    perms = list(permutations(range(k)))

    target_counts: Counter = Counter()
    by_roulette_counter: Counter = Counter()
    total_occ = 0  # numero de janelas (documentos) que casaram
    # (timestamp_raw, occurrence_dict) para ordenar por mais recente depois.
    matched_rows: List[tuple] = []

    cursor = history_triplets_coll.find(match, projection)
    async for doc in cursor:
        positions = [doc.get(f) for f in match_db_fields]
        if any(p is None for p in positions):
            continue
        # Existe permutacao sigma tal que positions[i] in field_cand_sets[sigma(i)]?
        matched = False
        for perm in perms:
            ok = True
            for i, fi in enumerate(perm):
                if positions[i] not in field_cand_sets[fi]:
                    ok = False
                    break
            if ok:
                matched = True
                break
        if not matched:
            continue
        total_occ += 1
        for tf in target_fields:
            tgt = doc.get(tf)
            if tgt is not None:
                target_counts[int(tgt)] += 1
        by_roulette_counter[doc.get("roulette_id")] += 1
        matched_rows.append(
            (doc.get("timestamp"), _occurrence_from_doc(doc, match_db_fields, target_fields))
        )

    total_appearances = sum(target_counts.values()) or 1
    rows = sorted(target_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ranking = [
        {
            "number": int(num),
            "count": int(cnt),
            "percentage": round(cnt / total_appearances * 100, 2),
        }
        for num, cnt in rows
    ]

    by_roulette = [
        {"roulette_id": rid, "count": int(cnt)}
        for rid, cnt in sorted(
            by_roulette_counter.items(), key=lambda kv: (-kv[1], str(kv[0]))
        )
    ]

    # Ordena por mais recente; timestamps None vao para o fim.
    matched_rows.sort(key=lambda r: (r[0] is not None, r[0]), reverse=True)
    occurrences = (
        [occ for _, occ in matched_rows[:occurrences_limit]]
        if occurrences_limit > 0
        else []
    )

    return {
        "ranking": ranking,
        "total": total_occ,
        "by_roulette": by_roulette,
        "occurrences": occurrences,
    }
