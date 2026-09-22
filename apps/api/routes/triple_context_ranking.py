"""HTTP access to the independently generated trio catalogs."""
from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pymongo.errors import PyMongoError

from api.core.runtime_db import history_db
from api.services.triple_context_ranking_service import (
    CatalogNotFound, CatalogUnavailable, get_triple_context_ranking, parse_numbers,
)


router = APIRouter(tags=["triple-context-ranking"])
CATALOG_QUERY_TIMEOUT_SECONDS = 5.0


def get_catalog_db():
    return history_db


@router.get("/api/triple-context-ranking")
async def triple_context_ranking(
    numbers: str = Query(..., min_length=5, max_length=32,
                         description="Três números distintos, separados por vírgula: 34,14,18."),
    direction: Literal["forward", "backward"] = Query(..., description="forward: frente; backward: trás."),
    ordered: bool = Query(..., description="true: ordem exata; false: qualquer ordem."),
    input_order: Literal["latest_first", "chronological"] = Query(
        "latest_first", description="Por padrão, o primeiro número informado é o mais recente."),
    roulette_id: str = Query("pragmatic-auto-roulette", min_length=1, max_length=120,
                              pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"),
    db=Depends(get_catalog_db),
):
    try:
        parsed = parse_numbers(numbers)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    try:
        return await asyncio.wait_for(
            get_triple_context_ranking(db, numbers=parsed, direction=direction, ordered=ordered,
                                       input_order=input_order, roulette_id=roulette_id),
            timeout=CATALOG_QUERY_TIMEOUT_SECONDS,
        )
    except CatalogNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except CatalogUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except (PyMongoError, asyncio.TimeoutError) as error:
        raise HTTPException(status_code=503, detail="Consulta ao catálogo temporariamente indisponível.") from error
