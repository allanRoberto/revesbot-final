from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

from api.services.triplet_strategy_service import (
    get_roulette_current,
    get_roulette_history,
    get_strategy_summary,
)


router = APIRouter()


@router.get("/api/triplet-strategy/summary")
async def triplet_strategy_summary() -> Dict[str, Any]:
    try:
        return await get_strategy_summary()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha ao obter summary: {exc}")


@router.get("/api/triplet-strategy/{roulette_id}/current")
async def triplet_strategy_current(roulette_id: str) -> Dict[str, Any]:
    try:
        return await get_roulette_current(roulette_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha ao consultar roleta: {exc}")


@router.get("/api/triplet-strategy/{roulette_id}/history")
async def triplet_strategy_history(
    roulette_id: str,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> Dict[str, Any]:
    try:
        return await get_roulette_history(roulette_id, page=page, size=size)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha ao consultar historico: {exc}")
