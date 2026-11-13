"""Live ranking built by the contextual similarity worker (public, read-only)."""
from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from redis.exceptions import RedisError

from api.core.redis_client import get_redis_client
from api.services.contextual_ranking_service import get_contextual_ranking

router = APIRouter(tags=["contextual-ranking"])
API_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=API_DIR / "templates")
ASSETS = (
    API_DIR / "static/css/pages/contextual-ranking.css",
    API_DIR / "static/js/pages/contextual-ranking.js",
)


@lru_cache(maxsize=1)
def asset_version() -> str:
    digest = hashlib.sha256()
    for path in ASSETS:
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def get_ranking_redis():
    return get_redis_client()


@router.get("/ranking-similaridade-contextual", response_class=HTMLResponse)
async def contextual_ranking_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="contextual_ranking.html",
        context={"asset_version": asset_version()},
    )


@router.get("/api/ranking-similaridade-contextual")
async def contextual_ranking_data(
    limit: int = Query(50, ge=1, le=50),
    redis_client=Depends(get_ranking_redis),
):
    try:
        payload = await get_contextual_ranking(redis_client, limit=limit)
    except RedisError as error:
        raise HTTPException(status_code=503, detail="Ranking temporariamente indisponível.") from error
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})
