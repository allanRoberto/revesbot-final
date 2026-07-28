from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from api.schemas.terminal_signals import TerminalSignalProfitabilityRequest
from api.services.terminal_signal_service import terminal_signal_service


router = APIRouter(prefix="/api/terminal-signals", tags=["terminal-signals"])


def _roulette_ids(value: Optional[str]) -> tuple[str, ...] | None:
    if not value:
        return None
    values = tuple(
        dict.fromkeys(item.strip() for item in str(value).split(",") if item.strip())
    )
    return values or None


@router.get("/catalog")
async def terminal_signal_catalog():
    return await terminal_signal_service.catalog()


@router.get("/summary")
async def terminal_signal_summary(
    variant: str = Query(min_length=1),
    roulette_ids: Optional[str] = Query(default=None),
    window: str = Query(default="24h"),
    maximum_records: int = Query(default=50_000, ge=100, le=200_000),
):
    try:
        return await terminal_signal_service.summary(
            variant,
            roulette_ids=_roulette_ids(roulette_ids),
            window=window,
            maximum_records=maximum_records,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/history")
async def terminal_signal_history(
    variant: str = Query(min_length=1),
    roulette_ids: Optional[str] = Query(default=None),
    window: str = Query(default="24h"),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    skip: int = Query(default=0, ge=0),
):
    try:
        return await terminal_signal_service.history(
            variant,
            roulette_ids=_roulette_ids(roulette_ids),
            window=window,
            status=status,
            limit=limit,
            skip=skip,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/profitability")
async def terminal_signal_profitability(payload: TerminalSignalProfitabilityRequest):
    try:
        return await terminal_signal_service.profitability(
            payload.variant,
            roulette_ids=payload.roulette_ids,
            window=payload.window,
            initial_bank=payload.initial_bank,
            attempt_stakes=payload.attempt_stakes,
            payout_mode=payload.payout_mode,
            maximum_records=payload.maximum_records,
            maximum_chart_points=payload.maximum_chart_points,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
