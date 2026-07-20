from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query

from api.schemas.orbit import OrbitReplayRequest
from api.services.orbit_performance_service import orbit_performance_service
from api.services.orbit_service import orbit_service


router = APIRouter(prefix="/api/orbit", tags=["orbit"])


@router.get("/number/{number}")
async def describe_number(
    number: int,
    pivot: int | None = Query(default=None, ge=0, le=36),
):
    try:
        return orbit_service.describe_number(number, pivot=pivot)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/analyze/{roulette_id}")
async def analyze_latest(
    roulette_id: str,
    pivot: int | None = Query(default=None, ge=0, le=36),
    history_limit: int = Query(default=2000, ge=50, le=50_000),
    pre_window: int = Query(default=5, ge=1, le=20),
    post_window: int = Query(default=5, ge=1, le=20),
    memory_occurrences: int = Query(default=6, ge=1, le=100),
    horizon: int = Query(default=3, ge=1, le=10),
    persist: bool = Query(default=False),
):
    try:
        return await orbit_service.analyze_latest(
            roulette_id,
            pivot=pivot,
            history_limit=history_limit,
            pre_window=pre_window,
            post_window=post_window,
            memory_occurrences=memory_occurrences,
            horizon=horizon,
            persist=persist,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/suggestions")
async def suggestions_by_roulette(
    roulette_ids: str = Query(min_length=1),
    pivot_count: int = Query(default=3, ge=1, le=5),
    history_limit: int = Query(default=600, ge=100, le=20_000),
    memory_occurrences: int = Query(default=6, ge=1, le=20),
    horizon: int = Query(default=3, ge=1, le=10),
):
    ids = tuple(
        dict.fromkeys(
            value.strip()
            for value in roulette_ids.split(",")
            if value.strip()
        )
    )
    if not ids:
        raise HTTPException(status_code=400, detail="informe ao menos uma roulette_id")
    if len(ids) > 20:
        raise HTTPException(status_code=400, detail="limite de 20 roletas por consulta")

    async def analyze(roulette_id: str):
        try:
            return await orbit_service.analyze_multi_latest(
                roulette_id,
                pivot_count=pivot_count,
                history_limit=history_limit,
                memory_occurrences=memory_occurrences,
                horizon=horizon,
            )
        except (LookupError, ValueError) as exc:
            return {
                "available": False,
                "roulette_id": roulette_id,
                "error": str(exc),
            }

    rows = await asyncio.gather(*(analyze(roulette_id) for roulette_id in ids))
    return {
        "engine_version": "orbital_multi_pivot_v1",
        "pivot_count": pivot_count,
        "memory_occurrences": memory_occurrences,
        "roulettes": rows,
    }


@router.get("/performance")
async def performance_by_roulette(
    roulette_ids: str = Query(min_length=1),
    max_attempts: int = Query(default=10, ge=1, le=20),
    maximum_records: int = Query(default=50_000, ge=100, le=200_000),
):
    ids = tuple(
        dict.fromkeys(
            value.strip()
            for value in roulette_ids.split(",")
            if value.strip()
        )
    )
    if not ids:
        raise HTTPException(status_code=400, detail="informe ao menos uma roulette_id")
    if len(ids) > 20:
        raise HTTPException(status_code=400, detail="limite de 20 roletas por consulta")
    rows = await orbit_performance_service.summarize_many(
        ids,
        max_attempts=max_attempts,
        maximum_records=maximum_records,
    )
    return {
        "engine_version": "orbital_multi_pivot_v1",
        "max_attempts": max_attempts,
        "roulettes": rows,
    }


@router.get("/history")
async def history_by_roulette(
    roulette_ids: str = Query(min_length=1),
    limit: int = Query(default=20, ge=1, le=50),
):
    ids = tuple(
        dict.fromkeys(
            value.strip()
            for value in roulette_ids.split(",")
            if value.strip()
        )
    )
    if not ids:
        raise HTTPException(status_code=400, detail="informe ao menos uma roulette_id")
    if len(ids) > 20:
        raise HTTPException(status_code=400, detail="limite de 20 roletas por consulta")
    rows = await orbit_performance_service.history_many(ids, limit=limit)
    return {
        "engine_version": "orbital_multi_pivot_v1",
        "limit": limit,
        "roulettes": rows,
    }


@router.post("/analyze-history")
async def analyze_history(payload: OrbitReplayRequest):
    try:
        return await asyncio.to_thread(
            orbit_service.analyze_history,
            payload.history_chronological,
            pivot=payload.pivot,
            pre_window=payload.pre_window,
            post_window=payload.post_window,
            memory_occurrences=payload.memory_occurrences,
            horizon=payload.horizon,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
