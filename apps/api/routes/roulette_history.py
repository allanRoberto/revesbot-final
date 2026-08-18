from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytz
from fastapi import APIRouter, HTTPException, Request
from fastapi.templating import Jinja2Templates

from api.core.runtime_db import history_coll
from api.helpers.active_roulettes import ACTIVE_ROULETTE_BY_SLUG, ACTIVE_ROULETTES


router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")
tz_br = pytz.timezone("America/Sao_Paulo")

_roulette_list_cache: tuple[float, list[dict[str, Any]]] | None = None


def _bounded_limit(limit: int) -> int:
    return max(1, min(limit, 50_000))


def _validate_slug(slug: str) -> None:
    if slug not in ACTIVE_ROULETTE_BY_SLUG:
        raise HTTPException(status_code=404, detail="Roleta não monitorada")


def _serialize_history_item(doc: dict[str, Any]) -> dict[str, Any]:
    timestamp = doc.get("timestamp")
    captured_at = doc.get("captured_at")
    return {
        "_id": str(doc.get("_id")) if doc.get("_id") is not None else None,
        "value": int(doc.get("value")),
        "roulette_id": str(doc.get("roulette_id") or ""),
        "roulette_name": str(doc.get("roulette_name") or doc.get("roulette_id") or ""),
        "external_game_id": doc.get("external_game_id"),
        "timestamp": timestamp.isoformat() if isinstance(timestamp, datetime) else None,
        "captured_at": captured_at.isoformat() if isinstance(captured_at, datetime) else None,
        "timestamp_source": doc.get("timestamp_source"),
        "recovered": bool(doc.get("recovered", False)),
        "slots": doc.get("slots") or [],
        "winning_multiplier": doc.get("winning_multiplier"),
    }


def _html_response(request: Request, slug: str, filters: dict[str, Any] | None = None):
    roulette = ACTIVE_ROULETTE_BY_SLUG.get(slug, {"slug": slug, "name": slug})
    return templates.TemplateResponse(
        request=request,
        name="history_minimal.html",
        context={
            "slug": slug,
            "roulette": roulette,
            "all_roulettes": ACTIVE_ROULETTES,
            "filters": filters or {},
        },
    )


@router.get("/api/roulettes-list")
async def get_all_roulettes():
    global _roulette_list_cache

    now = time.monotonic()
    if _roulette_list_cache and now - _roulette_list_cache[0] < 30:
        return _roulette_list_cache[1]

    pipeline = [
        {"$match": {"roulette_id": {"$in": list(ACTIVE_ROULETTE_BY_SLUG)}}},
        {"$group": {"_id": "$roulette_id", "count": {"$sum": 1}}},
    ]
    try:
        counts = {row["_id"]: row["count"] async for row in history_coll.aggregate(pipeline)}
        result = [
            {
                "id": roulette["slug"],
                "name": roulette["name"],
                "count": counts.get(roulette["slug"], 0),
            }
            for roulette in ACTIVE_ROULETTES
        ]
        result.sort(key=lambda item: (-item["count"], item["name"]))
        _roulette_list_cache = (now, result)
        return result
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Banco de dados indisponível") from exc


@router.get("/history-detailed/{slug}")
async def get_history_detailed(
    slug: str,
    request: Request,
    limit: int = 500,
    start_date: str | None = None,
    end_date: str | None = None,
    start_hour: int | None = None,
    end_hour: int | None = None,
):
    _validate_slug(slug)
    limit = _bounded_limit(limit)

    if start_hour is not None and not 0 <= start_hour <= 23:
        raise HTTPException(status_code=422, detail="start_hour deve estar entre 0 e 23")
    if end_hour is not None and not 0 <= end_hour <= 23:
        raise HTTPException(status_code=422, detail="end_hour deve estar entre 0 e 23")

    query: dict[str, Any] = {"roulette_id": slug}
    date_filter: dict[str, datetime] = {}
    try:
        if start_date:
            start = tz_br.localize(datetime.strptime(start_date, "%Y-%m-%d"))
            date_filter["$gte"] = start.astimezone(pytz.utc)
        if end_date:
            end = datetime.strptime(end_date, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, microsecond=999999
            )
            date_filter["$lte"] = tz_br.localize(end).astimezone(pytz.utc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Data inválida; use AAAA-MM-DD") from exc

    if date_filter:
        query["timestamp"] = date_filter

    try:
        docs = await history_coll.find(query).sort("timestamp", -1).limit(limit).to_list(length=limit)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Banco de dados indisponível") from exc

    results: list[dict[str, Any]] = []
    for doc in docs:
        timestamp = doc.get("timestamp")
        if not isinstance(timestamp, datetime):
            continue
        if timestamp.tzinfo is None:
            timestamp = pytz.utc.localize(timestamp)
        local_time = timestamp.astimezone(tz_br)
        if start_hour is not None and local_time.hour < start_hour:
            continue
        if end_hour is not None and local_time.hour > end_hour:
            continue

        item = _serialize_history_item(doc)
        item.update(
            {
                "timestamp": timestamp.isoformat(),
                "timestamp_br": local_time.isoformat(),
                "date": local_time.strftime("%Y-%m-%d"),
                "time": local_time.strftime("%H:%M:%S"),
                "hour": local_time.hour,
                "minute": local_time.minute,
                "day_of_week": local_time.strftime("%A"),
                "formatted": local_time.strftime("%d/%m/%Y %H:%M:%S"),
            }
        )
        results.append(item)

    if "text/html" in request.headers.get("accept", ""):
        return _html_response(
            request,
            slug,
            {
                "start_date": start_date,
                "end_date": end_date,
                "start_hour": start_hour,
                "end_hour": end_hour,
            },
        )
    return results


@router.get("/history/{slug}")
async def get_history(slug: str, request: Request, limit: int = 2_000):
    _validate_slug(slug)
    if "text/html" in request.headers.get("accept", ""):
        return _html_response(request, slug)

    limit = _bounded_limit(limit)
    try:
        docs = await history_coll.find({"roulette_id": slug}).sort("timestamp", -1).limit(limit).to_list(length=limit)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Banco de dados indisponível") from exc

    items = [_serialize_history_item(doc) for doc in docs]
    return {"results": [item["value"] for item in items], "items": items}


@router.get("/history-app/{slug}")
async def get_history_app(slug: str, limit: int = 2_000):
    _validate_slug(slug)
    limit = _bounded_limit(limit)
    try:
        docs = await history_coll.find({"roulette_id": slug}).sort("timestamp", -1).limit(limit).to_list(length=limit)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Banco de dados indisponível") from exc
    return {"results": [int(doc["value"]) for doc in docs]}
