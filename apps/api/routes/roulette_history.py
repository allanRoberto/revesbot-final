from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

import pytz
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from api.core.config import settings
from api.core.db import history_coll
from api.helpers.roulettes_list import roulettes


router = APIRouter()
base_dir = os.path.dirname(os.path.dirname(__file__))
templates_dir = os.path.join(base_dir, "templates")


def _serialize_history_item(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "_id": str(doc.get("_id")) if doc.get("_id") is not None else None,
        "value": int(doc.get("value")),
        "roulette_id": str(doc.get("roulette_id") or ""),
        "roulette_name": str(doc.get("roulette_name") or doc.get("roulette_id") or ""),
        "timestamp": doc.get("timestamp").isoformat() if isinstance(doc.get("timestamp"), datetime) else None,
    }


def get_color_class(num: int) -> str:
    if num == 0:
        return "green"
    red_numbers = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
    return "red" if num in red_numbers else "black"


def _template_feature_context() -> Dict[str, Any]:
    return {
        "bot_automation_enabled": bool(settings.bot_automation_enabled),
        "bot_api_url": settings.bot_api_url,
        "bot_health_url": settings.bot_health_url,
        "pattern_metrics_enabled": bool(settings.pattern_metrics_enabled),
    }


@router.get("/api/roulettes-list")
async def get_all_roulettes():
    """
    Lista todas as roletas disponíveis no banco
    """
    try:
        roulettes_list = await history_coll.distinct("roulette_id")

        roulette_info = []
        for roulette_id in roulettes_list:
            count = await history_coll.count_documents({"roulette_id": roulette_id})
            roulette_info.append({
                "id": roulette_id,
                "name": roulette_id.replace("-", " ").title(),
                "count": count,
            })

        roulette_info.sort(key=lambda x: x["count"], reverse=True)
        return roulette_info

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history-detailed/{slug}")
async def get_history_detailed(
    slug: str,
    request: Request,
    limit: int = 500,
    start_date: str = None,
    end_date: str = None,
    start_hour: int = None,
    end_hour: int = None,
):
    """
    Retorna histórico detalhado da roleta com timestamps.
    """
    try:
        max_limit = 50000
        limit = min(limit, max_limit)

        tz_br = pytz.timezone("America/Sao_Paulo")
        filter_query = {"roulette_id": slug}

        date_filter = {}
        if start_date:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            start_dt_br = tz_br.localize(start_dt)
            date_filter["$gte"] = start_dt_br.astimezone(pytz.utc)

        if end_date:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            end_dt = end_dt.replace(hour=23, minute=59, second=59)
            end_dt_br = tz_br.localize(end_dt)
            date_filter["$lte"] = end_dt_br.astimezone(pytz.utc)

        if date_filter:
            filter_query["timestamp"] = date_filter

        cursor = (
            history_coll
            .find(filter_query)
            .sort("timestamp", -1)
            .limit(limit)
        )

        docs = await cursor.to_list(length=limit)

        processed_results = []
        for doc in docs:
            timestamp = doc["timestamp"]

            if timestamp.tzinfo is None:
                timestamp = pytz.utc.localize(timestamp)
            br_time = timestamp.astimezone(tz_br)

            if start_hour is not None and br_time.hour < start_hour:
                continue
            if end_hour is not None and br_time.hour > end_hour:
                continue

            processed_results.append({
                "_id": str(doc["_id"]) if doc.get("_id") is not None else None,
                "roulette_id": doc["roulette_id"],
                "roulette_name": doc["roulette_name"],
                "value": doc["value"],
                "timestamp": timestamp.isoformat(),
                "timestamp_br": br_time.isoformat(),
                "date": br_time.strftime("%Y-%m-%d"),
                "time": br_time.strftime("%H:%M:%S"),
                "hour": br_time.hour,
                "minute": br_time.minute,
                "day_of_week": br_time.strftime("%A"),
                "formatted": br_time.strftime("%d/%m/%Y %H:%M:%S"),
            })

        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            roulette = next((r for r in roulettes if r.get("slug") == slug), {"name": slug})
            from fastapi.templating import Jinja2Templates

            templates = Jinja2Templates(directory=templates_dir)
            return templates.TemplateResponse(
                "api.html",
                {
                    "request": request,
                    "slug": slug,
                    "numbers": [r["value"] for r in processed_results],
                    "history_entries": processed_results,
                    "detailed_results": processed_results,
                    "roulette": roulette,
                    "all_roulettes": roulettes,
                    "get_color_class": get_color_class,
                    "filters": {
                        "start_date": start_date,
                        "end_date": end_date,
                        "start_hour": start_hour,
                        "end_hour": end_hour,
                    },
                    **_template_feature_context(),
                },
            )

        return processed_results

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/{slug}")
async def get_history(slug: str, request: Request, limit: int = 2000):
    """
    Retorna histórico da roleta.
    - Param `limit`: número de resultados (default=2000)
    - Mais recente sempre vem primeiro.
    """
    try:
        max_limit = 50000
        limit = min(limit, max_limit)

        cursor = (
            history_coll
            .find({"roulette_id": slug})
            .sort("timestamp", -1)
            .limit(limit)
        )

        docs = await cursor.to_list(length=limit)
        numbers = [doc["value"] for doc in docs]
        history_entries = [_serialize_history_item(dict(doc)) for doc in docs]

        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            roulette = next((r for r in roulettes if r.get("slug") == slug), {"name": slug})
            from fastapi.templating import Jinja2Templates

            templates = Jinja2Templates(directory=templates_dir)
            return templates.TemplateResponse(
                "api.html",
                {
                    "request": request,
                    "slug": slug,
                    "numbers": numbers,
                    "history_entries": history_entries,
                    "roulette": roulette,
                    "all_roulettes": roulettes,
                    "get_color_class": get_color_class,
                    **_template_feature_context(),
                },
            )

        return {"results": numbers, "items": history_entries}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
