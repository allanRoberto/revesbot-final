"""Feature-scoped HTTP Basic and CSRF protection for the paid Jev panel."""
from __future__ import annotations

import re
import secrets
from uuid import uuid4

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from api.core.config import settings


CSRF_COOKIE = "jev_csrf"
CSRF_HEADER = "X-CSRF-Token"
_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,128}\Z", re.ASCII)
_basic = HTTPBasic(auto_error=False)


def request_id_for(request: Request) -> str:
    existing = getattr(request.state, "jev_request_id", None)
    if existing:
        return existing
    candidate = request.headers.get("X-Request-ID", "")
    request_id = candidate if _REQUEST_ID.fullmatch(candidate) else str(uuid4())
    request.state.jev_request_id = request_id
    return request_id


def jev_http_error(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
) -> HTTPException:
    response_headers = {"Cache-Control": "no-store", "X-Request-ID": request_id_for(request)}
    if headers:
        response_headers.update(headers)
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "request_id": request_id_for(request),
        },
        headers=response_headers,
    )


async def require_jev_access(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(_basic),
) -> str:
    configured_user = (settings.jev_panel_user or "").strip()
    configured_password = settings.jev_panel_password or ""
    if not configured_user or not configured_password:
        raise jev_http_error(
            request,
            status_code=503,
            code="jev_access_not_configured",
            message="O acesso ao painel Jev ainda não foi configurado no servidor.",
        )

    valid = bool(
        credentials
        and secrets.compare_digest(credentials.username, configured_user)
        and secrets.compare_digest(credentials.password, configured_password)
    )
    if not valid:
        raise jev_http_error(
            request,
            status_code=401,
            code="jev_authentication_required",
            message="Credenciais inválidas para o painel Jev.",
            headers={"WWW-Authenticate": 'Basic realm="Jev", charset="UTF-8"'},
        )
    return configured_user


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


async def require_jev_csrf(request: Request) -> None:
    cookie_token = request.cookies.get(CSRF_COOKIE, "")
    header_token = request.headers.get(CSRF_HEADER, "")
    if (
        not cookie_token
        or not header_token
        or not secrets.compare_digest(cookie_token, header_token)
    ):
        raise jev_http_error(
            request,
            status_code=403,
            code="jev_csrf_invalid",
            message="A proteção da sessão expirou. Reabra a página e tente novamente.",
        )

    fetch_site = request.headers.get("Sec-Fetch-Site", "").lower()
    if fetch_site == "cross-site":
        raise jev_http_error(
            request,
            status_code=403,
            code="jev_cross_site_request",
            message="A análise deve ser solicitada pela própria página do painel.",
        )

    origin = request.headers.get("Origin")
    if origin:
        expected_origin = f"{request.url.scheme}://{request.url.netloc}"
        if not secrets.compare_digest(origin.rstrip("/"), expected_origin.rstrip("/")):
            raise jev_http_error(
                request,
                status_code=403,
                code="jev_origin_invalid",
                message="A origem da solicitação não é permitida.",
            )
