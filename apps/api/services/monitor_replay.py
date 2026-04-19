from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from api.core.redis_client import r
from api.services.assertiveness_replay import fetch_history_desc


SIMULATION_RESULT_CHANNEL = "new_result_simulate"
DEFAULT_REPLAY_LIMIT = 2000
DEFAULT_REPLAY_DELAY_MS = 10
MAX_REPLAY_LIMIT = 10000
MAX_REPLAY_DELAY_MS = 5000

_ACTIVE_REPLAYS: dict[str, asyncio.Task] = {}
_REPLAY_STATUS: dict[str, Dict[str, Any]] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_limit(limit: int) -> int:
    return max(1, min(MAX_REPLAY_LIMIT, int(limit)))


def _safe_delay_ms(delay_ms: int) -> int:
    return max(0, min(MAX_REPLAY_DELAY_MS, int(delay_ms)))


def _build_status(
    *,
    roulette_id: str,
    state: str,
    channel: str,
    limit: int,
    delay_ms: int,
    total_numbers: int = 0,
    published_numbers: int = 0,
    started_at: str | None = None,
    finished_at: str | None = None,
    error: str = "",
) -> Dict[str, Any]:
    return {
        "roulette_id": roulette_id,
        "channel": channel,
        "limit": limit,
        "delay_ms": delay_ms,
        "total_numbers": total_numbers,
        "published_numbers": published_numbers,
        "state": state,
        "started_at": started_at,
        "finished_at": finished_at,
        "error": error,
    }


async def replay_history_to_channel(
    *,
    roulette_id: str,
    limit: int = DEFAULT_REPLAY_LIMIT,
    delay_ms: int = DEFAULT_REPLAY_DELAY_MS,
    channel: str = SIMULATION_RESULT_CHANNEL,
) -> Dict[str, Any]:
    safe_limit = _safe_limit(limit)
    safe_delay_ms = _safe_delay_ms(delay_ms)
    started_at = _now_iso()

    history_desc = await fetch_history_desc(roulette_id, safe_limit)
    chronological = list(reversed([int(number) for number in history_desc]))
    total_numbers = len(chronological)

    status = _build_status(
        roulette_id=roulette_id,
        state="running",
        channel=channel,
        limit=safe_limit,
        delay_ms=safe_delay_ms,
        total_numbers=total_numbers,
        published_numbers=0,
        started_at=started_at,
    )
    _REPLAY_STATUS[roulette_id] = dict(status)

    for index, number in enumerate(chronological, start=1):
        await r.publish(
            channel,
            json.dumps(
                {
                    "slug": roulette_id,
                    "result": int(number),
                    "simulation": True,
                    "source": "monitor_replay",
                    "sequence": index,
                    "total": total_numbers,
                }
            ),
        )
        status["published_numbers"] = index
        _REPLAY_STATUS[roulette_id] = dict(status)

        if safe_delay_ms > 0:
            await asyncio.sleep(safe_delay_ms / 1000)

    status["state"] = "completed"
    status["finished_at"] = _now_iso()
    _REPLAY_STATUS[roulette_id] = dict(status)
    return dict(status)


async def _run_replay_task(
    *,
    roulette_id: str,
    limit: int,
    delay_ms: int,
    channel: str,
) -> None:
    try:
        await replay_history_to_channel(
            roulette_id=roulette_id,
            limit=limit,
            delay_ms=delay_ms,
            channel=channel,
        )
    except asyncio.CancelledError:
        current = dict(_REPLAY_STATUS.get(roulette_id) or {})
        if current:
            current["state"] = "cancelled"
            current["finished_at"] = _now_iso()
            _REPLAY_STATUS[roulette_id] = current
        raise
    except Exception as exc:
        current = dict(_REPLAY_STATUS.get(roulette_id) or {})
        current.update(
            _build_status(
                roulette_id=roulette_id,
                state="failed",
                channel=channel,
                limit=_safe_limit(limit),
                delay_ms=_safe_delay_ms(delay_ms),
                total_numbers=int(current.get("total_numbers", 0) or 0),
                published_numbers=int(current.get("published_numbers", 0) or 0),
                started_at=current.get("started_at") or _now_iso(),
                finished_at=_now_iso(),
                error=str(exc),
            )
        )
        _REPLAY_STATUS[roulette_id] = current
    finally:
        task = _ACTIVE_REPLAYS.get(roulette_id)
        if task is not None and task is asyncio.current_task():
            _ACTIVE_REPLAYS.pop(roulette_id, None)


async def start_monitor_replay(
    *,
    roulette_id: str,
    limit: int = DEFAULT_REPLAY_LIMIT,
    delay_ms: int = DEFAULT_REPLAY_DELAY_MS,
    channel: str = SIMULATION_RESULT_CHANNEL,
) -> Dict[str, Any]:
    existing = _ACTIVE_REPLAYS.get(roulette_id)
    if existing and not existing.done():
        existing.cancel()
        try:
            await existing
        except asyncio.CancelledError:
            pass

    task = asyncio.create_task(
        _run_replay_task(
            roulette_id=roulette_id,
            limit=_safe_limit(limit),
            delay_ms=_safe_delay_ms(delay_ms),
            channel=channel,
        )
    )
    _ACTIVE_REPLAYS[roulette_id] = task

    status = _build_status(
        roulette_id=roulette_id,
        state="scheduled",
        channel=channel,
        limit=_safe_limit(limit),
        delay_ms=_safe_delay_ms(delay_ms),
        total_numbers=0,
        published_numbers=0,
        started_at=_now_iso(),
    )
    _REPLAY_STATUS[roulette_id] = dict(status)
    return dict(status)


async def stop_monitor_replay(roulette_id: str) -> Dict[str, Any]:
    task = _ACTIVE_REPLAYS.get(roulette_id)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    current = dict(_REPLAY_STATUS.get(roulette_id) or {})
    if not current:
        current = _build_status(
            roulette_id=roulette_id,
            state="idle",
            channel=SIMULATION_RESULT_CHANNEL,
            limit=DEFAULT_REPLAY_LIMIT,
            delay_ms=DEFAULT_REPLAY_DELAY_MS,
        )
    elif str(current.get("state") or "") not in {"completed", "failed", "cancelled"}:
        current["state"] = "cancelled"
        current["finished_at"] = _now_iso()
    _ACTIVE_REPLAYS.pop(roulette_id, None)
    _REPLAY_STATUS[roulette_id] = current
    return dict(current)


def get_monitor_replay_status(roulette_id: str) -> Dict[str, Any]:
    current = _REPLAY_STATUS.get(roulette_id)
    if current:
        return dict(current)
    return _build_status(
        roulette_id=roulette_id,
        state="idle",
        channel=SIMULATION_RESULT_CHANNEL,
        limit=DEFAULT_REPLAY_LIMIT,
        delay_ms=DEFAULT_REPLAY_DELAY_MS,
    )
