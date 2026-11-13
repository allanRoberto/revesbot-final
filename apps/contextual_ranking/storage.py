"""Redis state for the page and permanent MongoDB history of every signal.

Redis (persistent instance, same as the other live workers) keeps the engine
state (including the open signals), the page projection, a heartbeat, the
latest 500 closed signals and the totals. Every closed signal is also queued in
a Redis outbox and copied to MongoDB by a dedicated least-privilege user; the
queue survives MongoDB outages or a missing configuration and is drained
automatically.

Each strategy version uses its own Redis keys, so its totals start from zero;
the MongoDB documents of every version share one collection and are told apart
by ``strategy_version`` (and the ``v<version>-`` id prefix).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Sequence

from contextual_ranking import STRATEGY_VERSION
from contextual_ranking.engine import ROULETTE_ID, compact_signal, parse_time

PREFIX = f"contextual_ranking:v{STRATEGY_VERSION}"
STATE_KEY = f"{PREFIX}:state:{ROULETTE_ID}"
VIEW_KEY = f"{PREFIX}:view:{ROULETTE_ID}"
HEARTBEAT_KEY = f"{PREFIX}:heartbeat:{ROULETTE_ID}"
HISTORY_KEY = f"{PREFIX}:history:{ROULETTE_ID}"
SUMMARY_KEY = f"{PREFIX}:summary:{ROULETTE_ID}"
OUTBOX_KEY = f"{PREFIX}:mongo-outbox:{ROULETTE_ID}"
HISTORY_LIMIT = 500
OUTBOX_LIMIT = 20_000
MONGO_COLLECTION = "contextual_ranking_signals_v1"

log = logging.getLogger("contextual-ranking")


def encode(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def decode(raw: str | bytes | None) -> Any:
    return json.loads(raw) if raw else None


class RedisStore:
    def __init__(self, redis_client):
        self.redis = redis_client

    def load_state(self) -> dict[str, Any] | None:
        return decode(self.redis.get(STATE_KEY))

    def save(self, state: dict[str, Any], view: dict[str, Any],
             closed: Sequence[dict[str, Any]] = ()) -> None:
        """State, page projection and the signals closed by this result change atomically."""
        pipeline = self.redis.pipeline(transaction=True)
        pipeline.set(STATE_KEY, encode(state))
        pipeline.set(VIEW_KEY, encode(view))
        for signal in closed:
            pipeline.lpush(HISTORY_KEY, encode(compact_signal(signal)))
            pipeline.hincrby(SUMMARY_KEY, "signals", 1)
            pipeline.hincrby(SUMMARY_KEY, "hits" if signal["hit"] else "misses", 1)
            pipeline.lpush(OUTBOX_KEY, encode(signal))
        if closed:
            pipeline.ltrim(HISTORY_KEY, 0, HISTORY_LIMIT - 1)
            pipeline.ltrim(OUTBOX_KEY, 0, OUTBOX_LIMIT - 1)
        pipeline.execute()

    def heartbeat(self, payload: dict[str, Any]) -> None:
        self.redis.set(HEARTBEAT_KEY, encode(payload))

    def outbox_size(self) -> int:
        return int(self.redis.llen(OUTBOX_KEY))

    def flush_outbox(self, writer: "MongoSignalWriter", limit: int = 50) -> int:
        """Copy the oldest queued signals to MongoDB; stops at the first failure."""
        sent = 0
        while sent < limit:
            raw = self.redis.lindex(OUTBOX_KEY, -1)
            if raw is None:
                break
            try:
                signal = decode(raw)
            except ValueError:
                log.error("Sinal ilegível descartado da fila do MongoDB")
                self.redis.rpop(OUTBOX_KEY)
                continue
            writer.write(signal)
            self.redis.rpop(OUTBOX_KEY)
            sent += 1
        return sent


def _as_datetime(value: Any) -> Any:
    return parse_time(value) if isinstance(value, str) else value


def _spin_document(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if not value:
        return value
    return {**value, "timestamp": _as_datetime(value.get("timestamp"))}


def to_mongo_document(signal: dict[str, Any]) -> dict[str, Any]:
    """Store dates as BSON dates so the history can be queried by time."""
    return {
        **signal,
        "built_after": _spin_document(signal.get("built_after")),
        "checks": [{**check, "result": _spin_document(check["result"])} for check in signal.get("checks", [])],
        "sources": [{**source, "trigger": _spin_document(source.get("trigger"))}
                    for source in signal.get("sources", [])],
        "created_at": _as_datetime(signal.get("created_at")),
        "closed_at": _as_datetime(signal.get("closed_at")),
    }


class MongoSignalWriter:
    def __init__(self, collection):
        self.collection = collection

    def ensure_indexes(self) -> None:
        # Strategy 1 documents are queried by result time, strategy 2 by creation time.
        self.collection.create_index([("roulette_id", 1), ("result.timestamp", -1)],
                                     name="roulette_result_time")
        self.collection.create_index([("roulette_id", 1), ("strategy_version", 1), ("created_at", -1)],
                                     name="roulette_strategy_created_at")

    def write(self, signal: dict[str, Any]) -> None:
        document = to_mongo_document(signal)
        self.collection.replace_one({"_id": document["_id"]}, document, upsert=True)
