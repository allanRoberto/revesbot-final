from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

import pytz
from fastapi import APIRouter, HTTPException

from api.core.db import history_coll


router = APIRouter()


@router.get("/api/analise/{roulette_id}")
async def get_roulette_analysis(
    roulette_id: str,
    number: int = None,
    start_date: str = None,
    end_date: str = None,
    hour_start: int = None,
    hour_end: int = None,
):
    """
    API para análise detalhada de números de uma roleta

    Params:
    - roulette_id: ID da roleta (ex: pragmatic-brazilian-roulette)
    - number: Número específico para filtrar (0-36) - opcional
    - start_date: Data inicial (YYYY-MM-DD) - opcional
    - end_date: Data final (YYYY-MM-DD) - opcional
    - hour_start: Hora inicial (0-23) - opcional
    - hour_end: Hora final (0-23) - opcional
    """
    try:
        filter_query = {"roulette_id": roulette_id}

        if number is not None:
            filter_query["value"] = number

        date_filter = {}
        if start_date:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            date_filter["$gte"] = start_dt
        if end_date:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            end_dt = end_dt.replace(hour=23, minute=59, second=59)
            date_filter["$lte"] = end_dt

        if date_filter:
            filter_query["timestamp"] = date_filter

        cursor = history_coll.find(filter_query).sort("timestamp", -1)
        results = await cursor.to_list(length=None)

        tz_br = pytz.timezone("America/Sao_Paulo")
        processed_results = []

        for doc in results:
            timestamp = doc["timestamp"]
            if timestamp.tzinfo is None:
                timestamp = pytz.utc.localize(timestamp)
            br_time = timestamp.astimezone(tz_br)

            if hour_start is not None and br_time.hour < hour_start:
                continue
            if hour_end is not None and br_time.hour > hour_end:
                continue

            processed_results.append({
                "value": doc["value"],
                "timestamp": timestamp.isoformat(),
                "date": br_time.strftime("%Y-%m-%d"),
                "time": br_time.strftime("%H:%M:%S"),
                "hour": br_time.hour,
                "day_of_week": br_time.strftime("%A"),
                "formatted": br_time.strftime("%d/%m/%Y %H:%M:%S"),
            })

        number_stats: Dict[int, Dict[str, Any]] = {}
        for i in range(37):
            count = sum(1 for r in processed_results if r["value"] == i)
            if count > 0:
                number_stats[i] = {
                    "count": count,
                    "percentage": (count / len(processed_results) * 100) if processed_results else 0,
                    "occurrences": [r for r in processed_results if r["value"] == i],
                }

        hour_stats: Dict[int, int] = {}
        for h in range(24):
            hour_count = sum(1 for r in processed_results if r["hour"] == h)
            if hour_count > 0:
                hour_stats[h] = hour_count

        daily_stats: Dict[str, Dict[str, Any]] = {}
        for result in processed_results:
            day_key = result["date"]
            if day_key not in daily_stats:
                daily_stats[day_key] = {"count": 0, "numbers": {}}
            daily_stats[day_key]["count"] += 1

            num = result["value"]
            daily_stats[day_key]["numbers"][num] = daily_stats[day_key]["numbers"].get(num, 0) + 1

        return {
            "roulette_id": roulette_id,
            "total_count": len(processed_results),
            "filters_applied": {
                "number": number,
                "start_date": start_date,
                "end_date": end_date,
                "hour_start": hour_start,
                "hour_end": hour_end,
            },
            "number_statistics": number_stats,
            "hourly_distribution": hour_stats,
            "daily_statistics": daily_stats,
            "recent_results": processed_results[:500],
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
