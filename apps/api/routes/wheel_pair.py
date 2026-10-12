"""Page for inspecting a number's previous occurrence and wheel offsets."""
from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from api.routes import roulette_history


# Use the catalog supported by the deployed history API, including any local extensions.
HISTORY_ROULETTES = getattr(roulette_history, "HISTORY_ROULETTES", roulette_history.ACTIVE_ROULETTES)
HISTORY_ROULETTE_BY_SLUG = getattr(
    roulette_history, "HISTORY_ROULETTE_BY_SLUG", roulette_history.ACTIVE_ROULETTE_BY_SLUG
)


router = APIRouter(tags=["wheel-pair"])
API_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=API_DIR / "templates")
PAGE_ASSETS = (
    API_DIR / "static/css/pages/wheel-pair.css",
    API_DIR / "static/js/pages/wheel-pair.js",
    API_DIR / "static/js/core/wheel-pair-model.js",
)


def _wheel_pair_asset_version() -> str:
    digest = hashlib.sha256()
    for path in PAGE_ASSETS:
        digest.update(path.read_bytes())
    return digest.hexdigest()


@router.get("/contagem-casas", response_class=HTMLResponse)
async def wheel_pair_page(request: Request, slug: str = "pragmatic-auto-roulette"):
    roulette = HISTORY_ROULETTE_BY_SLUG.get(slug)
    if roulette is None:
        raise HTTPException(status_code=404, detail="Roleta não monitorada")
    return templates.TemplateResponse(
        request=request,
        name="wheel_pair.html",
        context={
            "slug": slug,
            "roulette": roulette,
            "roulettes": HISTORY_ROULETTES,
            "asset_version": _wheel_pair_asset_version(),
        },
    )
