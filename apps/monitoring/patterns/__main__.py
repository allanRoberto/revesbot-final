from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from pathlib import Path

import certifi
import redis
from dotenv import load_dotenv
from pymongo import MongoClient

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.monitoring.patterns.core.loader import load_pattern
from apps.monitoring.patterns.core.mongo_history import MongoHistorySource
from apps.monitoring.patterns.core.redis_projection import RedisProjection
from apps.monitoring.patterns.core.repository import PatternRepository
from apps.monitoring.patterns.core.runtime import PatternRuntime


def _mongo_kwargs(url: str) -> dict:
    tls_override = (os.getenv("MONGO_TLS") or "").strip().lower()
    if tls_override:
        tls = tls_override in {"1", "true", "yes", "on"}
    else:
        lowered = url.lower()
        tls = url.startswith("mongodb+srv://") or not any(
            host in lowered for host in ("localhost", "127.0.0.1", "::1")
        )
    return {"tls": True, "tlsCAFile": certifi.where()} if tls else {}


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Executa uma implementacao de pattern")
    parser.add_argument("--pattern", default=os.getenv("PATTERN_KEY"))
    args = parser.parse_args()
    if not args.pattern:
        parser.error("--pattern e obrigatorio")

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    mongo_url = (os.getenv("MONGO_URL") or os.getenv("mongo_url") or "").strip()
    if not mongo_url:
        raise RuntimeError("MONGO_URL nao configurado")
    database_name = (
        os.getenv("MONGO_DATABASE") or os.getenv("MONGO_DB") or "roleta_db"
    ).strip()
    mongo_client = MongoClient(mongo_url, **_mongo_kwargs(mongo_url))
    database = mongo_client[database_name]

    redis_client = None
    redis_url = (os.getenv("REDIS_CONNECT") or "").strip()
    if redis_url:
        redis_client = redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )

    loaded = load_pattern(args.pattern)
    runtime = PatternRuntime(
        loaded=loaded,
        repository=PatternRepository(database),
        history_source=MongoHistorySource(database["history"]),
        projection=RedisProjection(redis_client),
    )
    signal.signal(signal.SIGTERM, lambda *_: runtime.stop())
    signal.signal(signal.SIGINT, lambda *_: runtime.stop())
    runtime.run_forever()


if __name__ == "__main__":
    main()
