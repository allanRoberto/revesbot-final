from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import HTTPException

from api.core.db import (
    ensure_next_number_ranking_indexes,
    history_coll,
    next_number_rankings_coll,
)


DEFAULT_ROULETTE_ID = "pragmatic-auto-roulette"
NUMBER_MIN = 0
NUMBER_MAX = 36
SERVICE_VERSION = "next_number_rankings_v1"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_roulette_id(roulette_id: str | None) -> str:
    safe_roulette_id = str(roulette_id or "").strip()
    if not safe_roulette_id:
        raise ValueError("roulette_id e obrigatorio.")
    return safe_roulette_id


def _coerce_base_number(base_number: Any) -> int:
    try:
        number = int(base_number)
    except (TypeError, ValueError):
        raise ValueError("base_number deve ser um numero entre 0 e 36.") from None
    if number < NUMBER_MIN or number > NUMBER_MAX:
        raise ValueError("base_number deve ser um numero entre 0 e 36.")
    return number


def _build_empty_number_payload(base_number: int) -> Dict[str, Any]:
    return {
        "base_number": int(base_number),
        "occurrence_count": 0,
        "with_next_count": 0,
        "without_next_count": 0,
        "first_occurrence_utc": None,
        "last_occurrence_utc": None,
        "ranking": [],
    }


def _build_aggregation_pipeline(roulette_id: str) -> List[Dict[str, Any]]:
    return [
        {
            "$match": {
                "roulette_id": roulette_id,
                "value": {"$gte": NUMBER_MIN, "$lte": NUMBER_MAX},
            }
        },
        {
            "$setWindowFields": {
                "sortBy": {"timestamp": 1, "_id": 1},
                "output": {
                    "next_value": {"$shift": {"output": "$value", "by": 1}},
                },
            }
        },
        {
            "$facet": {
                "rankings": [
                    {
                        "$match": {
                            "next_value": {"$gte": NUMBER_MIN, "$lte": NUMBER_MAX},
                        }
                    },
                    {
                        "$group": {
                            "_id": {
                                "base_number": "$value",
                                "next_number": "$next_value",
                            },
                            "count": {"$sum": 1},
                        }
                    },
                    {
                        "$sort": {
                            "_id.base_number": 1,
                            "count": -1,
                            "_id.next_number": 1,
                        }
                    },
                    {
                        "$group": {
                            "_id": "$_id.base_number",
                            "items": {
                                "$push": {
                                    "number": "$_id.next_number",
                                    "count": "$count",
                                }
                            },
                        }
                    },
                ],
                "summaries": [
                    {
                        "$group": {
                            "_id": "$value",
                            "occurrence_count": {"$sum": 1},
                            "with_next_count": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$and": [
                                                {"$gte": ["$next_value", NUMBER_MIN]},
                                                {"$lte": ["$next_value", NUMBER_MAX]},
                                            ]
                                        },
                                        1,
                                        0,
                                    ]
                                }
                            },
                            "without_next_count": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$and": [
                                                {"$gte": ["$next_value", NUMBER_MIN]},
                                                {"$lte": ["$next_value", NUMBER_MAX]},
                                            ]
                                        },
                                        0,
                                        1,
                                    ]
                                }
                            },
                            "first_occurrence_utc": {"$min": "$timestamp"},
                            "last_occurrence_utc": {"$max": "$timestamp"},
                        }
                    }
                ],
                "history_meta": [
                    {
                        "$group": {
                            "_id": None,
                            "history_count": {"$sum": 1},
                            "first_history_timestamp_utc": {"$min": "$timestamp"},
                            "last_history_timestamp_utc": {"$max": "$timestamp"},
                        }
                    }
                ],
            }
        },
    ]


def build_next_number_ranking_document(
    *,
    roulette_id: str,
    aggregation_result: Dict[str, Any],
    updated_at_utc: datetime,
    interval_seconds: int | None = None,
    source: str = "worker",
) -> Dict[str, Any]:
    ranking_by_base: Dict[int, List[Dict[str, Any]]] = {}
    for row in aggregation_result.get("rankings") or []:
        try:
            base_number = _coerce_base_number(row.get("_id"))
        except ValueError:
            continue
        ranking_by_base[base_number] = list(row.get("items") or [])

    summary_by_base: Dict[int, Dict[str, Any]] = {}
    for row in aggregation_result.get("summaries") or []:
        try:
            base_number = _coerce_base_number(row.get("_id"))
        except ValueError:
            continue
        summary_by_base[base_number] = dict(row)

    numbers: Dict[str, Dict[str, Any]] = {}
    numbers_list: List[Dict[str, Any]] = []
    for base_number in range(NUMBER_MIN, NUMBER_MAX + 1):
        payload = _build_empty_number_payload(base_number)
        summary = summary_by_base.get(base_number, {})
        payload.update(
            {
                "occurrence_count": int(summary.get("occurrence_count") or 0),
                "with_next_count": int(summary.get("with_next_count") or 0),
                "without_next_count": int(summary.get("without_next_count") or 0),
                "first_occurrence_utc": summary.get("first_occurrence_utc"),
                "last_occurrence_utc": summary.get("last_occurrence_utc"),
            }
        )

        with_next_count = max(0, int(payload["with_next_count"]))
        ranking_items: List[Dict[str, Any]] = []
        for index, item in enumerate(ranking_by_base.get(base_number, []), start=1):
            try:
                next_number = _coerce_base_number(item.get("number"))
            except ValueError:
                continue
            count = max(0, int(item.get("count") or 0))
            percentage = round((count / with_next_count) * 100.0, 4) if with_next_count else 0.0
            ranking_items.append(
                {
                    "position": int(index),
                    "number": int(next_number),
                    "count": int(count),
                    "percentage": percentage,
                }
            )
        payload["ranking"] = ranking_items
        numbers[str(base_number)] = payload
        numbers_list.append(payload)

    meta = (aggregation_result.get("history_meta") or [{}])[0] or {}
    return {
        "roulette_id": roulette_id,
        "source": source,
        "version": SERVICE_VERSION,
        "updated_at_utc": updated_at_utc,
        "interval_seconds": interval_seconds,
        "history_count": int(meta.get("history_count") or 0),
        "first_history_timestamp_utc": meta.get("first_history_timestamp_utc"),
        "last_history_timestamp_utc": meta.get("last_history_timestamp_utc"),
        "numbers": numbers,
        "numbers_list": numbers_list,
    }


async def build_next_number_rankings(
    roulette_id: str = DEFAULT_ROULETTE_ID,
    *,
    interval_seconds: int | None = None,
    source: str = "worker",
) -> Dict[str, Any]:
    safe_roulette_id = _coerce_roulette_id(roulette_id)
    cursor = history_coll.aggregate(
        _build_aggregation_pipeline(safe_roulette_id),
        allowDiskUse=True,
    )
    rows = await cursor.to_list(length=1)
    aggregation_result = rows[0] if rows else {}
    return build_next_number_ranking_document(
        roulette_id=safe_roulette_id,
        aggregation_result=aggregation_result,
        updated_at_utc=_utc_now(),
        interval_seconds=interval_seconds,
        source=source,
    )


async def refresh_next_number_rankings(
    roulette_id: str = DEFAULT_ROULETTE_ID,
    *,
    interval_seconds: int | None = None,
    source: str = "worker",
) -> Dict[str, Any]:
    await ensure_next_number_ranking_indexes()
    doc = await build_next_number_rankings(
        roulette_id,
        interval_seconds=interval_seconds,
        source=source,
    )
    await next_number_rankings_coll.update_one(
        {"roulette_id": doc["roulette_id"]},
        {
            "$set": doc,
            "$setOnInsert": {"created_at_utc": doc["updated_at_utc"]},
        },
        upsert=True,
    )
    return doc


async def get_latest_next_number_rankings(roulette_id: str = DEFAULT_ROULETTE_ID) -> Dict[str, Any]:
    safe_roulette_id = _coerce_roulette_id(roulette_id)
    await ensure_next_number_ranking_indexes()
    doc = await next_number_rankings_coll.find_one(
        {"roulette_id": safe_roulette_id},
        {"_id": 0},
    )
    if not doc:
        raise LookupError(f"Ranking de puxadas ainda nao foi gerado para {safe_roulette_id}.")
    return doc


async def get_next_number_ranking_for_number(
    roulette_id: str = DEFAULT_ROULETTE_ID,
    base_number: Any = None,
) -> Dict[str, Any]:
    safe_number = _coerce_base_number(base_number)
    doc = await get_latest_next_number_rankings(roulette_id)
    number_payload = dict((doc.get("numbers") or {}).get(str(safe_number)) or {})
    if not number_payload:
        raise HTTPException(status_code=404, detail="Ranking do numero solicitado nao encontrado.")
    return {
        "roulette_id": doc.get("roulette_id"),
        "updated_at_utc": doc.get("updated_at_utc"),
        "interval_seconds": doc.get("interval_seconds"),
        "history_count": doc.get("history_count"),
        "number": number_payload,
    }
