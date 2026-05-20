from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from pymongo import ASCENDING

from api.core.db import history_coll, history_triplets_coll
from api.services.base_suggestion import MIRROR_MAP, get_neighbors

ROULETTE_NUMBERS = set(range(37))


def _relation(actual: int, target: int, neighbor_span: int) -> Optional[str]:
    """Como o valor `actual` (campo do banco) se relaciona com `target` (numero digitado)."""
    if actual == target:
        return "exato"
    if actual in (target - 1, target + 1) and 0 <= actual <= 36:
        return "sequencia"
    if actual in MIRROR_MAP.get(target, []):
        return "espelho"
    if actual in get_neighbors(target, span=neighbor_span):
        return "vizinho"
    return None


def _evaluate_positions(inputs: List[int], actuals: List[int], neighbor_span: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for i, (inp, act) in enumerate(zip(inputs, actuals)):
        rows.append({
            "pos": i + 1,
            "input": inp,
            "actual": act,
            "relation": _relation(act, inp, neighbor_span),
        })
    return rows


def _check_conf2(positions: List[Dict[str, Any]]) -> bool:
    """Precisa de >=1 posicao exata E >=1 outra posicao com vizinho/sequencia/espelho."""
    exact_idx = {p["pos"] for p in positions if p["relation"] == "exato"}
    if not exact_idx:
        return False
    for p in positions:
        if p["pos"] in exact_idx:
            continue
        if p["relation"] in ("vizinho", "sequencia", "espelho"):
            return True
    return False


def _check_conf3(positions: List[Dict[str, Any]]) -> bool:
    """Precisa de >=1 posicao com qualquer relacao (exato/vizinho/sequencia/espelho)."""
    return any(p["relation"] is not None for p in positions)


async def _post_sequence_numbers(roulette_id: str, base_ts: Any, count: int) -> List[Dict[str, Any]]:
    """Numeros que vieram apos a sequencia (apos next3) na roleta identificada.

    base_ts e o timestamp de `a`. Apos `a` vem: b, c, next1, next2, next3 (5 spins),
    entao pulamos esses 5 e pegamos os `count` seguintes.
    """
    docs = await history_coll.find(
        {"roulette_id": roulette_id, "timestamp": {"$gt": base_ts}},
        {"value": 1, "timestamp": 1},
    ).sort("timestamp", ASCENDING).skip(5).limit(count).to_list(length=count)
    return [
        {
            "value": int(d["value"]),
            "timestamp": d["timestamp"].isoformat() if hasattr(d.get("timestamp"), "isoformat") else str(d.get("timestamp")),
        }
        for d in docs
    ]


async def validate_triplet_pattern(
    numbers: List[int],
    neighbor_span: int = 2,
    roulette_id: Optional[str] = None,
    post_count: int = 20,
    max_occurrences: int = 500,
) -> Dict[str, Any]:
    """Valida o padrao de 3 trios (9 numeros em ordem cronologica, mais antigo -> mais recente).

    zzz = numbers[0:3] -> prev_3, prev_2, prev_1   (trio mais antigo)
    yyy = numbers[3:6] -> a, b, c                  (trio do meio)
    xxx = numbers[6:9] -> next1, next2, next3       (trio mais recente)
    """
    if len(numbers) != 9:
        raise ValueError("sao necessarios exatamente 9 numeros")
    for n in numbers:
        if n not in ROULETTE_NUMBERS:
            raise ValueError("todos os numeros devem estar entre 0 e 36")
    if neighbor_span < 1 or neighbor_span > 6:
        raise ValueError("neighbor_span deve estar entre 1 e 6")

    t0 = time.perf_counter()

    zzz = numbers[0:3]   # -> prev_3, prev_2, prev_1
    yyy = numbers[3:6]   # -> a, b, c
    xxx = numbers[6:9]   # -> next1, next2, next3

    # ── Confirmacao 1: ocorrencia exata do trio mais antigo nos campos prev ──
    match: Dict[str, Any] = {
        "prev_3": zzz[0],
        "prev_2": zzz[1],
        "prev_1": zzz[2],
    }
    if roulette_id:
        match["roulette_id"] = roulette_id

    conf1_docs = await history_triplets_coll.find(match).limit(max_occurrences).to_list(length=max_occurrences)
    conf1_count = len(conf1_docs)

    confirmed: List[Dict[str, Any]] = []
    conf2_count = 0

    for doc in conf1_docs:
        abc = [int(doc["a"]), int(doc["b"]), int(doc["c"])]
        nxt = [int(doc["next1"]), int(doc["next2"]), int(doc["next3"])]

        # ── Confirmacao 2: trio do meio (yyy) vs a, b, c ──
        conf2_positions = _evaluate_positions(yyy, abc, neighbor_span)
        if not _check_conf2(conf2_positions):
            continue
        conf2_count += 1

        # ── Confirmacao 3: trio mais recente (xxx) vs next1, next2, next3 ──
        conf3_positions = _evaluate_positions(xxx, nxt, neighbor_span)
        if not _check_conf3(conf3_positions):
            continue

        rid = doc.get("roulette_id", "")
        base_ts = doc.get("timestamp")
        post = await _post_sequence_numbers(rid, base_ts, post_count) if base_ts is not None else []

        confirmed.append({
            "roulette_id": rid,
            "timestamp": base_ts.isoformat() if hasattr(base_ts, "isoformat") else str(base_ts),
            "matched": {
                "prev": [int(doc["prev_3"]), int(doc["prev_2"]), int(doc["prev_1"])],
                "abc": abc,
                "next": nxt,
            },
            "conf2_positions": conf2_positions,
            "conf3_positions": conf3_positions,
            "post_numbers": post,
        })

    return {
        "input": {
            "zzz": zzz,
            "yyy": yyy,
            "xxx": xxx,
        },
        "neighbor_span": neighbor_span,
        "roulette_id": roulette_id,
        "funnel": {
            "conf1": conf1_count,
            "conf2": conf2_count,
            "confirmed": len(confirmed),
        },
        "truncated": conf1_count >= max_occurrences,
        "confirmed": confirmed,
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
    }
