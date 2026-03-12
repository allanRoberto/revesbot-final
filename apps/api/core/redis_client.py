from __future__ import annotations

import os
from urllib.parse import quote

from dotenv import load_dotenv
import redis.asyncio as redis


load_dotenv()


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def build_redis_url() -> str:
    redis_connect = (os.getenv("REDIS_CONNECT") or "").strip()
    if redis_connect:
        return redis_connect

    host = (os.getenv("REDIS_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    port = _env_int("REDIS_PORT", 6380)
    db = _env_int("REDIS_DB", 0)

    user = (os.getenv("REDIS_USER") or "").strip()
    password = os.getenv("REDIS_PASSWORD")

    auth = ""
    if password:
        encoded_password = quote(password, safe="")
        if user:
            encoded_user = quote(user, safe="")
            auth = f"{encoded_user}:{encoded_password}@"
        else:
            auth = f":{encoded_password}@"

    return f"redis://{auth}{host}:{port}/{db}"


def build_signals_redis_url(default_url: str) -> str:
    redis_connect = (os.getenv("REDIS_SIGNALS_CONNECT") or "").strip()
    if redis_connect:
        return redis_connect
    return default_url


REDIS_URL = build_redis_url()
REDIS_SOCKET_TIMEOUT = _env_float("REDIS_SOCKET_TIMEOUT", 5.0)
REDIS_CONNECT_TIMEOUT = _env_float("REDIS_CONNECT_TIMEOUT", 5.0)
REDIS_HEALTH_CHECK_INTERVAL = _env_int("REDIS_HEALTH_CHECK_INTERVAL", 30)
REDIS_RETRY_ON_TIMEOUT = _env_bool("REDIS_RETRY_ON_TIMEOUT", True)

r = redis.from_url(
    REDIS_URL,
    decode_responses=True,
    socket_timeout=REDIS_SOCKET_TIMEOUT,
    socket_connect_timeout=REDIS_CONNECT_TIMEOUT,
    retry_on_timeout=REDIS_RETRY_ON_TIMEOUT,
    health_check_interval=REDIS_HEALTH_CHECK_INTERVAL,
)

SIGNALS_REDIS_URL = build_signals_redis_url(REDIS_URL)
signals_r = r if SIGNALS_REDIS_URL == REDIS_URL else redis.from_url(
    SIGNALS_REDIS_URL,
    decode_responses=True,
    socket_timeout=REDIS_SOCKET_TIMEOUT,
    socket_connect_timeout=REDIS_CONNECT_TIMEOUT,
    retry_on_timeout=REDIS_RETRY_ON_TIMEOUT,
    health_check_interval=REDIS_HEALTH_CHECK_INTERVAL,
)


def get_redis_client():
    return r


def get_redis_url() -> str:
    return REDIS_URL


def get_signals_redis_client():
    return signals_r


def get_signals_redis_url() -> str:
    return SIGNALS_REDIS_URL


__all__ = [
    "r",
    "signals_r",
    "get_redis_client",
    "get_redis_url",
    "get_signals_redis_client",
    "get_signals_redis_url",
    "build_redis_url",
    "build_signals_redis_url",
]
