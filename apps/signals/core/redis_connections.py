from __future__ import annotations

import os
from urllib.parse import quote

from dotenv import load_dotenv
import redis
import redis.asyncio as redis_async


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


def _build_url_from_parts(
    *,
    host: str,
    port: int,
    db: int,
    user: str = "",
    password: str = "",
) -> str:
    auth = ""
    if password:
        encoded_password = quote(password, safe="")
        if user:
            encoded_user = quote(user, safe="")
            auth = f"{encoded_user}:{encoded_password}@"
        else:
            auth = f":{encoded_password}@"
    return f"redis://{auth}{host}:{port}/{db}"


def _build_signal_redis_url() -> str:
    direct = (os.getenv("REDIS_SIGNALS_CONNECT") or os.getenv("REDIS_CONNECT") or "").strip()
    if direct:
        return direct

    host = (os.getenv("REDIS_SIGNALS_HOST") or os.getenv("REDIS_HOST") or "127.0.0.1").strip()
    port = _env_int("REDIS_SIGNALS_PORT", _env_int("REDIS_PORT", 6379))
    db = _env_int("REDIS_SIGNALS_DB", _env_int("REDIS_DB", 0))
    user = (os.getenv("REDIS_SIGNALS_USER") or os.getenv("REDIS_USER") or "").strip()
    password = (os.getenv("REDIS_SIGNALS_PASSWORD") or os.getenv("REDIS_PASSWORD") or "").strip()

    return _build_url_from_parts(host=host, port=port, db=db, user=user, password=password)


def _build_results_redis_url(signal_redis_url: str) -> str:
    direct = (os.getenv("REDIS_RESULTS_CONNECT") or "").strip()
    if direct:
        return direct

    host_raw = os.getenv("REDIS_RESULTS_HOST")
    port_raw = os.getenv("REDIS_RESULTS_PORT")
    db_raw = os.getenv("REDIS_RESULTS_DB")
    user_raw = os.getenv("REDIS_RESULTS_USER")
    pass_raw = os.getenv("REDIS_RESULTS_PASSWORD")

    if any(v is not None for v in [host_raw, port_raw, db_raw, user_raw, pass_raw]):
        host = (host_raw or "127.0.0.1").strip()
        port = _env_int("REDIS_RESULTS_PORT", 6379)
        db = _env_int("REDIS_RESULTS_DB", 0)
        user = (user_raw or "").strip()
        password = (pass_raw or "").strip()
        return _build_url_from_parts(host=host, port=port, db=db, user=user, password=password)

    return signal_redis_url


SIGNALS_REDIS_URL = _build_signal_redis_url()
RESULTS_REDIS_URL = _build_results_redis_url(SIGNALS_REDIS_URL)

REDIS_SOCKET_TIMEOUT = _env_float("REDIS_SOCKET_TIMEOUT", 5.0)
REDIS_CONNECT_TIMEOUT = _env_float("REDIS_CONNECT_TIMEOUT", 5.0)
REDIS_HEALTH_CHECK_INTERVAL = _env_int("REDIS_HEALTH_CHECK_INTERVAL", 30)
REDIS_RETRY_ON_TIMEOUT = _env_bool("REDIS_RETRY_ON_TIMEOUT", True)


def get_sync_signals_redis_client() -> redis.Redis:
    return redis.from_url(
        SIGNALS_REDIS_URL,
        socket_timeout=REDIS_SOCKET_TIMEOUT,
        socket_connect_timeout=REDIS_CONNECT_TIMEOUT,
        retry_on_timeout=REDIS_RETRY_ON_TIMEOUT,
        health_check_interval=REDIS_HEALTH_CHECK_INTERVAL,
    )


def get_async_results_redis_client(*, decode_responses: bool = False) -> redis_async.Redis:
    return redis_async.from_url(
        RESULTS_REDIS_URL,
        decode_responses=decode_responses,
        socket_timeout=REDIS_SOCKET_TIMEOUT,
        socket_connect_timeout=REDIS_CONNECT_TIMEOUT,
        retry_on_timeout=REDIS_RETRY_ON_TIMEOUT,
        health_check_interval=REDIS_HEALTH_CHECK_INTERVAL,
    )


def get_signals_redis_url() -> str:
    return SIGNALS_REDIS_URL


def get_results_redis_url() -> str:
    return RESULTS_REDIS_URL

