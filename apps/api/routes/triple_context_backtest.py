"""Web interface and bounded read-only evaluation of the published trio catalog."""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from pymongo.errors import PyMongoError

from api.core.runtime_db import history_db
from api.services.triple_context_backtest_service import run_catalog_backtest
from api.services.triple_context_ranking_service import CatalogNotFound, CatalogUnavailable

router = APIRouter(tags=["triple-context-backtest"])
API_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=API_DIR / "templates")
BACKTEST_TIMEOUT_SECONDS = 50.0
_backtest_lock = asyncio.Lock()


class BacktestConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    history_limit: StrictInt = Field(default=5000, ge=6, le=50000)
    top_k: StrictInt = Field(default=13, ge=1, le=37)
    attempts: StrictInt = Field(default=3, ge=1, le=100)
    ordered: StrictBool = True
    direction: Literal["forward", "backward"] = "forward"


def get_backtest_db():
    return history_db


@router.get("/backtest-trios", response_class=HTMLResponse)
async def backtest_page(request: Request):
    digest = hashlib.sha256()
    for path in ("static/css/triple_context_ranking.css", "static/css/triple_context_backtest.css",
                 "static/js/pages/triple-context-backtest.js"):
        digest.update((API_DIR / path).read_bytes())
    return templates.TemplateResponse(request=request, name="triple_context_backtest.html",
                                      context={"asset_version": digest.hexdigest()})


@router.post("/api/triple-context-backtest")
async def triple_context_backtest(config: BacktestConfig, db=Depends(get_backtest_db)):
    if _backtest_lock.locked():
        raise HTTPException(status_code=429, detail="Um backtest está em andamento. Tente novamente em instantes.",
                            headers={"Retry-After": "5"})
    async with _backtest_lock:
        try:
            return await asyncio.wait_for(run_catalog_backtest(db, **config.model_dump()),
                                           timeout=BACKTEST_TIMEOUT_SECONDS)
        except CatalogNotFound as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except CatalogUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except asyncio.TimeoutError as error:
            raise HTTPException(status_code=504, detail="A consulta demorou mais que o esperado. Tente um recorte menor.") from error
        except PyMongoError as error:
            raise HTTPException(status_code=503, detail="O histórico ou catálogo está temporariamente indisponível.") from error
