"""Redis state for the pairs page and the Mongo outbox of its signals.

Same layout as the ranking worker's store, with its own keys (``contextual_pairs:v<version>``).
Closed signals are also queued for MongoDB and written to the shared
``contextual_ranking_signals_v1`` collection, told apart by ``strategy_version`` ("pairs-1") and
the ``pairs-1-`` id prefix, so the existing least-privilege Mongo user is enough.
"""
from __future__ import annotations

import logging
from typing import Any, Sequence

from contextual_ranking.engine import ROULETTE_ID
from contextual_ranking.storage import MongoSignalWriter, decode, encode

from contextual_pairs import PAIRS_VERSION
from contextual_pairs.engine import compact_signal

PREFIX = f"contextual_pairs:v{PAIRS_VERSION}"
STATE_KEY = f"{PREFIX}:state:{ROULETTE_ID}"
VIEW_KEY = f"{PREFIX}:view:{ROULETTE_ID}"
HEARTBEAT_KEY = f"{PREFIX}:heartbeat:{ROULETTE_ID}"
HISTORY_KEY = f"{PREFIX}:history:{ROULETTE_ID}"
SUMMARY_KEY = f"{PREFIX}:summary:{ROULETTE_ID}"
OUTBOX_KEY = f"{PREFIX}:mongo-outbox:{ROULETTE_ID}"
HISTORY_LIMIT = 500
OUTBOX_LIMIT = 20_000

log = logging.getLogger("contextual-pairs")


class PairsRedisStore:
    def __init__(self, redis_client):
        self.redis = redis_client

    def load_state(self) -> dict[str, Any] | None:
        return decode(self.redis.get(STATE_KEY))

    def save(self, state: dict[str, Any], view: dict[str, Any], closed: Sequence[dict[str, Any]] = (),
             tally: str | None = None) -> None:
        """State, page projection, closed signals and the ranking tally change atomically."""
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
        if tally:
            pipeline.hincrby(SUMMARY_KEY, "rankings", 1)
            pipeline.hincrby(SUMMARY_KEY, f"ranking_{tally}", 1)
        pipeline.execute()

    def heartbeat(self, payload: dict[str, Any]) -> None:
        self.redis.set(HEARTBEAT_KEY, encode(payload))

    def outbox_size(self) -> int:
        return int(self.redis.llen(OUTBOX_KEY))

    def flush_outbox(self, writer: MongoSignalWriter, limit: int = 50) -> int:
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
