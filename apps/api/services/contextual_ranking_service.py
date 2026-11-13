"""Read-only Redis projection for /ranking-similaridade-contextual.

The worker in ``apps/contextual_ranking`` writes these keys; the API never
touches MongoDB for this page. Each signal is checked against up to 7 results:
open signals come from the page projection, closed ones from the history list.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

ROULETTE_ID = "pragmatic-brazilian-roulette"
PREFIX = "contextual_ranking:v2"
ATTEMPTS_LIMIT = 7
VIEW_KEY = f"{PREFIX}:view:{ROULETTE_ID}"
HEARTBEAT_KEY = f"{PREFIX}:heartbeat:{ROULETTE_ID}"
HISTORY_KEY = f"{PREFIX}:history:{ROULETTE_ID}"
SUMMARY_KEY = f"{PREFIX}:summary:{ROULETTE_ID}"
ONLINE_SECONDS = 20
LATE_SECONDS = 90
EMPTY_RANKING = {"top": [], "built_after": None, "analyzed_results": 0, "maximum": 0}


def _decode(raw: Any) -> Any:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def _age_seconds(value: Any, now: datetime) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return max(0.0, (now - moment).total_seconds())


def _int(mapping: dict, name: str) -> int:
    value = mapping.get(name) or mapping.get(name.encode()) or 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def worker_status(heartbeat: dict[str, Any], age: float | None) -> str:
    if not heartbeat:
        return "offline"
    if heartbeat.get("status") == "config_pending":
        return "configuracao_pendente"
    if age is None or age > LATE_SECONDS:
        return "offline"
    if age > ONLINE_SECONDS or heartbeat.get("status") == "error":
        return "atrasado"
    return "online"


async def get_contextual_ranking(redis_client, *, limit: int = 50, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    pipeline = redis_client.pipeline(transaction=False)
    pipeline.get(VIEW_KEY)
    pipeline.get(HEARTBEAT_KEY)
    pipeline.lrange(HISTORY_KEY, 0, limit - 1)
    pipeline.hgetall(SUMMARY_KEY)
    view_raw, heartbeat_raw, history_raw, summary_raw = await pipeline.execute()

    view = _decode(view_raw) or {}
    heartbeat = _decode(heartbeat_raw) or {}
    closed = [row for row in (_decode(raw) for raw in history_raw or []) if isinstance(row, dict)]
    open_signals = [row for row in view.get("open_signals") or [] if isinstance(row, dict)]
    history = (open_signals + closed)[:limit]
    finished = [row for row in history if row.get("status") in {"hit", "miss"}]
    summary = summary_raw or {}
    age = _age_seconds(heartbeat.get("at"), now)
    return {
        "generated_at": now.isoformat(),
        "roulette_id": ROULETTE_ID,
        "worker": {
            "status": worker_status(heartbeat, age),
            "detail": heartbeat.get("detail"),
            "heartbeat_age_seconds": round(age, 1) if age is not None else None,
            "last_result_at": heartbeat.get("last_result_at"),
            "mongo": heartbeat.get("mongo"),
        },
        "version": view.get("version", 0),
        "updated_at": view.get("updated_at"),
        "ranking": view.get("ranking") or EMPTY_RANKING,
        "last_numbers": view.get("last_numbers") or [],
        "analysis": view.get("analysis") or [],
        "attempts_limit": view.get("attempts_limit") or ATTEMPTS_LIMIT,
        "history": history,
        "summary": {
            "open": len(open_signals),
            "recent": {"hits": sum(1 for row in finished if row.get("hit") is True), "total": len(finished)},
            "all_time": {"hits": _int(summary, "hits"), "total": _int(summary, "signals")},
        },
    }
