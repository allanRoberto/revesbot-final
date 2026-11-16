"""Pair strategy over the contextual ranking (public, read-only)."""
from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from redis.exceptions import RedisError

from api.core.redis_client import get_redis_client
from api.services.contextual_pairs_service import get_contextual_pairs

router = APIRouter(tags=["contextual-pairs"])
API_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=API_DIR / "templates")
# The page shares the layout of the ranking page, so its stylesheet is part of the version too.
ASSETS = (
    API_DIR / "static/css/pages/contextual-ranking.css",
    API_DIR / "static/css/pages/contextual-pairs.css",
    API_DIR / "static/js/pages/contextual-pairs.js",
)


@lru_cache(maxsize=1)
def asset_version() -> str:
    digest = hashlib.sha256()
    for path in ASSETS:
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def get_pairs_redis():
    return get_redis_client()


@router.get("/ranking-similaridade-pares", response_class=HTMLResponse)
async def contextual_pairs_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="contextual_pairs.html",
        context={"asset_version": asset_version()},
    )


@router.get("/api/ranking-similaridade-pares")
async def contextual_pairs_data(
    limit: int = Query(50, ge=1, le=50),
    redis_client=Depends(get_pairs_redis),
):
    try:
        payload = await get_contextual_pairs(redis_client, limit=limit)
    except RedisError as error:
        raise HTTPException(status_code=503, detail="Pares temporariamente indisponíveis.") from error
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})
