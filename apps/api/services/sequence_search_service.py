from __future__ import annotations

import time
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
    """Retorna os candidatos de busca para um campo, sempre incluindo o numero digitado.
    `modes` pode conter varias opcoes ('vizinhos','sequencia','espelho','soma'); os
    candidatos sao a uniao dos conjuntos. 'exato' (ou lista vazia) significa apenas o
    numero digitado."""
    n = int(value)
    s = {n}
    cleaned = [m for m in (modes or []) if m in VALID_MODES]
    if not cleaned or cleaned == ["exato"]:
        return [n]
    for mode in cleaned:
        if mode == "exato":
            continue
        if mode == "vizinhos":
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
                if _digit_sum(x) == target:
                    s.add(x)
    return sorted(s)


async def sequence_search(
    fields: List[Dict[str, Any]],
    roulette_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Busca documentos em history_triplets casando os k primeiros campos do esquema
    e monta o ranking no (k+1)-esimo campo. fields = [{value:int, mode:str}, ...] (2..6 itens)."""
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
    seen = {r["number"] for r in ranking}
    missing = sorted(set(range(37)) - seen)

    return {
        "filled": k,
        "target_field": target_field,
        "match_fields": match_db_fields,
        "candidates_per_field": cands_per_field,
        "fields": fields,
        "roulette_id": roulette_id,
        "total_occurrences": total_occ,
        "ranking": ranking,
        "missing": missing,
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
    }
