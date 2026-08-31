from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from api.services.roulette_analyzer_backtest_service import (
    RouletteBacktestValidationError,
    run_roulette_analyzer_backtest,
)
from api.services.roulette_analyzer_service import (
    RouletteHistoryNotFoundError,
    RouletteHistoryUnavailableError,
    analyze_roulette,
    list_analyzer_roulettes,
)


router = APIRouter()
template_path = Path(__file__).resolve().parent.parent / "templates/roulette_analyzer.html"


class RouletteAnalyzerBacktestRequest(BaseModel):
    roulette_ids: list[str] = Field(min_length=1, max_length=10)
    analysis_window: int = Field(default=500, ge=20, le=5_000)
    backtest_limit: int = Field(default=5_000, ge=100, le=50_000)
    max_attempts: int = Field(default=10, ge=1, le=100)
    renewal_mode: Literal["spins", "minutes"] = "spins"
    renewal_value: int = Field(default=5, ge=1, le=10_000)
    target_hit_rate: float = Field(default=0.90, ge=0.01, le=1.0)


@router.get("/analisador-gatilhos", response_class=HTMLResponse)
async def roulette_analyzer_page() -> HTMLResponse:
    return HTMLResponse(template_path.read_text(encoding="utf-8"))


@router.get("/api/roulette-analyzer")
async def run_roulette_analyzer(
    roulette_id: str = Query(min_length=1),
    quantidade: int = Query(ge=1, le=50_000),
) -> dict[str, Any]:
    try:
        return await analyze_roulette(roulette_id, quantidade)
    except RouletteHistoryNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="Roleta sem resultados armazenados",
        ) from exc
    except RouletteHistoryUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail="Histórico de roleta indisponível",
        ) from exc


@router.get("/api/roulette-analyzer/roulettes")
async def get_roulette_analyzer_roulettes() -> dict[str, Any]:
    try:
        roulettes = await list_analyzer_roulettes()
    except RouletteHistoryUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail="Histórico de roleta indisponível",
        ) from exc
    return {"roulettes": roulettes}


@router.post("/api/roulette-analyzer/backtest")
async def run_roulette_analyzer_backtest_route(
    payload: RouletteAnalyzerBacktestRequest,
) -> dict[str, Any]:
    try:
        return await run_roulette_analyzer_backtest(
            roulette_ids=payload.roulette_ids,
            analysis_window=payload.analysis_window,
            backtest_limit=payload.backtest_limit,
            max_attempts=payload.max_attempts,
            renewal_mode=payload.renewal_mode,
            renewal_value=payload.renewal_value,
            target_hit_rate=payload.target_hit_rate,
        )
    except RouletteBacktestValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RouletteHistoryNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Histórico insuficiente para a roleta: {exc}",
        ) from exc
    except RouletteHistoryUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail="Histórico de roleta indisponível",
        ) from exc
