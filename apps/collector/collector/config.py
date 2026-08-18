from __future__ import annotations

import os
from dataclasses import dataclass


DEFAULT_SUBSCRIBE_KEYS = (
    "237", "204", "225", "292", "2501", "545", "270", "12501",
    "28301", "28201", "266", "230", "211", "203", "206", "287",
)


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Variavel obrigatoria ausente: {name}")
    return value


def _int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"Variavel {name} deve ser um inteiro") from exc
    if value < minimum:
        raise RuntimeError(f"Variavel {name} deve ser >= {minimum}")
    return value


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class CollectorSettings:
    mongo_url: str
    mongo_database: str
    mongo_collection: str
    redis_url: str
    redis_channel: str
    casino_id: str
    subscribe_keys: tuple[str, ...]
    health_host: str
    health_port: int
    ws_stale_seconds: int
    result_stale_seconds: int
    startup_grace_seconds: int
    watchdog_interval_seconds: int
    watchdog_failures_before_exit: int
    watchdog_exit_enabled: bool
    retention_limit_per_table: int
    retention_interval_seconds: int
    log_level: str

    @classmethod
    def from_env(cls) -> "CollectorSettings":
        raw_keys = os.getenv("PRAGMATIC_SUBSCRIBE_KEYS", "").strip()
        keys = tuple(key.strip() for key in raw_keys.split(",") if key.strip())
        return cls(
            mongo_url=_required("MONGO_URL"),
            mongo_database=os.getenv("MONGO_DATABASE", "roleta_db").strip() or "roleta_db",
            mongo_collection=os.getenv("MONGO_COLLECTION", "history").strip() or "history",
            redis_url=_required("REDIS_CONNECT"),
            redis_channel=os.getenv("RESULT_CHANNEL", "new_result").strip() or "new_result",
            casino_id=os.getenv("PRAGMATIC_CASINO_ID", "ppcdd00000006702").strip(),
            subscribe_keys=keys or DEFAULT_SUBSCRIBE_KEYS,
            health_host=os.getenv("COLLECTOR_HEALTH_HOST", "127.0.0.1").strip(),
            health_port=_int("COLLECTOR_HEALTH_PORT", 9101, 1),
            ws_stale_seconds=_int("COLLECTOR_WS_STALE_SECONDS", 90, 10),
            result_stale_seconds=_int("COLLECTOR_RESULT_STALE_SECONDS", 180, 30),
            startup_grace_seconds=_int("COLLECTOR_STARTUP_GRACE_SECONDS", 120, 10),
            watchdog_interval_seconds=_int("COLLECTOR_WATCHDOG_INTERVAL_SECONDS", 15, 5),
            watchdog_failures_before_exit=_int("COLLECTOR_WATCHDOG_FAILURES", 3, 1),
            watchdog_exit_enabled=_bool("COLLECTOR_WATCHDOG_EXIT_ENABLED", True),
            retention_limit_per_table=_int("COLLECTOR_RETENTION_LIMIT", 200000, 0),
            retention_interval_seconds=_int("COLLECTOR_RETENTION_INTERVAL_SECONDS", 300, 30),
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO",
        )
