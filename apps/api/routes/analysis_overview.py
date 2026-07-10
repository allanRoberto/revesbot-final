from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

import pytz
from fastapi import APIRouter, HTTPException

from api.core.db import history_coll


router = APIRouter()

TZ_BR = "America/Sao_Paulo"
MAX_OCCURRENCES = 20000


def _format_occurrence(doc: Dict[str, Any], tz_br) -> Dict[str, Any]:
    timestamp = doc["timestamp"]
    if timestamp.tzinfo is None:
        timestamp = pytz.utc.localize(timestamp)
    br_time = timestamp.astimezone(tz_br)
    return {
        "value": doc["value"],
        "timestamp": timestamp.isoformat(),
        "date": br_time.strftime("%Y-%m-%d"),
        "time": br_time.strftime("%H:%M:%S"),
        "hour": br_time.hour,
        "day_of_week": br_time.strftime("%A"),
        "formatted": br_time.strftime("%d/%m/%Y %H:%M:%S"),
    }


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
    API para análise detalhada de números de uma roleta.

    Contagens (por número, por hora, por dia) são agregadas direto no MongoDB —
    o histórico completo de uma mesa passa de 200 mil giros e materializar tudo
    em Python tornava a resposta uma questão de minutos.

    A lista de ocorrências individuais só é retornada quando `number` é
    informado (limitada às MAX_OCCURRENCES mais recentes); sem esse filtro o
    front usa apenas contagens + `recent_results`.

    Params:
    - roulette_id: ID da roleta (ex: pragmatic-brazilian-roulette)
    - number: Número específico para filtrar (0-36) - opcional
    - start_date: Data inicial (YYYY-MM-DD) - opcional
    - end_date: Data final (YYYY-MM-DD) - opcional
    - hour_start: Hora inicial (0-23) - opcional
    - hour_end: Hora final (0-23) - opcional
    """
    try:
        filter_query: Dict[str, Any] = {"roulette_id": roulette_id}

        if number is not None:
            filter_query["value"] = number

        date_filter: Dict[str, Any] = {}
        if start_date:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            date_filter["$gte"] = start_dt
        if end_date:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            end_dt = end_dt.replace(hour=23, minute=59, second=59)
            date_filter["$lte"] = end_dt

        if date_filter:
            filter_query["timestamp"] = date_filter

        match_stages: List[Dict[str, Any]] = [{"$match": filter_query}]

        # Filtro de hora (fuso BR) direto no banco — antes era um continue por doc
        if hour_start is not None or hour_end is not None:
            hour_conds = []
            if hour_start is not None:
                hour_conds.append({"$gte": ["$_hora_br", hour_start]})
            if hour_end is not None:
                hour_conds.append({"$lte": ["$_hora_br", hour_end]})
            match_stages.append({"$addFields": {
                "_hora_br": {"$hour": {"date": "$timestamp", "timezone": TZ_BR}},
            }})
            match_stages.append({"$match": {"$expr": {"$and": hour_conds}}})

        pipeline = match_stages + [{"$facet": {
            "por_numero": [
                {"$group": {"_id": "$value", "count": {"$sum": 1}}},
            ],
            "por_hora": [
                {"$group": {
                    "_id": {"$hour": {"date": "$timestamp", "timezone": TZ_BR}},
                    "count": {"$sum": 1},
                }},
            ],
            "por_dia": [
                {"$group": {
                    "_id": {
                        "date": {"$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp", "timezone": TZ_BR}},
                        "value": "$value",
                    },
                    "count": {"$sum": 1},
                }},
            ],
            "recentes": [
                {"$sort": {"timestamp": -1}},
                {"$limit": 500},
                {"$project": {"_id": 0, "value": 1, "timestamp": 1}},
            ],
            "total": [
                {"$count": "n"},
            ],
        }}]

        facets = (await history_coll.aggregate(pipeline).to_list(length=1))[0]

        total_count = facets["total"][0]["n"] if facets["total"] else 0
        tz_br = pytz.timezone(TZ_BR)

        number_stats: Dict[int, Dict[str, Any]] = {}
        for item in facets["por_numero"]:
            num = int(item["_id"])
            count = int(item["count"])
            number_stats[num] = {
                "count": count,
                "percentage": (count / total_count * 100) if total_count else 0,
            }

        hour_stats: Dict[int, int] = {
            int(item["_id"]): int(item["count"]) for item in facets["por_hora"]
        }

        daily_stats: Dict[str, Dict[str, Any]] = {}
        for item in facets["por_dia"]:
            day_key = item["_id"]["date"]
            num = int(item["_id"]["value"])
            count = int(item["count"])
            if day_key not in daily_stats:
                daily_stats[day_key] = {"count": 0, "numbers": {}}
            daily_stats[day_key]["count"] += count
            daily_stats[day_key]["numbers"][num] = count

        recent_results = [_format_occurrence(doc, tz_br) for doc in facets["recentes"]]

        # Ocorrências individuais apenas com filtro de número (dataset limitado)
        if number is not None and number in number_stats:
            occ_pipeline = match_stages + [
                {"$sort": {"timestamp": -1}},
                {"$limit": MAX_OCCURRENCES},
                {"$project": {"_id": 0, "value": 1, "timestamp": 1}},
            ]
            occ_docs = await history_coll.aggregate(occ_pipeline).to_list(length=MAX_OCCURRENCES)
            number_stats[number]["occurrences"] = [
                _format_occurrence(doc, tz_br) for doc in occ_docs
            ]

        return {
            "roulette_id": roulette_id,
            "total_count": total_count,
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
            "recent_results": recent_results,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
