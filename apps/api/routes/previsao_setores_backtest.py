from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from api.services.previsao_setores_backtest_service import run_previsao_setores_backtest

router = APIRouter()


@router.get("/api/previsao-setores/backtest")
async def previsao_setores_backtest(
    roulette_id: str = Query(..., min_length=1),
    limit: int = Query(default=2000, ge=100, le=10000),
    entries_limit: int = Query(default=500, ge=10, le=2000),
):
    try:
        return await run_previsao_setores_backtest(
            roulette_id=roulette_id,
            limit=limit,
            entries_limit=entries_limit,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha no backtest: {exc}")
