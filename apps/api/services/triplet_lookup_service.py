from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from api.core.db import history_triplets_coll


ROULETTE_NUMBERS = set(range(37))


async def lookup_triplet_ranking(
    a: int,
    b: int,
    c: int,
    positions: int,
    roulette_id: Optional[str] = None,
) -> Dict[str, Any]:
    if positions not in (1, 2, 3):
        raise ValueError("positions must be 1, 2 or 3")
    for label, value in (("a", a), ("b", b), ("c", c)):
        if value not in ROULETTE_NUMBERS:
            raise ValueError(f"{label} must be in 0..36")

    t0 = time.perf_counter()

    match: Dict[str, Any] = {"a": a, "b": b, "c": c}
    if roulette_id:
        match["roulette_id"] = roulette_id

    total_occurrences = await history_triplets_coll.count_documents(match)
    if total_occurrences == 0:
        return {
            "sequence": [a, b, c],
            "positions": positions,
            "roulette_id": roulette_id,
            "total_occurrences": 0,
            "ranking": [],
            "missing": sorted(ROULETTE_NUMBERS),
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
        }

    next_fields = [f"$next{i}" for i in range(1, positions + 1)]
    pipeline: List[Dict[str, Any]] = [
        {"$match": match},
        {"$project": {"nexts": next_fields}},
        {"$unwind": "$nexts"},
        {"$group": {"_id": "$nexts", "count": {"$sum": 1}}},
        {"$sort": {"count": -1, "_id": 1}},
    ]
    rows = [doc async for doc in history_triplets_coll.aggregate(pipeline)]
    total_appearances = total_occurrences * positions
    ranking = [
        {
            "number": int(r["_id"]),
            "count": int(r["count"]),
            "percentage": round(r["count"] / total_appearances * 100, 2) if total_appearances else 0.0,
        }
        for r in rows
    ]
    seen = {r["number"] for r in ranking}
    missing = sorted(ROULETTE_NUMBERS - seen)

    return {
        "sequence": [a, b, c],
        "positions": positions,
        "roulette_id": roulette_id,
        "total_occurrences": total_occurrences,
        "ranking": ranking,
        "missing": missing,
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
    }
