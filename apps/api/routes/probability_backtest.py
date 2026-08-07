"""Rotas da calculadora e do backtest da expressao central."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.services.probability_backtest_service import (
    analyze_current_probability,
    run_probability_backtest,
)


router = APIRouter(tags=["probability-backtest"])
TEMPLATE_PATH = (
    Path(__file__).resolve().parents[1]
    / "templates"
    / "probability_backtest.html"
)


def _normalize_roulette_id(value: str) -> str:
    normalized = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", normalized):
        raise ValueError("roulette_id deve ser um slug valido")
    return normalized


class CurrentProbabilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    roulette_id: str = Field(min_length=1, max_length=120)
    history_limit: int = Field(default=2000, ge=10, le=10_000, strict=True)
    number_count: int = Field(default=10, ge=1, le=36, strict=True)

    @field_validator("roulette_id")
    @classmethod
    def normalize_roulette_id(cls, value: str) -> str:
        return _normalize_roulette_id(value)


class ProbabilityBacktestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    roulette_id: str = Field(min_length=1, max_length=120)
    history_limit: int = Field(default=2000, ge=100, le=10_000, strict=True)
    number_count: int = Field(default=10, ge=1, le=36, strict=True)
    attempts: int = Field(default=4, ge=1, le=12, strict=True)
    entries_limit: int = Field(default=300, ge=1, le=2000, strict=True)
    minimum_history: int = Field(default=100, ge=50, le=5000, strict=True)

    @field_validator("roulette_id")
    @classmethod
    def normalize_roulette_id(cls, value: str) -> str:
        return _normalize_roulette_id(value)


@router.get(
    "/probability-backtest",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def probability_backtest_page() -> HTMLResponse:
    return HTMLResponse(TEMPLATE_PATH.read_text(encoding="utf-8"))


@router.post("/api/probability-model/analyze")
async def probability_model_analyze(payload: CurrentProbabilityRequest):
    try:
        return await analyze_current_probability(
            roulette_id=payload.roulette_id,
            history_limit=payload.history_limit,
            number_count=payload.number_count,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Falha ao calcular o ranking atual.",
        ) from exc


@router.post("/api/probability-model/backtest")
async def probability_model_backtest(payload: ProbabilityBacktestRequest):
    try:
        return await run_probability_backtest(
            roulette_id=payload.roulette_id,
            history_limit=payload.history_limit,
            number_count=payload.number_count,
            attempts=payload.attempts,
            entries_limit=payload.entries_limit,
            minimum_history=payload.minimum_history,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Falha ao executar o backtest.",
        ) from exc


__all__ = ["router"]
