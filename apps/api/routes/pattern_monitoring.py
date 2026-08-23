from __future__ import annotations

import json
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from pymongo import ASCENDING, DESCENDING

from api.core.redis_client import get_redis_client
from api.core.runtime_db import history_db


router = APIRouter()
api_dir = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=api_dir / "templates")
patterns_coll = history_db["patterns"]
signals_coll = history_db["pattern_signals"]
states_coll = history_db["pattern_states"]
redis_client = get_redis_client()
tz_br = ZoneInfo("America/Sao_Paulo")


def _json_default(value: Any):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def _serialize(value: Any) -> Any:
    return json.loads(json.dumps(value, default=_json_default, ensure_ascii=False))


async def _pattern_or_404(pattern_key: str) -> dict[str, Any]:
    document = await patterns_coll.find_one({"key": pattern_key, "enabled": True})
    if not document:
        raise HTTPException(status_code=404, detail="Pattern nao encontrado ou inativo")
    return document


async def _mongo_dashboard(pattern_key: str) -> dict[str, Any]:
    pipeline = [
        {"$match": {"pattern_key": pattern_key}},
        {
            "$group": {
                "_id": {"status": "$status", "roulette_id": "$roulette_id"},
                "count": {"$sum": 1},
                "profit": {"$sum": {"$ifNull": ["$financial.net_profit", 0]}},
                "wagered": {"$sum": {"$ifNull": ["$financial.total_wagered", 0]}},
            }
        },
    ]
    grouped: dict[str, dict[str, float | int]] = {}
    by_roulette: dict[str, dict[str, float | int]] = {}
    async for row in signals_coll.aggregate(pipeline):
        status = str(row.get("_id", {}).get("status") or "unknown")
        roulette_id = str(row.get("_id", {}).get("roulette_id") or "unknown")
        count = int(row.get("count") or 0)
        row_profit = float(row.get("profit") or 0)
        row_wagered = float(row.get("wagered") or 0)
        bucket = grouped.setdefault(status, {"count": 0, "profit": 0.0, "wagered": 0.0})
        bucket["count"] += count
        bucket["profit"] += row_profit
        bucket["wagered"] += row_wagered
        table = by_roulette.setdefault(
            roulette_id,
            {"active": 0, "won": 0, "lost": 0, "resolved": 0, "profit": 0.0, "wagered": 0.0},
        )
        if status in {"active", "won", "lost"}:
            table[status] += count
        if status in {"won", "lost"}:
            table["resolved"] += count
            table["profit"] += row_profit
            table["wagered"] += row_wagered
    for table in by_roulette.values():
        table["assertiveness"] = table["won"] / table["resolved"] if table["resolved"] else 0.0
        table["roi_on_wagered"] = table["profit"] / table["wagered"] if table["wagered"] else 0.0
    won = int(grouped.get("won", {}).get("count") or 0)
    lost = int(grouped.get("lost", {}).get("count") or 0)
    resolved = won + lost
    profit = sum(float(grouped.get(status, {}).get("profit") or 0) for status in ("won", "lost"))
    wagered = sum(float(grouped.get(status, {}).get("wagered") or 0) for status in ("won", "lost"))
    active = await signals_coll.find(
        {"pattern_key": pattern_key, "status": "active"}
    ).sort("created_at", DESCENDING).to_list(length=500)
    runtime = await states_coll.find_one(
        {"pattern_key": pattern_key, "roulette_id": "__runtime__"}
    )
    return _serialize(
        {
            "pattern_key": pattern_key,
            "generated_at": datetime.now(timezone.utc),
            "runtime": runtime or {},
            "counts": {
                "active": len(active),
                "won": won,
                "lost": lost,
                "resolved": resolved,
                "skipped_outside_schedule": int(
                    grouped.get("skipped_outside_schedule", {}).get("count") or 0
                ),
                "cancelled_gap": int(grouped.get("cancelled_gap", {}).get("count") or 0),
            },
            "assertiveness": won / resolved if resolved else 0.0,
            "profit": profit,
            "wagered": wagered,
            "roi_on_wagered": profit / wagered if wagered else 0.0,
            "by_roulette": by_roulette,
            "active_signals": active,
        }
    )


async def _cache_dashboard(pattern_key: str, dashboard: dict[str, Any]) -> None:
    try:
        await redis_client.setex(
            f"patterns:{pattern_key}:dashboard",
            180,
            json.dumps(dashboard, ensure_ascii=False),
        )
    except Exception:
        pass


@router.get("/patterns/{pattern_key}", response_class=HTMLResponse)
async def pattern_page(request: Request, pattern_key: str):
    pattern = await _pattern_or_404(pattern_key)
    return templates.TemplateResponse(
        request=request,
        name="pattern_monitoring.html",
        context={
            "pattern_key": pattern_key,
            "pattern_name": pattern.get("name") or pattern_key,
            "asset_version": "1",
        },
    )


@router.get("/api/patterns")
async def list_patterns() -> dict[str, Any]:
    documents = await patterns_coll.find(
        {"enabled": True},
        {
            "key": 1,
            "name": 1,
            "version": 1,
            "description": 1,
            "required_history": 1,
            "max_attempts": 1,
            "roulette_ids": 1,
            "schedules": 1,
            "default_chip_profile": 1,
            "ui_schema": 1,
        },
    ).sort("name", ASCENDING).to_list(length=500)
    return {"patterns": _serialize(documents)}


@router.get("/api/patterns/{pattern_key}/dashboard")
async def pattern_dashboard(pattern_key: str, refresh: bool = False) -> dict[str, Any]:
    await _pattern_or_404(pattern_key)
    if not refresh:
        try:
            cached = await redis_client.get(f"patterns:{pattern_key}:dashboard")
            if cached:
                payload = json.loads(cached)
                payload["source"] = "redis"
                return payload
        except Exception:
            pass
    dashboard = await _mongo_dashboard(pattern_key)
    dashboard["source"] = "mongodb"
    await _cache_dashboard(pattern_key, dashboard)
    return dashboard


@router.get("/api/patterns/{pattern_key}/signals")
async def list_pattern_signals(
    pattern_key: str,
    roulette_id: str | None = None,
    status: str | None = None,
    eligible_only: bool = True,
    bet_count: int | None = Query(None, ge=1, le=37),
    trigger_hour: int | None = Query(None, ge=0, le=23),
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(100, ge=1, le=1000),
    skip: int = Query(0, ge=0),
) -> dict[str, Any]:
    pattern = await _pattern_or_404(pattern_key)
    query: dict[str, Any] = {"pattern_key": pattern_key}
    if roulette_id:
        if roulette_id not in pattern.get("roulette_ids", []):
            raise HTTPException(status_code=422, detail="Mesa nao configurada no pattern")
        query["roulette_id"] = roulette_id
    if status and status != "all":
        query["status"] = status
    if eligible_only:
        query["eligible_hour"] = True
    if bet_count is not None:
        query["bet_count"] = bet_count
    if trigger_hour is not None:
        query["trigger_hour_br"] = trigger_hour
    created_filter: dict[str, datetime] = {}
    if start_date:
        created_filter["$gte"] = datetime.combine(
            start_date, datetime_time.min, tzinfo=tz_br
        ).astimezone(timezone.utc)
    if end_date:
        created_filter["$lt"] = datetime.combine(
            end_date + timedelta(days=1), datetime_time.min, tzinfo=tz_br
        ).astimezone(timezone.utc)
    if created_filter:
        query["trigger_timestamp"] = created_filter
    total = await signals_coll.count_documents(query)
    documents = await signals_coll.find(query).sort(
        "created_at", DESCENDING
    ).skip(skip).limit(limit).to_list(length=limit)
    return {
        "pattern": _serialize(pattern),
        "total": total,
        "skip": skip,
        "limit": limit,
        "signals": _serialize(documents),
    }


class SimulationRequest(BaseModel):
    starting_bankroll: float = Field(1000, gt=0)
    attempt_values: list[float] = Field(default_factory=lambda: [2.5, 1.5, 1.5, 1.0])
    roulette_id: str | None = None
    bet_count: int | None = Field(None, ge=1, le=37)
    limit: int = Field(20_000, ge=1, le=50_000)


def simulate_bankroll(
    signals: list[dict[str, Any]],
    *,
    starting_bankroll: float,
    attempt_values: list[float],
) -> dict[str, Any]:
    chips = [float(value) for value in attempt_values]
    if not chips or any(value <= 0 for value in chips):
        raise ValueError("Todos os valores de tentativa devem ser maiores que zero")
    current = float(starting_bankroll)
    peak = current
    minimum = current
    maximum = current
    max_drawdown = 0.0
    wins = 0
    losses = 0
    total_wagered = 0.0
    total_profit = 0.0
    points = [{"index": 0, "bankroll": current, "profit": 0.0, "status": "start"}]

    for signal in signals:
        bet_count = int(signal.get("bet_count") or len(signal.get("bet_numbers") or []))
        payout = int(signal.get("payout") or 36)
        won_at = int(signal.get("won_at_attempt") or 0)
        won_inside_horizon = signal.get("status") == "won" and 1 <= won_at <= len(chips)
        used = won_at if won_inside_horizon else len(chips)
        wagered = bet_count * sum(chips[:used])
        if won_inside_horizon:
            gross = payout * chips[won_at - 1]
            profit = gross - wagered
            wins += 1
            status = "won"
        else:
            profit = -wagered
            losses += 1
            status = "lost"
        current += profit
        total_wagered += wagered
        total_profit += profit
        peak = max(peak, current)
        minimum = min(minimum, current)
        maximum = max(maximum, current)
        max_drawdown = max(max_drawdown, peak - current)
        points.append(
            {
                "index": len(points),
                "bankroll": round(current, 2),
                "profit": round(profit, 2),
                "status": status,
                "roulette_id": signal.get("roulette_id"),
                "created_at": (
                    _json_default(signal.get("created_at"))
                    if signal.get("created_at") is not None
                    else None
                ),
                "won_at_attempt": won_at or None,
                "bet_count": bet_count,
            }
        )
    resolved = wins + losses
    return {
        "starting_bankroll": round(starting_bankroll, 2),
        "ending_bankroll": round(current, 2),
        "profit": round(total_profit, 2),
        "total_wagered": round(total_wagered, 2),
        "roi_on_wagered": total_profit / total_wagered if total_wagered else 0.0,
        "return_on_bankroll": total_profit / starting_bankroll,
        "wins": wins,
        "losses": losses,
        "resolved": resolved,
        "assertiveness": wins / resolved if resolved else 0.0,
        "max_drawdown": round(max_drawdown, 2),
        "minimum_bankroll": round(minimum, 2),
        "maximum_bankroll": round(maximum, 2),
        "attempt_values": chips,
        "points": points,
    }


@router.post("/api/patterns/{pattern_key}/simulation")
async def pattern_simulation(pattern_key: str, request: SimulationRequest) -> dict[str, Any]:
    pattern = await _pattern_or_404(pattern_key)
    if request.roulette_id and request.roulette_id not in pattern.get("roulette_ids", []):
        raise HTTPException(status_code=422, detail="Mesa nao configurada no pattern")
    max_attempts = int(pattern.get("max_attempts") or 1)
    if len(request.attempt_values) > max_attempts:
        raise HTTPException(status_code=422, detail="Quantidade de tentativas acima do pattern")
    if not request.attempt_values or any(value <= 0 for value in request.attempt_values):
        raise HTTPException(status_code=422, detail="Valores de ficha invalidos")
    query: dict[str, Any] = {
        "pattern_key": pattern_key,
        "eligible_hour": True,
        "status": {"$in": ["won", "lost"]},
    }
    if request.roulette_id:
        query["roulette_id"] = request.roulette_id
    if request.bet_count is not None:
        query["bet_count"] = request.bet_count
    documents = await signals_coll.find(query).sort(
        "created_at", ASCENDING
    ).limit(request.limit).to_list(length=request.limit)
    result = simulate_bankroll(
        documents,
        starting_bankroll=request.starting_bankroll,
        attempt_values=request.attempt_values,
    )
    result["pattern_key"] = pattern_key
    result["roulette_id"] = request.roulette_id
    return result
