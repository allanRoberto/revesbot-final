from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

from api.services.next_number_ranking_service import DEFAULT_ROULETTE_ID
from api.services.next_number_sequence_service import (
    DEFAULT_HOUR_END,
    DEFAULT_HOUR_START,
    DEFAULT_MODE,
    DEFAULT_POSITIONS_LIMIT,
    DEFAULT_TIME_WINDOW_ENABLED,
    DEFAULT_TIME_WINDOW_UNIT,
    DEFAULT_TIME_WINDOW_VALUE,
    MAX_TIME_WINDOW_VALUE,
    SEQUENCE_DEPTH,
    get_next_number_sequence_rankings,
    refresh_next_number_sequences,
)


router = APIRouter()


@router.post("/api/next-number-sequences/{roulette_id}/refresh")
async def refresh_next_number_sequences_route(
    roulette_id: str,
) -> Dict[str, Any]:
    try:
        return await refresh_next_number_sequences(roulette_id=roulette_id, source="api")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha ao atualizar catalogacao de sequencias: {exc}")


@router.get("/api/next-number-sequences/{roulette_id}/rankings")
async def get_next_number_sequence_rankings_route(
    roulette_id: str,
    base_number: int = Query(..., ge=0, le=36),
    positions_limit: int = Query(default=DEFAULT_POSITIONS_LIMIT, ge=1, le=SEQUENCE_DEPTH),
    hour_start: int = Query(default=DEFAULT_HOUR_START, ge=0, le=23),
    hour_end: int = Query(default=DEFAULT_HOUR_END, ge=0, le=23),
    mode: str = Query(default=DEFAULT_MODE),
    preview_limit: int = Query(default=50, ge=0, le=200),
    time_window_enabled: bool = Query(default=DEFAULT_TIME_WINDOW_ENABLED),
    time_window_value: int = Query(default=DEFAULT_TIME_WINDOW_VALUE, ge=1, le=MAX_TIME_WINDOW_VALUE),
    time_window_unit: str = Query(default=DEFAULT_TIME_WINDOW_UNIT),
) -> Dict[str, Any]:
    try:
        return await get_next_number_sequence_rankings(
            roulette_id=roulette_id,
            base_number=base_number,
            positions_limit=positions_limit,
            hour_start=hour_start,
            hour_end=hour_end,
            mode=mode,
            preview_limit=preview_limit,
            time_window_enabled=time_window_enabled,
            time_window_value=time_window_value,
            time_window_unit=time_window_unit,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha ao consultar catalogacao de sequencias: {exc}")


@router.post("/api/next-number-sequences/refresh")
async def refresh_default_next_number_sequences_route() -> Dict[str, Any]:
    return await refresh_next_number_sequences_route(DEFAULT_ROULETTE_ID)
