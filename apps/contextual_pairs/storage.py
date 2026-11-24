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
from contextual_pairs.quality import SUPREMO, supremo_result

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
            for tag in signal.get("tags") or []:
                # Hit rate of the tagged signals, counted from ``tags_since``: signals opened before the tags
                # existed carry none, so the count never mixes the data the rules were found on.
                if tag == SUPREMO:
                    continue  # counted below: a Supremo signal only wins inside its own results
                pipeline.hincrby(SUMMARY_KEY, f"tag_{tag}_signals", 1)
                pipeline.hincrby(SUMMARY_KEY, f"tag_{tag}_{'hits' if signal['hit'] else 'misses'}", 1)
            supremo = supremo_result(signal)
            if supremo is not None:
                won, staked, net = supremo
                pipeline.hincrby(SUMMARY_KEY, f"tag_{SUPREMO}_signals", 1)
                pipeline.hincrby(SUMMARY_KEY, f"tag_{SUPREMO}_{'hits' if won else 'misses'}", 1)
                pipeline.hincrby(SUMMARY_KEY, f"tag_{SUPREMO}_staked", staked)  # R$ 1 per number
                pipeline.hincrby(SUMMARY_KEY, f"tag_{SUPREMO}_net", net)
            pipeline.lpush(OUTBOX_KEY, encode(signal))
        if closed:
            pipeline.ltrim(HISTORY_KEY, 0, HISTORY_LIMIT - 1)
            pipeline.ltrim(OUTBOX_KEY, 0, OUTBOX_LIMIT - 1)
        if tally:
            pipeline.hincrby(SUMMARY_KEY, "rankings", 1)
            pipeline.hincrby(SUMMARY_KEY, f"ranking_{tally}", 1)
        if state.get("updated_at"):
            pipeline.hsetnx(SUMMARY_KEY, "tags_since", state["updated_at"])  # only the first save sets it
            pipeline.hsetnx(SUMMARY_KEY, f"{SUPREMO}_since", state["updated_at"])  # first save with the Supremo tag
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
