from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from pymongo import ASCENDING, DESCENDING

from api.core.db import history_coll
from api.helpers.roulettes_list import roulettes
from api.services.base_suggestion import WHEEL_INDEX, WHEEL_ORDER
from api.services.number_day_backtest import build_walk_forward_backtest
from api.services.number_live_signal import build_live_signal
from api.services.number_period_backtest import build_intraday_backtest


router = APIRouter()

DISPLAY_TZ = ZoneInfo("America/Sao_Paulo")
INDEX_ROULETTE_VALUE = "idx_roulette_value"
INDEX_ROULETTE_TS = "history_roulette_ts_desc"
BACKTEST_OUTCOME_HORIZON_MINUTES = 15
BACKTEST_ATTEMPT_SECONDS = 40
LIVE_REFRESH_SECONDS = 60
LIVE_STALE_AFTER_MINUTES = 3

RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}


def _number_color(value: int) -> str:
    if value == 0:
        return "green"
    return "red" if value in RED_NUMBERS else "black"


def _region_numbers(center: int, neighbors_side: int) -> List[int]:
    if center not in WHEEL_INDEX:
        return [center]

    safe_span = max(0, int(neighbors_side))
    center_index = WHEEL_INDEX[center]
    wheel_size = len(WHEEL_ORDER)
    return [
        int(WHEEL_ORDER[(center_index + offset) % wheel_size])
        for offset in range(-safe_span, safe_span + 1)
    ]


def _serialize_number(value: int) -> Dict[str, Any]:
    return {"value": int(value), "color": _number_color(int(value))}


def _parse_hour_minute(value: str) -> tuple[int, int]:
    raw = str(value or "").strip()
    try:
        hour_text, minute_text = raw.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="horario precisa estar no formato HH:MM")

    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise HTTPException(status_code=400, detail="horario precisa estar entre 00:00 e 23:59")

    return hour, minute


def _to_display_timezone(timestamp: Any) -> datetime | None:
    if not isinstance(timestamp, datetime):
        return None

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    return timestamp.astimezone(DISPLAY_TZ)


def _to_utc(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=DISPLAY_TZ)
    return timestamp.astimezone(timezone.utc)


def _format_timestamp(timestamp: datetime) -> str:
    return timestamp.strftime("%d/%m/%Y %H:%M")


def _format_minute_diff(delta: timedelta) -> str:
    minutes = int(round(delta.total_seconds() / 60))
    sign = "+" if minutes > 0 else ""
    return f"{sign}{minutes} min"


def _serialize_item(doc: Dict[str, Any], target_timestamp: datetime) -> Dict[str, Any] | None:
    local_timestamp = _to_display_timezone(doc.get("timestamp"))
    if local_timestamp is None:
        return None

    value = int(doc.get("value"))
    delta = local_timestamp - target_timestamp
    return {
        "id": str(doc.get("_id") or ""),
        "value": value,
        "color": _number_color(value),
        "timestamp": local_timestamp.isoformat(),
        "formatted": _format_timestamp(local_timestamp),
        "time": local_timestamp.strftime("%H:%M"),
        "diff_seconds": int(delta.total_seconds()),
        "diff_minutes": int(round(delta.total_seconds() / 60)),
        "diff_label": _format_minute_diff(delta),
    }


def _circular_wheel_distance(first: int, second: int) -> int:
    first_index = WHEEL_INDEX[first]
    second_index = WHEEL_INDEX[second]
    direct_distance = abs(first_index - second_index)
    return min(direct_distance, len(WHEEL_ORDER) - direct_distance)


def _build_reverse_intersections(
    rankings: List[Dict[str, Any]],
    days_source: List[Dict[str, Any]],
    *,
    neighbors_side: int,
    total_days: int,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    sectors = []

    for first_index, first in enumerate(rankings):
        first_numbers = _region_numbers(int(first["center"]), neighbors_side)
        first_number_set = set(first_numbers)

        for second in rankings[first_index + 1 :]:
            second_numbers = _region_numbers(int(second["center"]), neighbors_side)
            intersection_set = first_number_set.intersection(second_numbers)
            if not intersection_set:
                continue

            intersection_numbers = [
                int(value) for value in WHEEL_ORDER if int(value) in intersection_set
            ]
            days = []
            hit_days = 0
            total_matches = 0

            for day in days_source:
                matches = [
                    item for item in day["items"] if item["value"] in intersection_set
                ]
                if not matches:
                    continue

                hit_days += 1
                total_matches += len(matches)
                days.append(
                    {
                        "day_offset": day["day_offset"],
                        "target": day["target"],
                        "matches": matches,
                    }
                )

            if not hit_days:
                continue

            overlap_rate = len(intersection_numbers) / max(
                1,
                min(len(first_numbers), len(second_numbers)),
            )
            evidence_rate = hit_days / max(1, total_days)
            center_strength = (
                float(first["hit_rate"]) + float(second["hit_rate"])
            ) / 2
            heat_score = round(
                (
                    (evidence_rate * 0.5)
                    + (center_strength * 0.3)
                    + (overlap_rate * 0.2)
                )
                * 100
            )

            centers = [int(first["center"]), int(second["center"])]
            sectors.append(
                {
                    "centers": [_serialize_number(center) for center in centers],
                    "center_values": centers,
                    "wheel_distance": _circular_wheel_distance(*centers),
                    "intersection_numbers": [
                        _serialize_number(value) for value in intersection_numbers
                    ],
                    "intersection_count": len(intersection_numbers),
                    "region_size": len(first_numbers),
                    "overlap_rate": round(overlap_rate, 4),
                    "hit_days": hit_days,
                    "total_days": total_days,
                    "hit_rate": round(evidence_rate, 4),
                    "total_matches": total_matches,
                    "heat_score": heat_score,
                    "days": days,
                }
            )

    sectors.sort(
        key=lambda item: (
            -item["heat_score"],
            -item["hit_days"],
            -item["intersection_count"],
            item["wheel_distance"],
            item["center_values"],
        )
    )

    heat_entries = []
    max_raw_heat = 0.0
    for value in WHEEL_ORDER:
        number = int(value)
        contributing = []
        raw_heat = 0.0

        for ranking in rankings:
            center = int(ranking["center"])
            if number not in _region_numbers(center, neighbors_side):
                continue

            contributing.append(center)
            raw_heat += float(ranking["hit_rate"])

        max_raw_heat = max(max_raw_heat, raw_heat)
        heat_entries.append(
            {
                "number": _serialize_number(number),
                "raw_heat": raw_heat,
                "contributing_centers": contributing,
            }
        )

    wheel_heat = []
    for entry in heat_entries:
        score = (
            round((float(entry["raw_heat"]) / max_raw_heat) * 100)
            if max_raw_heat
            else 0
        )
        wheel_heat.append(
            {
                "number": entry["number"],
                "score": score,
                "contributing_centers": entry["contributing_centers"],
                "center_count": len(entry["contributing_centers"]),
            }
        )

    return sectors, wheel_heat


async def _fetch_base_occurrences(roulette_id: str, value: int, limit: int) -> List[Dict[str, Any]]:
    projection = {"_id": 1, "roulette_id": 1, "roulette_name": 1, "value": 1, "timestamp": 1}
    cursor = (
        history_coll.find({"roulette_id": roulette_id, "value": value}, projection)
        .hint(INDEX_ROULETTE_VALUE)
        .sort("timestamp", DESCENDING)
        .limit(limit)
    )
    return await cursor.to_list(length=limit)


async def _fetch_window_results(
    roulette_id: str,
    *,
    target_timestamp: datetime,
    window_minutes: int,
) -> List[Dict[str, Any]]:
    window = timedelta(minutes=window_minutes)
    return await _fetch_results_between(
        roulette_id,
        start_timestamp=target_timestamp - window,
        end_timestamp=target_timestamp + window,
    )


async def _fetch_results_between(
    roulette_id: str,
    *,
    start_timestamp: datetime,
    end_timestamp: datetime,
    limit: int = 300,
) -> List[Dict[str, Any]]:
    projection = {"_id": 1, "roulette_id": 1, "roulette_name": 1, "value": 1, "timestamp": 1}
    query = {
        "roulette_id": roulette_id,
        "timestamp": {
            "$gte": _to_utc(start_timestamp),
            "$lte": _to_utc(end_timestamp),
        },
    }
    cursor = (
        history_coll.find(query, projection)
        .hint(INDEX_ROULETTE_TS)
        .sort("timestamp", ASCENDING)
    )
    return await cursor.to_list(length=limit)


@router.get("/api/number-day-comparison/roulettes")
async def number_day_comparison_roulettes():
    return [
        {
            "id": str(item.get("slug") or ""),
            "name": str(item.get("name") or item.get("slug") or ""),
            "count": None,
        }
        for item in roulettes
        if str(item.get("slug") or "").strip()
    ]


@router.get("/api/number-day-comparison")
async def number_day_comparison(
    roulette_id: str = Query(..., min_length=1),
    numero: int = Query(..., ge=0, le=36),
    modo: str = Query("numero"),
    vizinhos_lado: int = Query(0, ge=0, le=8),
    janela_minutos: int = Query(3, ge=1, le=15),
    dias_anteriores: int = Query(20, ge=1, le=60),
    limit: int = Query(10, ge=1, le=50),
):
    roulette_id = str(roulette_id or "").strip()
    if not roulette_id:
        raise HTTPException(status_code=400, detail="roulette_id e obrigatorio")

    mode = str(modo or "numero").strip().lower()
    if mode not in {"numero", "regiao"}:
        raise HTTPException(status_code=400, detail="modo precisa ser numero ou regiao")

    target_numbers = [numero]
    if mode == "regiao":
        target_numbers = _region_numbers(numero, vizinhos_lado)
    target_number_set = set(target_numbers)

    try:
        total_occurrences = await history_coll.count_documents(
            {"roulette_id": roulette_id, "value": numero},
            hint=INDEX_ROULETTE_VALUE,
        )
        base_docs = await _fetch_base_occurrences(roulette_id, numero, limit)

        comparisons = []
        for base_doc in base_docs:
            base_timestamp = _to_display_timezone(base_doc.get("timestamp"))
            if base_timestamp is None:
                continue

            days = []
            for day_offset in range(1, dias_anteriores + 1):
                target_timestamp = base_timestamp - timedelta(days=day_offset)
                window_docs = await _fetch_window_results(
                    roulette_id,
                    target_timestamp=target_timestamp,
                    window_minutes=janela_minutos,
                )
                items = [
                    item
                    for item in (_serialize_item(doc, target_timestamp) for doc in window_docs)
                    if item is not None
                ]
                matches = [item for item in items if item["value"] in target_number_set]

                days.append(
                    {
                        "day_offset": day_offset,
                        "target": {
                            "timestamp": target_timestamp.isoformat(),
                            "formatted": _format_timestamp(target_timestamp),
                            "time": target_timestamp.strftime("%H:%M"),
                        },
                        "status": "hit" if matches else "miss",
                        "matches": matches,
                        "alternatives": [] if matches else items,
                    }
                )

            comparisons.append(
                {
                    "base": {
                        "id": str(base_doc.get("_id") or ""),
                        "value": int(base_doc.get("value")),
                        "color": _number_color(int(base_doc.get("value"))),
                        "timestamp": base_timestamp.isoformat(),
                        "formatted": _format_timestamp(base_timestamp),
                        "time": base_timestamp.strftime("%H:%M"),
                    },
                    "days": days,
                }
            )

        return {
            "roulette_id": roulette_id,
            "numero": numero,
            "modo": mode,
            "vizinhos_lado": vizinhos_lado,
            "target_numbers": [_serialize_number(value) for value in target_numbers],
            "janela_minutos": janela_minutos,
            "dias_anteriores": dias_anteriores,
            "limit": limit,
            "total_occurrences": int(total_occurrences),
            "comparisons": comparisons,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/number-day-comparison/reverse")
async def number_day_comparison_reverse(
    roulette_id: str = Query(..., min_length=1),
    horario: str = Query(..., min_length=4, max_length=5),
    vizinhos_lado: int = Query(3, ge=0, le=8),
    janela_minutos: int = Query(3, ge=1, le=15),
    dias_anteriores: int = Query(10, ge=1, le=60),
    top: int = Query(10, ge=1, le=37),
):
    roulette_id = str(roulette_id or "").strip()
    if not roulette_id:
        raise HTTPException(status_code=400, detail="roulette_id e obrigatorio")

    hour, minute = _parse_hour_minute(horario)
    today = datetime.now(DISPLAY_TZ).date()

    try:
        days_source = []
        for day_offset in range(1, dias_anteriores + 1):
            target_date = today - timedelta(days=day_offset)
            target_timestamp = datetime(
                target_date.year,
                target_date.month,
                target_date.day,
                hour,
                minute,
                tzinfo=DISPLAY_TZ,
            )
            window_docs = await _fetch_window_results(
                roulette_id,
                target_timestamp=target_timestamp,
                window_minutes=janela_minutos,
            )
            items = [
                item
                for item in (_serialize_item(doc, target_timestamp) for doc in window_docs)
                if item is not None
            ]
            days_source.append(
                {
                    "day_offset": day_offset,
                    "target": {
                        "timestamp": target_timestamp.isoformat(),
                        "formatted": _format_timestamp(target_timestamp),
                        "time": target_timestamp.strftime("%H:%M"),
                    },
                    "items": items,
                }
            )

        rankings = []
        for center in range(37):
            target_numbers = _region_numbers(center, vizinhos_lado)
            target_number_set = set(target_numbers)
            days = []
            hit_days = 0
            total_matches = 0

            for day in days_source:
                matches = [item for item in day["items"] if item["value"] in target_number_set]
                if matches:
                    hit_days += 1
                    total_matches += len(matches)

                days.append(
                    {
                        "day_offset": day["day_offset"],
                        "target": day["target"],
                        "status": "hit" if matches else "miss",
                        "matches": matches,
                        "alternatives": [] if matches else day["items"],
                    }
                )

            rankings.append(
                {
                    "center": center,
                    "center_number": _serialize_number(center),
                    "target_numbers": [_serialize_number(value) for value in target_numbers],
                    "hit_days": hit_days,
                    "total_days": dias_anteriores,
                    "hit_rate": round(hit_days / dias_anteriores, 4),
                    "total_matches": total_matches,
                    "days": days,
                }
            )

        rankings.sort(key=lambda item: (-item["hit_days"], -item["total_matches"], item["center"]))
        selected_rankings = rankings[:top]
        hot_sectors, wheel_heat = _build_reverse_intersections(
            selected_rankings,
            days_source,
            neighbors_side=vizinhos_lado,
            total_days=dias_anteriores,
        )

        return {
            "roulette_id": roulette_id,
            "modo": "reversa",
            "horario": f"{hour:02d}:{minute:02d}",
            "vizinhos_lado": vizinhos_lado,
            "janela_minutos": janela_minutos,
            "dias_anteriores": dias_anteriores,
            "top": top,
            "rankings": selected_rankings,
            "hot_sectors": hot_sectors[:top],
            "wheel_heat": wheel_heat,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/number-day-comparison/backtest")
async def number_day_comparison_backtest(
    roulette_id: str = Query(..., min_length=1),
    horario: str = Query(..., min_length=4, max_length=5),
    dias_anteriores: int = Query(10, ge=1, le=60),
    dias_teste: int = Query(90, ge=1, le=365),
    janela_minutos: int = Query(3, ge=1, le=15),
    vizinhos_lado: int = Query(3, ge=0, le=8),
    centros_aposta: int = Query(2, ge=1, le=37),
    vizinhos_aposta: int = Query(3, ge=0, le=8),
    tentativas: int = Query(5, ge=1, le=5),
):
    roulette_id = str(roulette_id or "").strip()
    if not roulette_id:
        raise HTTPException(status_code=400, detail="roulette_id e obrigatorio")

    hour, minute = _parse_hour_minute(horario)
    today = datetime.now(DISPLAY_TZ).date()
    total_calendar_days = dias_anteriores + dias_teste
    semaphore = asyncio.Semaphore(12)

    async def fetch_day(day_offset: int) -> tuple[int, Dict[str, Any]]:
        target_date = today - timedelta(days=day_offset)
        target_timestamp = datetime(
            target_date.year,
            target_date.month,
            target_date.day,
            hour,
            minute,
            tzinfo=DISPLAY_TZ,
        )
        start_timestamp = target_timestamp - timedelta(minutes=janela_minutos)
        end_timestamp = target_timestamp + timedelta(
            minutes=BACKTEST_OUTCOME_HORIZON_MINUTES
        )

        async with semaphore:
            docs = await _fetch_results_between(
                roulette_id,
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
            )

        items = [
            item
            for item in (_serialize_item(doc, target_timestamp) for doc in docs)
            if item is not None
        ]
        training_window_seconds = janela_minutos * 60
        return day_offset, {
            "target": {
                "timestamp": target_timestamp.isoformat(),
                "formatted": _format_timestamp(target_timestamp),
                "time": target_timestamp.strftime("%H:%M"),
            },
            "training_items": [
                item
                for item in items
                if abs(int(item["diff_seconds"])) <= training_window_seconds
            ],
            "outcome_items": [
                item
                for item in items
                if 0
                <= int(item["diff_seconds"])
                <= BACKTEST_OUTCOME_HORIZON_MINUTES * 60
            ],
        }

    try:
        fetched_days = await asyncio.gather(
            *(fetch_day(day_offset) for day_offset in range(1, total_calendar_days + 1))
        )
        days_by_offset = dict(fetched_days)
        backtest = build_walk_forward_backtest(
            days_by_offset,
            training_days=dias_anteriores,
            test_days=dias_teste,
            analysis_neighbors=vizinhos_lado,
            bet_neighbors=vizinhos_aposta,
            centers_count=centros_aposta,
            attempts_limit=tentativas,
        )

        return {
            "roulette_id": roulette_id,
            "modo": "validacao",
            "horario": f"{hour:02d}:{minute:02d}",
            "dias_anteriores": dias_anteriores,
            "dias_teste": dias_teste,
            "janela_minutos": janela_minutos,
            "vizinhos_lado": vizinhos_lado,
            "centros_aposta": centros_aposta,
            "vizinhos_aposta": vizinhos_aposta,
            "tentativas": tentativas,
            "outcome_horizon_minutes": BACKTEST_OUTCOME_HORIZON_MINUTES,
            **backtest,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/number-day-comparison/backtest-period")
async def number_day_comparison_backtest_period(
    roulette_id: str = Query(..., min_length=1),
    data_teste: str = Query(..., min_length=10, max_length=10),
    horario: str = Query(..., min_length=4, max_length=5),
    minutos_teste: int = Query(60, ge=1, le=720),
    dias_anteriores: int = Query(10, ge=1, le=60),
    janela_minutos: int = Query(3, ge=1, le=15),
    vizinhos_lado: int = Query(3, ge=0, le=8),
    centros_aposta: int = Query(2, ge=1, le=37),
    vizinhos_aposta: int = Query(3, ge=0, le=8),
    tentativas: int = Query(5, ge=1, le=5),
):
    roulette_id = str(roulette_id or "").strip()
    if not roulette_id:
        raise HTTPException(status_code=400, detail="roulette_id e obrigatorio")

    try:
        selected_date = datetime.strptime(data_teste, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="data_teste precisa estar no formato AAAA-MM-DD")

    today = datetime.now(DISPLAY_TZ).date()
    if selected_date > today:
        raise HTTPException(status_code=400, detail="data_teste nao pode estar no futuro")

    hour, minute = _parse_hour_minute(horario)
    start_timestamp = datetime(
        selected_date.year,
        selected_date.month,
        selected_date.day,
        hour,
        minute,
        tzinfo=DISPLAY_TZ,
    )
    semaphore = asyncio.Semaphore(12)

    async def fetch_period_day(day_offset: int) -> tuple[int, List[Dict[str, Any]]]:
        day_start = start_timestamp - timedelta(days=day_offset)
        range_start = day_start - timedelta(minutes=janela_minutos)
        range_end = day_start + timedelta(
            minutes=minutos_teste + BACKTEST_OUTCOME_HORIZON_MINUTES
        )

        async with semaphore:
            docs = await _fetch_results_between(
                roulette_id,
                start_timestamp=range_start,
                end_timestamp=range_end,
                limit=5000,
            )

        items = [
            item
            for item in (_serialize_item(doc, day_start) for doc in docs)
            if item is not None
        ]
        return day_offset, items

    try:
        fetched_days = await asyncio.gather(
            *(fetch_period_day(day_offset) for day_offset in range(dias_anteriores + 1))
        )
        days_source = dict(fetched_days)
        backtest = build_intraday_backtest(
            days_source,
            start_timestamp=start_timestamp,
            period_minutes=minutos_teste,
            training_days=dias_anteriores,
            window_minutes=janela_minutos,
            analysis_neighbors=vizinhos_lado,
            bet_neighbors=vizinhos_aposta,
            centers_count=centros_aposta,
            attempts_limit=tentativas,
            attempt_seconds=BACKTEST_ATTEMPT_SECONDS,
            outcome_horizon_minutes=BACKTEST_OUTCOME_HORIZON_MINUTES,
        )

        return {
            "roulette_id": roulette_id,
            "modo": "validacao_periodo",
            "data_teste": selected_date.isoformat(),
            "data_teste_formatada": selected_date.strftime("%d/%m/%Y"),
            "horario": f"{hour:02d}:{minute:02d}",
            "minutos_teste": minutos_teste,
            "dias_anteriores": dias_anteriores,
            "janela_minutos": janela_minutos,
            "vizinhos_lado": vizinhos_lado,
            "centros_aposta": centros_aposta,
            "vizinhos_aposta": vizinhos_aposta,
            "tentativas": tentativas,
            "segundos_tentativa": BACKTEST_ATTEMPT_SECONDS,
            "outcome_horizon_minutes": BACKTEST_OUTCOME_HORIZON_MINUTES,
            **backtest,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/number-day-comparison/live")
async def number_day_comparison_live(
    roulette_id: str = Query(..., min_length=1),
    dias_anteriores: int = Query(10, ge=1, le=60),
    janela_minutos: int = Query(3, ge=1, le=15),
    vizinhos_lado: int = Query(3, ge=0, le=8),
    centros_aposta: int = Query(2, ge=1, le=37),
    vizinhos_aposta: int = Query(3, ge=0, le=8),
    bloqueio_minutos: int = Query(5, ge=1, le=30),
):
    roulette_id = str(roulette_id or "").strip()
    if not roulette_id:
        raise HTTPException(status_code=400, detail="roulette_id e obrigatorio")

    now = datetime.now(DISPLAY_TZ)
    analysis_timestamp = now.replace(second=0, microsecond=0)

    async def fetch_training_day(day_offset: int) -> Dict[str, Any]:
        target_timestamp = analysis_timestamp - timedelta(days=day_offset)
        docs = await _fetch_window_results(
            roulette_id,
            target_timestamp=target_timestamp,
            window_minutes=janela_minutos,
        )
        items = [
            item
            for item in (_serialize_item(doc, target_timestamp) for doc in docs)
            if item is not None
        ]
        return {
            "day_offset": day_offset,
            "target": {
                "timestamp": target_timestamp.isoformat(),
                "formatted": _format_timestamp(target_timestamp),
                "time": target_timestamp.strftime("%H:%M"),
            },
            "items": items,
        }

    async def fetch_recent_results() -> List[Dict[str, Any]]:
        recent_horizon = max(bloqueio_minutos, LIVE_STALE_AFTER_MINUTES)
        docs = await _fetch_results_between(
            roulette_id,
            start_timestamp=now - timedelta(minutes=recent_horizon),
            end_timestamp=now,
            limit=500,
        )
        return [
            item
            for item in (_serialize_item(doc, now) for doc in docs)
            if item is not None and int(item["diff_seconds"]) <= 0
        ]

    try:
        fetched = await asyncio.gather(
            *(fetch_training_day(day_offset) for day_offset in range(1, dias_anteriores + 1)),
            fetch_recent_results(),
        )
        training_days_source = fetched[:-1]
        recent_items = fetched[-1]
        signal = build_live_signal(
            training_days_source,
            recent_items,
            training_days=dias_anteriores,
            analysis_neighbors=vizinhos_lado,
            bet_neighbors=vizinhos_aposta,
            centers_count=centros_aposta,
            blocking_minutes=bloqueio_minutos,
            stale_after_minutes=LIVE_STALE_AFTER_MINUTES,
        )
        next_update = now + timedelta(seconds=LIVE_REFRESH_SECONDS)

        return {
            "roulette_id": roulette_id,
            "modo": "ao_vivo",
            "generated_at": now.isoformat(),
            "generated_at_formatted": now.strftime("%d/%m/%Y %H:%M:%S"),
            "analysis_time": analysis_timestamp.strftime("%H:%M"),
            "next_update_at": next_update.isoformat(),
            "next_update_at_formatted": next_update.strftime("%H:%M:%S"),
            "refresh_seconds": LIVE_REFRESH_SECONDS,
            "stale_after_minutes": LIVE_STALE_AFTER_MINUTES,
            "dias_anteriores": dias_anteriores,
            "janela_minutos": janela_minutos,
            "vizinhos_lado": vizinhos_lado,
            "centros_aposta": centros_aposta,
            "vizinhos_aposta": vizinhos_aposta,
            "bloqueio_minutos": bloqueio_minutos,
            **signal,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
