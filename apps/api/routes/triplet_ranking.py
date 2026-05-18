from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List

from fastapi import APIRouter, Query
from pymongo import DESCENDING

from api.core.db import history_coll, history_triplets_coll

router = APIRouter()


@router.get("/api/triplet-ranking/query")
async def query_triplet_ranking(
    roulette_id: str = Query(...),
    history_count: int = Query(12, ge=3, le=100),
    top_next1: int = Query(10, ge=0, le=37),
    top_next2: int = Query(10, ge=0, le=37),
    top_next3: int = Query(10, ge=0, le=37),
) -> Dict[str, Any]:
    # Busca os últimos N números da roleta
    docs = await history_coll.find(
        {"roulette_id": roulette_id},
        {"value": 1, "timestamp": 1},
    ).sort("timestamp", DESCENDING).limit(history_count).to_list(length=history_count)

    if len(docs) < 3:
        return {"numbers": [], "ranking": [], "trios": []}

    docs.reverse()
    numbers = [int(d["value"]) for d in docs]

    scores: Dict[int, Dict[str, int]] = {n: {"next1": 0, "next2": 0, "next3": 0} for n in range(37)}
    trios_detail: List[Dict] = []

    for i in range(len(numbers) - 2):
        a, b, c = numbers[i], numbers[i + 1], numbers[i + 2]
        trio_sorted = sorted([a, b, c])

        trio_info: Dict[str, Any] = {"trio": [a, b, c], "next1": [], "next2": [], "next3": []}

        for field, top_n in [("next1", top_next1), ("next2", top_next2), ("next3", top_next3)]:
            if top_n == 0:
                continue
            pipeline = [
                {"$match": {"a": trio_sorted[0], "b": trio_sorted[1], "c": trio_sorted[2]}},
                {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": top_n},
            ]
            results = await history_triplets_coll.aggregate(pipeline).to_list(length=top_n)
            if not results:
                pipeline[0]["$match"] = {"a": a, "b": b, "c": c}
                results = await history_triplets_coll.aggregate(pipeline).to_list(length=top_n)

            for r in results:
                num = r["_id"]
                cnt = r["count"]
                if num is not None and 0 <= num <= 36:
                    scores[num][field] += cnt
            trio_info[field] = [{"number": r["_id"], "count": r["count"]} for r in results if r["_id"] is not None]

        trios_detail.append(trio_info)

    ranking = []
    for num in range(37):
        s = scores[num]
        total = s["next1"] + s["next2"] + s["next3"]
        ranking.append({
            "number": num,
            "next1": s["next1"],
            "next2": s["next2"],
            "next3": s["next3"],
            "total": total,
        })

    ranking.sort(key=lambda x: x["total"], reverse=True)
    for pos, item in enumerate(ranking, 1):
        item["rank"] = pos

    return {
        "roulette_id": roulette_id,
        "numbers": numbers,
        "history_count": history_count,
        "trios_count": len(trios_detail),
        "ranking": ranking,
        "trios": trios_detail,
    }
