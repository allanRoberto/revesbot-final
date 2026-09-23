"""Token-protected live dashboard for the top-six ordered trio worker."""
from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pymongo.errors import PyMongoError

from api.core.runtime_db import history_db
from api.services.triple_context_live_service import get_live_dashboard


router = APIRouter(tags=["triple-context-live"])
API_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=API_DIR / "templates")
ASSETS = (
    API_DIR / "static/css/triple_context_live.css",
    API_DIR / "static/js/pages/triple-context-live.js",
)


def _asset_version() -> str:
    digest = hashlib.sha256()
    for path in ASSETS:
        digest.update(path.read_bytes())
    return digest.hexdigest()


def get_live_db():
    return history_db


def require_dashboard_token(x_live_dashboard_token: str | None = Header(None)) -> None:
    expected = os.getenv("TRIPLE_CONTEXT_LIVE_DASHBOARD_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=503, detail="Acesso ao monitor ainda não foi configurado.")
    if not x_live_dashboard_token or not hmac.compare_digest(x_live_dashboard_token, expected):
        raise HTTPException(status_code=401, detail="Token do monitor inválido.")


@router.get("/patterns/triple-context-live", response_class=HTMLResponse)
async def triple_context_live_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="triple_context_live.html",
        context={"asset_version": _asset_version()},
    )


@router.get("/api/patterns/triple-context-live", dependencies=[Depends(require_dashboard_token)])
async def triple_context_live_data(
    limit: int = Query(50, ge=1, le=200),
    database=Depends(get_live_db),
):
    try:
        return await get_live_dashboard(database, limit=limit)
    except PyMongoError as error:
        raise HTTPException(status_code=503, detail="Monitor live temporariamente indisponível.") from error
