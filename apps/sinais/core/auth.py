"""Autenticação via Clerk — verificação do session JWT por JWKS.

Dependency `get_current_user` para uso nas rotas protegidas. O token é lido
do header `Authorization: Bearer <jwt>` (enviado pelo frontend via
`Clerk.session.getToken()`) ou do cookie `__session` como fallback.
"""

import time

import httpx
from fastapi import HTTPException, Request, status
from jose import jwt
from jose.exceptions import JWTError

from sinais.core.config import settings
from sinais.services.credits import get_or_create_user

_JWKS_CACHE: dict = {"url": None, "keys": None, "fetched_at": 0.0}
_JWKS_TTL = 3600.0


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return request.cookies.get("__session")


def _jwks_url_for(token: str) -> str:
    if settings.clerk_jwks_url:
        return settings.clerk_jwks_url
    claims = jwt.get_unverified_claims(token)
    iss = claims.get("iss")
    if not iss:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token sem issuer")
    return iss.rstrip("/") + "/.well-known/jwks.json"


async def _get_jwks(url: str, force: bool = False) -> list[dict]:
    now = time.time()
    fresh = (
        not force
        and _JWKS_CACHE["keys"]
        and _JWKS_CACHE["url"] == url
        and now - _JWKS_CACHE["fetched_at"] < _JWKS_TTL
    )
    if fresh:
        return _JWKS_CACHE["keys"]
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        keys = resp.json().get("keys", [])
    _JWKS_CACHE.update(url=url, keys=keys, fetched_at=now)
    return keys


def _find_key(keys: list[dict], kid: str | None) -> dict | None:
    return next((k for k in keys if k.get("kid") == kid), None)


async def get_current_user(request: Request) -> dict:
    token = _extract_token(request)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "não autenticado")

    try:
        header = jwt.get_unverified_header(token)
        url = _jwks_url_for(token)
        keys = await _get_jwks(url)
        key = _find_key(keys, header.get("kid"))
        if key is None:  # possível rotação de chave: recarrega o JWKS
            keys = await _get_jwks(url, force=True)
            key = _find_key(keys, header.get("kid"))
        if key is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "chave de assinatura não encontrada")
        claims = jwt.decode(token, key, algorithms=["RS256"], options={"verify_aud": False})
    except HTTPException:
        raise
    except (JWTError, httpx.HTTPError, KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token inválido")

    azp_allow = settings.authorized_parties
    azp = claims.get("azp")
    if azp_allow and azp and azp not in azp_allow:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "origem não autorizada")

    clerk_user_id = claims.get("sub")
    if not clerk_user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token sem sub")

    return await get_or_create_user(clerk_user_id, claims.get("email"))
