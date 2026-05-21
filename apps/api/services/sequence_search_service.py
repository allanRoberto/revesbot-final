from __future__ import annotations

import time
from collections import Counter
from itertools import permutations
from typing import Any, Dict, List, Optional

from api.core.db import history_triplets_coll
from api.services.base_suggestion import MIRROR_MAP, WHEEL_ORDER, WHEEL_INDEX


# Ordem do esquema do history_triplets:
# prev_3, prev_2, prev_1, a, b, c, next1, next2, next3
# Quando o usuario preenche k campos (2..6), casamos os k primeiros e
# fazemos o ranking no campo (k+1)-esimo.
DB_FIELD_SEQ: List[str] = ["prev_3", "prev_2", "prev_1", "a", "b", "c", "next1"]
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


async def sequence_search(
    fields: List[Dict[str, Any]],
    roulette_id: Optional[str] = None,
    shuffled: bool = False,
) -> Dict[str, Any]:
    """Busca documentos em history_triplets casando os k primeiros campos do esquema
    e monta o ranking no (k+1)-esimo campo. fields = [{value:int, mode:str}, ...] (2..6 itens).

    Se shuffled=True, os valores casam contra os k primeiros campos do esquema em
    QUALQUER ordem (matching bipartite: cada campo do usuario precisa achar uma
    posicao do esquema cujo valor esteja nos seus candidates)."""
    k = len(fields)
    if k < 2 or k > 6:
        raise ValueError("preencha entre 2 e 6 campos")

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

    match_db_fields = DB_FIELD_SEQ[:k]
    target_field = DB_FIELD_SEQ[k]

    cands_per_field: List[List[int]] = [
        candidates_for(int(f["value"]), f.get("modes") or ["exato"]) for f in fields
    ]

    # Se algum campo tem 0 candidatos (ex: 'espelho' sozinho num numero sem espelho),
    # nada pode casar: retorna ranking vazio sem fazer query.
    if any(len(c) == 0 for c in cands_per_field):
        return {
            "filled": k,
            "target_field": target_field,
            "match_fields": match_db_fields,
            "candidates_per_field": cands_per_field,
            "fields": fields,
            "roulette_id": roulette_id,
            "total_occurrences": 0,
            "ranking": [],
            "missing": list(range(37)),
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
        }

    if shuffled:
        ranking, total_occ = await _search_shuffled(
            match_db_fields,
            target_field,
            cands_per_field,
            roulette_id,
        )
    else:
        ranking, total_occ = await _search_ordered(
            match_db_fields,
            target_field,
            cands_per_field,
            roulette_id,
        )

    seen = {r["number"] for r in ranking}
    missing = sorted(set(range(37)) - seen)

    return {
        "filled": k,
        "target_field": target_field,
        "match_fields": match_db_fields,
        "candidates_per_field": cands_per_field,
        "fields": fields,
        "roulette_id": roulette_id,
        "shuffled": shuffled,
        "total_occurrences": total_occ,
        "ranking": ranking,
        "missing": missing,
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
    }


async def _search_ordered(
    match_db_fields: List[str],
    target_field: str,
    cands_per_field: List[List[int]],
    roulette_id: Optional[str],
) -> tuple[List[Dict[str, Any]], int]:
    match: Dict[str, Any] = {}
    for db_field, cands in zip(match_db_fields, cands_per_field):
        if len(cands) == 1:
            match[db_field] = cands[0]
        else:
            match[db_field] = {"$in": cands}
    if roulette_id:
        match["roulette_id"] = roulette_id

    total_occ = await history_triplets_coll.count_documents(match)
    if total_occ == 0:
        return [], 0

    pipeline = [
        {"$match": match},
        {"$match": {target_field: {"$ne": None}}},
        {"$group": {"_id": f"${target_field}", "count": {"$sum": 1}}},
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
    return ranking, total_occ


async def _search_shuffled(
    match_db_fields: List[str],
    target_field: str,
    cands_per_field: List[List[int]],
    roulette_id: Optional[str],
) -> tuple[List[Dict[str, Any]], int]:
    """Busca permitindo que os k campos do usuario casem em qualquer ordem
    contra as k primeiras posicoes do esquema (prev_3..c)."""
    k = len(match_db_fields)

    # Pre-filtro DB: cada uma das k posicoes tem que estar na UNIAO de todos
    # os candidatos. E necessario que o doc tenha valor nao-nulo no target.
    union_cands = sorted({c for cands in cands_per_field for c in cands})
    match: Dict[str, Any] = {target_field: {"$ne": None}}
    for db_field in match_db_fields:
        match[db_field] = {"$in": union_cands}
    if roulette_id:
        match["roulette_id"] = roulette_id

    # Conjunto de candidatos por campo do usuario (para o teste bipartite).
    field_cand_sets: List[set] = [set(c) for c in cands_per_field]

    projection = {f: 1 for f in match_db_fields}
    projection[target_field] = 1
    projection["_id"] = 0

    # Permutacoes pre-computadas (k <= 6 -> 720 worst case).
    perms = list(permutations(range(k)))

    target_counts: Counter = Counter()
    total_occ = 0

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
        tgt = doc.get(target_field)
        if tgt is None:
            continue
        target_counts[int(tgt)] += 1
        total_occ += 1

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
    return ranking, total_occ
