"""Páginas HTML (login, gerador, histórico)."""

import base64
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from sinais.core.config import settings
from sinais.core.roulettes import display_name

router = APIRouter()

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _clerk_frontend_api(pk: str | None) -> str:
    """Deriva o host do Frontend API a partir da publishable key do Clerk.

    Formato: pk_test_<base64("<frontend-api>$")> (ou pk_live_...).
    """
    if not pk:
        return ""
    try:
        encoded = pk.split("_", 2)[2]
        padding = "=" * (-len(encoded) % 4)  # padding correto (senão quebra keys válidas)
        decoded = base64.b64decode(encoded + padding).decode("utf-8")
        return decoded.rstrip("$")
    except Exception:
        return ""


def _base_ctx(request: Request) -> dict:
    pk = settings.clerk_publishable_key
    return {
        "request": request,
        "clerk_publishable_key": pk or "",
        "clerk_frontend_api": _clerk_frontend_api(pk),
        "clerk_enabled": bool(pk),
    }


@router.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", _base_ctx(request))


@router.get("/app", response_class=HTMLResponse)
async def app_page(request: Request):
    ctx = _base_ctx(request)
    ctx["roulettes"] = [
        {"slug": slug, "name": display_name(slug)} for slug in settings.allowed_roulettes
    ]
    ctx["attempts"] = settings.attempts
    ctx["entry_numbers"] = settings.entry_numbers
    ctx["entry_sizes"] = settings.allowed_entry_sizes
    return templates.TemplateResponse("app.html", ctx)


@router.get("/historico", response_class=HTMLResponse)
async def historico_page(request: Request):
    return templates.TemplateResponse("historico.html", _base_ctx(request))
