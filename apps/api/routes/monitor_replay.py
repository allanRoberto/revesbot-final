from __future__ import annotations

from typing import Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.services.monitor_replay import (
    DEFAULT_REPLAY_DELAY_MS,
    DEFAULT_REPLAY_LIMIT,
    SIMULATION_RESULT_CHANNEL,
    get_monitor_replay_status,
    start_monitor_replay,
    stop_monitor_replay,
)


router = APIRouter()


class MonitorReplayRequest(BaseModel):
    roulette_id: str
    limit: int = DEFAULT_REPLAY_LIMIT
    delay_ms: int = DEFAULT_REPLAY_DELAY_MS


@router.post("/api/monitor/replay/start")
async def start_replay(payload: MonitorReplayRequest) -> Dict:
    roulette_id = str(payload.roulette_id or "").strip()
    if not roulette_id:
        raise HTTPException(status_code=400, detail="roulette_id é obrigatório.")

    try:
        status = await start_monitor_replay(
            roulette_id=roulette_id,
            limit=payload.limit,
            delay_ms=payload.delay_ms,
            channel=SIMULATION_RESULT_CHANNEL,
        )
        return {
            "ok": True,
            "message": "Replay iniciado.",
            "status": status,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/monitor/replay/stop")
async def stop_replay(payload: MonitorReplayRequest) -> Dict:
    roulette_id = str(payload.roulette_id or "").strip()
    if not roulette_id:
        raise HTTPException(status_code=400, detail="roulette_id é obrigatório.")

    try:
        status = await stop_monitor_replay(roulette_id)
        return {
            "ok": True,
            "message": "Replay interrompido.",
            "status": status,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/monitor/replay/status/{roulette_id}")
async def replay_status(roulette_id: str) -> Dict:
    safe_roulette_id = str(roulette_id or "").strip()
    if not safe_roulette_id:
        raise HTTPException(status_code=400, detail="roulette_id é obrigatório.")
    return {
        "ok": True,
        "status": get_monitor_replay_status(safe_roulette_id),
    }

