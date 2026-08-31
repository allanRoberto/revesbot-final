from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from api.services.roulette_analyzer_service import (
    RouletteHistoryNotFoundError,
    RouletteHistoryUnavailableError,
    analyze_roulette,
    list_analyzer_roulettes,
)


router = APIRouter()
template_path = Path(__file__).resolve().parent.parent / "templates/roulette_analyzer.html"


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
