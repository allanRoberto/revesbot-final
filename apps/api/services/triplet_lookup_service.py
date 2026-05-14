from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from api.core.db import history_triplets_coll


ROULETTE_NUMBERS = set(range(37))


async def lookup_triplet_ranking(
    a: int,
    b: int,
    c: int,
    positions: int,
    roulette_id: Optional[str] = None,
    window_hours: Optional[float] = None,
    prev_positions: int = 0,
) -> Dict[str, Any]:
    if positions not in (1, 2, 3):
        raise ValueError("positions must be 1, 2 or 3")
    if prev_positions not in (0, 1, 2, 3):
        raise ValueError("prev_positions must be 0, 1, 2 or 3")
    for label, value in (("a", a), ("b", b), ("c", c)):
        if value not in ROULETTE_NUMBERS:
            raise ValueError(f"{label} must be in 0..36")
    if window_hours is not None and window_hours <= 0:
        raise ValueError("window_hours must be > 0 when provided")

    t0 = time.perf_counter()

    match: Dict[str, Any] = {"a": a, "b": b, "c": c}
    if roulette_id:
        match["roulette_id"] = roulette_id
    window_cutoff: Optional[datetime] = None
    if window_hours is not None:
        window_cutoff = datetime.now(timezone.utc) - timedelta(hours=float(window_hours))
        match["timestamp"] = {"$gte": window_cutoff}

    fields = [f"$next{i}" for i in range(1, positions + 1)]
    fields.extend(f"$prev_{i}" for i in range(1, prev_positions + 1))
    fields_per_doc = len(fields)

    total_occurrences = await history_triplets_coll.count_documents(match)
    if total_occurrences == 0:
        return {
            "sequence": [a, b, c],
            "positions": positions,
            "prev_positions": prev_positions,
            "roulette_id": roulette_id,
            "window_hours": window_hours,
            "window_cutoff_utc": window_cutoff.isoformat() if window_cutoff else None,
            "total_occurrences": 0,
            "ranking": [],
            "missing": sorted(ROULETTE_NUMBERS),
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
        }

    pipeline: List[Dict[str, Any]] = [
        {"$match": match},
        {"$project": {"nums": fields}},
        {"$unwind": "$nums"},
        {"$match": {"nums": {"$ne": None}}},
        {"$group": {"_id": "$nums", "count": {"$sum": 1}}},
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
    missing = sorted(ROULETTE_NUMBERS - seen)

    return {
        "sequence": [a, b, c],
        "positions": positions,
        "prev_positions": prev_positions,
        "roulette_id": roulette_id,
        "window_hours": window_hours,
        "window_cutoff_utc": window_cutoff.isoformat() if window_cutoff else None,
        "total_occurrences": total_occurrences,
        "ranking": ranking,
        "missing": missing,
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
    }
