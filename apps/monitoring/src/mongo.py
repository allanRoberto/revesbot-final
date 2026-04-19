from __future__ import annotations

import os
from typing import Any, Dict

import certifi
from dotenv import load_dotenv
from pymongo import MongoClient


load_dotenv()


def _env_bool(name: str, default: bool | None = None) -> bool | None:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def _build_client_kwargs(mongo_url: str) -> Dict[str, Any]:
    tls_override = _env_bool("MONGO_TLS", None)
    if tls_override is None:
        lowered = mongo_url.lower()
        tls_enabled = mongo_url.startswith("mongodb+srv://") or (
            "localhost" not in lowered
            and "127.0.0.1" not in lowered
            and "::1" not in lowered
        )
    else:
        tls_enabled = tls_override

    kwargs: Dict[str, Any] = {}
    if tls_enabled:
        kwargs["tls"] = True
        kwargs["tlsCAFile"] = certifi.where()
    return kwargs


def _resolve_mongo_url() -> str:
    return (os.getenv("MONGO_URL") or os.getenv("mongo_url") or "").strip()


def _resolve_db_name() -> str:
    return (os.getenv("MONGO_DB") or "roleta_db").strip() or "roleta_db"


MONGO_URL = _resolve_mongo_url()
if not MONGO_URL:
    raise RuntimeError("MONGO_URL nao configurado para o suggestion monitor.")

mongo_client = MongoClient(MONGO_URL, **_build_client_kwargs(MONGO_URL))
mongo_db = mongo_client[_resolve_db_name()]

