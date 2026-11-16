"""Live worker of the pair strategy.

It reuses the ranking worker (history reading, Mongo outbox flush, heartbeat, run loop) and only
replaces the part that turns each ranking into pair signals. MongoDB ``history`` is read with the
API's read-only credential; engine state lives in the persistent Redis; closed signals are copied
to MongoDB by the same least-privilege user the ranking worker uses
(``CONTEXTUAL_RANKING_MONGO_URL``).
"""
from __future__ import annotations

import logging
import os
import signal
from typing import Any

from contextual_ranking import STRATEGY_VERSION
from contextual_ranking.engine import SPIN_MEMORY
from contextual_ranking.search_client import VectorSearchClient
from contextual_ranking.storage import MONGO_COLLECTION, MongoSignalWriter
from contextual_ranking.worker import GAP_RESULTS_LIMIT, MAX_CATCHUP, ContextualRankingWorker, MongoHistorySource

from contextual_pairs import PAIRS_VERSION
from contextual_pairs.engine import advance_pair_signals, build_view, process, rebuild
from contextual_pairs.storage import PairsRedisStore

log = logging.getLogger("contextual-pairs")


class PairsWorker(ContextualRankingWorker):
    def _save(self, state: dict[str, Any], closed: list[dict[str, Any]] | tuple = ()) -> None:
        tally = (state.get("screen") or {}).get("state")
        self.store.save(state, build_view(state), closed, tally)
        self.state = state

    @staticmethod
    def _log_closed(closed: list[dict[str, Any]]) -> None:
        for item in closed:
            pair = " e ".join(str(number) for number in item["pair"])
            if item["hit"]:
                log.info("Sinal %s (par %s) ACERTOU na %dª rodada com o %s", item["_id"], pair,
                         item["hit_attempt"], item["hit_number"])
            else:
                log.info("Sinal %s (par %s) errou nas %d rodadas · aposta=%s", item["_id"], pair,
                         len(item["checks"]), item["bet"])

    def _needs_restart(self) -> bool:
        state = self.state
        return (state is None or state.get("strategy_version") != STRATEGY_VERSION
                or state.get("pairs_version") != PAIRS_VERSION or not state.get("last_processed"))

    def resync(self, reason: str, previous: dict[str, Any] | None = None,
               closed: list[dict[str, Any]] | tuple = ()) -> None:
        spins = self.history.latest(SPIN_MEMORY)
        log.info("Ressincronizando a janela (%s) com %d resultados", reason, len(spins))
        self._save(rebuild(previous if previous is not None else self.state, spins, self.search, self.clock()),
                   closed)
        self._log_closed(list(closed))

    def step(self) -> None:
        if self._needs_restart():
            self.resync("início")
            return
        state = self.state
        spins = self.history.after(state["last_processed"], MAX_CATCHUP + 1)
        if len(spins) > MAX_CATCHUP:
            missed = self.history.after(state["last_processed"], GAP_RESULTS_LIMIT)
            advanced, closed = advance_pair_signals(state, missed, self.clock())
            self.resync(f"mais de {MAX_CATCHUP} resultados atrasados", advanced, closed)
            return
        for item in spins:
            next_state, closed = process(self.state, item, self.search, self.clock())
            self._save(next_state, closed)
            self._log_closed(closed)
            screen = next_state["screen"]
            log.info("Ranking após %d · top7=%s · par=%s · %s · sinais abertos=%d", item["number"],
                     [row["number"] for row in next_state["ranking"]["top"]], screen["pair"], screen["state"],
                     len(next_state["pair_signals"]))


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
    worker = PairsWorker(
        MongoHistorySource(mongo[database]["history"]), PairsRedisStore(redis_client), client.search,
        search_configured=client.configured, writer=writer,
    )

    def stop(*_: Any) -> None:
        worker.running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    worker.run(max(0.25, float(os.getenv("CONTEXTUAL_PAIRS_POLL_SECONDS", "1"))))
