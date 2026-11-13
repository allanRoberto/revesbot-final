"""Live worker for the contextual similarity ranking.

MongoDB ``history`` is read with the API's read-only credential. Engine state
lives in the persistent Redis; signals are copied to MongoDB by a separate,
least-privilege user (``CONTEXTUAL_RANKING_MONGO_URL``).
"""
from __future__ import annotations

import logging
import os
import signal
import time
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from contextual_ranking import STRATEGY_VERSION
from contextual_ranking.engine import (
    ROULETTE_ID, SPIN_MEMORY, SearchFunction, build_view, iso, process, rebuild, spin,
)
from contextual_ranking.search_client import VectorSearchClient
from contextual_ranking.storage import MONGO_COLLECTION, MongoSignalWriter, RedisStore

MAX_CATCHUP = 5

log = logging.getLogger("contextual-ranking")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HistorySource(Protocol):
    def latest(self, limit: int) -> list[dict[str, Any]]: ...
    def after(self, cursor: dict[str, Any], limit: int) -> list[dict[str, Any]]: ...


def spin_from_document(document: dict[str, Any]) -> dict[str, Any] | None:
    value, timestamp = document.get("value"), document.get("timestamp")
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if isinstance(value, bool) or not 0 <= number <= 36 or not isinstance(timestamp, datetime):
        return None
    return spin(document["_id"], number, timestamp)


class MongoHistorySource:
    """Results of one table, oldest first, ordered like the other live workers."""

    def __init__(self, collection, roulette_id: str = ROULETTE_ID):
        self.collection = collection
        self.roulette_id = roulette_id

    def _spins(self, documents) -> list[dict[str, Any]]:
        spins = [spin_from_document(document) for document in documents]
        return [item for item in spins if item is not None]

    def latest(self, limit: int) -> list[dict[str, Any]]:
        documents = list(
            self.collection.find({"roulette_id": self.roulette_id}, {"value": 1, "timestamp": 1})
            .sort([("timestamp", -1), ("_id", -1)]).limit(limit)
        )
        return self._spins(reversed(documents))

    def after(self, cursor: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        from bson import ObjectId
        from bson.errors import InvalidId

        timestamp = datetime.fromisoformat(cursor["timestamp"])
        try:
            last_id: Any = ObjectId(cursor["history_id"])
        except (InvalidId, TypeError):
            last_id = cursor["history_id"]
        query = {"roulette_id": self.roulette_id, "$or": [
            {"timestamp": {"$gt": timestamp}},
            {"timestamp": timestamp, "_id": {"$gt": last_id}},
        ]}
        documents = self.collection.find(query, {"value": 1, "timestamp": 1}) \
            .sort([("timestamp", 1), ("_id", 1)]).limit(limit)
        return self._spins(documents)


class ContextualRankingWorker:
    def __init__(self, history: HistorySource, store: RedisStore, search: SearchFunction, *,
                 search_configured: bool = True, writer: MongoSignalWriter | None = None,
                 clock: Callable[[], datetime] = utcnow):
        self.history, self.store, self.search = history, store, search
        self.search_configured = search_configured
        self.writer = writer
        self.clock = clock
        self.started_at = clock()
        self.state: dict[str, Any] | None = store.load_state()
        self.mongo_error: str | None = None
        self.last_mongo_write_at: datetime | None = None
        self.running = True

    def _save(self, state: dict[str, Any], signal_document: dict[str, Any] | None = None) -> None:
        self.store.save(state, build_view(state), signal_document)
        self.state = state

    def resync(self, reason: str) -> None:
        spins = self.history.latest(SPIN_MEMORY)
        log.info("Ressincronizando a janela (%s) com %d resultados", reason, len(spins))
        self._save(rebuild(self.state, spins, self.search, self.clock()))

    def step(self) -> None:
        state = self.state
        if state is None or state.get("strategy_version") != STRATEGY_VERSION or not state.get("last_processed"):
            self.resync("início")
            return
        spins = self.history.after(state["last_processed"], MAX_CATCHUP + 1)
        if len(spins) > MAX_CATCHUP:
            self.resync(f"mais de {MAX_CATCHUP} resultados atrasados")
            return
        for item in spins:
            next_state, signal_document = process(self.state, item, self.search, self.clock())
            self._save(next_state, signal_document)
            if signal_document is not None:
                log.info("Resultado %d %s · top7=%s", item["number"],
                         "ACERTOU" if signal_document["hit"] else "errou", signal_document["top_numbers"])
            log.info("Ranking atualizado após %d · top7=%s", item["number"],
                     [row["number"] for row in next_state["ranking"]["top"]])

    def flush(self) -> None:
        if self.writer is None:
            return
        try:
            if self.store.flush_outbox(self.writer):
                self.last_mongo_write_at = self.clock()
            self.mongo_error = None
        except Exception as error:  # keep the queue and retry on the next loop
            self.mongo_error = f"{type(error).__name__}: {str(error)[:200]}"
            log.warning("MongoDB indisponível para o histórico: %s", self.mongo_error)

    def beat(self, status: str = "running", detail: str | None = None) -> None:
        state = self.state or {}
        last = state.get("last_processed") or {}
        self.store.heartbeat({
            "at": iso(self.clock()), "started_at": iso(self.started_at), "status": status,
            "detail": detail, "search_configured": self.search_configured,
            "last_result_at": last.get("timestamp"), "version": state.get("version", 0),
            "mongo": {
                "configured": self.writer is not None, "pending": self.store.outbox_size(),
                "last_error": self.mongo_error,
                "last_write_at": iso(self.last_mongo_write_at) if self.last_mongo_write_at else None,
            },
        })

    def run_once(self) -> None:
        if not self.search_configured:
            self.beat("config_pending", "VECTOR_API_TOKEN não configurado no ambiente da API.")
            return
        self.step()
        self.flush()
        self.beat()

    def run(self, poll_seconds: float = 1.0) -> None:
        log.info("Worker iniciado; mesa=%s", ROULETTE_ID)
        while self.running:
            try:
                self.run_once()
            except Exception as error:
                log.exception("Falha no ciclo do worker")
                try:
                    self.beat("error", f"{type(error).__name__}: {str(error)[:200]}")
                except Exception:
                    pass
            time.sleep(poll_seconds)


def main() -> None:
    from pymongo import MongoClient
    from redis import Redis

    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    mongo = MongoClient(os.getenv("MONGO_URL", "mongodb://127.0.0.1:27017"),
                        serverSelectionTimeoutMS=5000, tz_aware=True)
    mongo.admin.command("ping")
    database = os.getenv("MONGO_DATABASE", "roleta_db")
    redis_client = Redis.from_url(os.getenv("REDIS_CONNECT", "redis://127.0.0.1:6380/0"),
                                  decode_responses=True, socket_connect_timeout=5,
                                  socket_timeout=10, health_check_interval=30)
    redis_client.ping()
    client = VectorSearchClient(os.getenv("VECTOR_SEARCH_URL", "http://127.0.0.1:8037"),
                                os.getenv("VECTOR_API_TOKEN", ""))
    writer = None
    writer_url = os.getenv("CONTEXTUAL_RANKING_MONGO_URL", "").strip()
    if writer_url:
        writer_client = MongoClient(writer_url, serverSelectionTimeoutMS=5000, tz_aware=True)
        writer = MongoSignalWriter(writer_client[database][MONGO_COLLECTION])
        try:
            writer.ensure_indexes()
        except Exception as error:
            log.warning("Índice do histórico não criado agora: %s", error)
    else:
        log.warning("CONTEXTUAL_RANKING_MONGO_URL ausente: sinais ficam na fila do Redis até a configuração.")
    worker = ContextualRankingWorker(
        MongoHistorySource(mongo[database]["history"]), RedisStore(redis_client), client.search,
        search_configured=client.configured, writer=writer,
    )

    def stop(*_: Any) -> None:
        worker.running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    worker.run(max(0.25, float(os.getenv("CONTEXTUAL_RANKING_POLL_SECONDS", "1"))))
