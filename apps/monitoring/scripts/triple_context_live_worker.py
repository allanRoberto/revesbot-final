"""Run the published ordered trio catalog in live paper-trading mode.

MongoDB is read-only for this process. Runtime state and prospective results are
stored atomically in the persistent Redis instance.
"""
from __future__ import annotations

import logging
import os
import signal
import time
from datetime import datetime, timezone
from typing import Any

from bson import json_util
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import PyMongoError
from redis import Redis
from redis.exceptions import RedisError


ROULETTE_ID = "pragmatic-auto-roulette"
PREFIX = "triple_context_live:v1"
STATE_KEY = f"{PREFIX}:state:{ROULETTE_ID}"
HISTORY_KEY = f"{PREFIX}:history:{ROULETTE_ID}"
SUMMARY_KEY = f"{PREFIX}:summary:{ROULETTE_ID}"
MAX_HISTORY = 5_000
POLL_SECONDS = max(0.25, float(os.getenv("TRIPLE_CONTEXT_LIVE_POLL_SECONDS", "1")))
MONGO_URL = os.getenv("MONGO_URL", "mongodb://127.0.0.1:27017")
MONGO_DATABASE = os.getenv("MONGO_DATABASE", "roleta_db")
REDIS_URL = os.getenv("REDIS_CONNECT", "redis://127.0.0.1:6380/0")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("triple-context-live")
running = True


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def encode(value: Any) -> str:
    return json_util.dumps(value, separators=(",", ":"))


def decode(value: str | bytes | None) -> Any:
    return json_util.loads(value) if value else None


def spin_ref(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "history_id": document["_id"],
        "number": int(document["value"]),
        "timestamp": document["timestamp"],
    }


def rolling_window(buffer: list[dict[str, Any]], spin: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the latest three results, including the result that settled a bet."""
    return [*buffer, spin][-3:]


class TripleContextLiveWorker:
    def __init__(self, database, redis_client: Redis):
        self.history = database["history"]
        self.active = database["triple_context_active_v1"]
        self.builds = database["triple_context_builds_v1"]
        self.rankings = database["triple_context_rankings_v1"]
        self.redis = redis_client

    def catalog_ranking(self, trio: list[int]) -> dict[str, Any] | None:
        if len(trio) != 3 or len(set(trio)) != 3:
            return None
        pointer = self.active.find_one({"_id": ROULETTE_ID}, {"build_id": 1})
        if not pointer or not pointer.get("build_id"):
            raise RuntimeError("Catálogo ativo não encontrado")
        build_id = pointer["build_id"]
        build = self.builds.find_one(
            {"_id": build_id, "roulette_id": ROULETTE_ID}, {"status": 1},
        )
        if not build or build.get("status") not in {"ready", "verified"}:
            raise RuntimeError("Catálogo ativo ainda não está pronto")
        key = ",".join(map(str, trio))
        document = self.rankings.find_one(
            {"build_id": build_id, "roulette_id": ROULETTE_ID, "mode": "ordered", "key": key},
            {"occurrences": 1, "forward.context_events": 1, "forward.ranking": 1},
        )
        if not document:
            raise RuntimeError(f"Trio {key} ausente do catálogo")
        side = document.get("forward") or {}
        ranking = side.get("ranking") or []
        if side.get("context_events", 0) <= 0 or len(ranking) != 37:
            return None
        top = []
        for position, row in enumerate(ranking[:6], 1):
            number = row.get("number")
            if type(number) is not int or not 0 <= number <= 36:
                raise RuntimeError("Ranking inválido no catálogo")
            top.append({
                "position": position, "number": number,
                "score": float(row.get("score", 0)),
                "direct_hits": int(row.get("direct_hits", 0)),
            })
        return {
            "build_id": build_id, "key": key,
            "occurrences": int(document.get("occurrences", 0)),
            "context_events": int(side["context_events"]), "top": top,
        }

    def build_signal(self, spins: list[dict[str, Any]]) -> dict[str, Any]:
        trio = [int(spin["number"]) for spin in spins]
        ranking = self.catalog_ranking(trio)
        common = {
            "id": str(spins[-1]["history_id"]),
            "roulette_id": ROULETTE_ID,
            "trigger_history_id": spins[-1]["history_id"],
            "trigger_timestamp": spins[-1]["timestamp"],
            "trio": trio,
            "configuration": {
                "ordered": True, "direction": "forward", "top_n": 6,
                "attempts": 1, "overlap": False,
            },
            "created_at": utcnow(), "resolved_at": None, "result": None,
        }
        if ranking is None:
            reason = "repeated_numbers" if len(set(trio)) != 3 else "no_evidence"
            return {**common, "status": "skipped", "skip_reason": reason, "ranking": []}
        return {
            **common, "status": "pending", "skip_reason": None,
            "build_id": ranking["build_id"], "catalog_key": ranking["key"],
            "occurrences": ranking["occurrences"],
            "context_events": ranking["context_events"],
            "ranking": ranking["top"],
            "top_numbers": [row["number"] for row in ranking["top"]],
        }

    @staticmethod
    def settle(pending: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        number = int(result["number"])
        hit = number in pending.get("top_numbers", [])
        return {
            **pending,
            "status": "won" if hit else "lost",
            "result": {
                "history_id": result["history_id"], "number": number,
                "timestamp": result["timestamp"], "hit": hit,
            },
            "resolved_at": utcnow(),
        }

    def save_state(self, state: dict[str, Any]) -> dict[str, Any]:
        state = {**state, "roulette_id": ROULETTE_ID, "updated_at": utcnow(), "worker_heartbeat_at": utcnow()}
        self.redis.set(STATE_KEY, encode(state))
        return state

    def save_transition(self, state: dict[str, Any], outcomes: list[dict[str, Any]]) -> dict[str, Any]:
        state = {**state, "roulette_id": ROULETTE_ID, "updated_at": utcnow(), "worker_heartbeat_at": utcnow()}
        pipeline = self.redis.pipeline(transaction=True)
        for outcome in outcomes:
            pipeline.lpush(HISTORY_KEY, encode(outcome))
            pipeline.hincrby(SUMMARY_KEY, outcome["status"], 1)
        pipeline.ltrim(HISTORY_KEY, 0, MAX_HISTORY - 1)
        pipeline.set(STATE_KEY, encode(state))
        pipeline.execute()
        return state

    def save_outcome(self, state: dict[str, Any], outcome: dict[str, Any]) -> dict[str, Any]:
        return self.save_transition(state, [outcome])

    def latest_three(self) -> list[dict[str, Any]]:
        documents = list(
            self.history.find({"roulette_id": ROULETTE_ID}, {"value": 1, "timestamp": 1})
            .sort([("timestamp", DESCENDING), ("_id", DESCENDING)]).limit(3)
        )
        return [spin_ref(row) for row in reversed(documents)]

    def bootstrap(self) -> dict[str, Any]:
        state = decode(self.redis.get(STATE_KEY))
        if state and state.get("strategy_version") == 2:
            return self.save_state({**state, "worker_started_at": utcnow()})
        if state and state.get("pending_signal"):
            return self.save_state({
                **state, "strategy_version": 2, "worker_started_at": utcnow(),
            })
        spins = self.latest_three()
        if len(spins) < 3:
            return self.save_state({
                "strategy_version": 2,
                "phase": "collecting", "buffer": [], "pending_signal": None,
                "last_processed": None, "worker_started_at": utcnow(),
            })
        signal_document = self.build_signal(spins)
        base = {
            "strategy_version": 2,
            "buffer": spins,
            "pending_signal": signal_document if signal_document["status"] == "pending" else None,
            "phase": "awaiting_result" if signal_document["status"] == "pending" else "watching",
            "last_processed": {"history_id": spins[-1]["history_id"], "timestamp": spins[-1]["timestamp"]},
            "worker_started_at": utcnow(),
        }
        if signal_document["status"] == "skipped":
            return self.save_outcome(base, signal_document)
        log.info("Entrada criada trio=%s top6=%s", signal_document["trio"], signal_document["top_numbers"])
        return self.save_state(base)

    def unseen(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        last = state.get("last_processed")
        query: dict[str, Any] = {"roulette_id": ROULETTE_ID}
        if last:
            query["$or"] = [
                {"timestamp": {"$gt": last["timestamp"]}},
                {"timestamp": last["timestamp"], "_id": {"$gt": last["history_id"]}},
            ]
        return list(
            self.history.find(query, {"value": 1, "timestamp": 1})
            .sort([("timestamp", ASCENDING), ("_id", ASCENDING)]).limit(100)
        )

    def process(self, state: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
        spin = spin_ref(document)
        last_processed = {"history_id": spin["history_id"], "timestamp": spin["timestamp"]}
        outcomes = []
        if state.get("phase") == "awaiting_result":
            pending = state.get("pending_signal")
            if pending:
                outcome = self.settle(pending, spin)
                outcomes.append(outcome)
                log.info("Entrada finalizada resultado=%d status=%s", spin["number"], outcome["status"])

        window = rolling_window(state.get("buffer") or [], spin)
        if len(window) < 3:
            next_state = {
                **state, "strategy_version": 2, "phase": "collecting", "buffer": window,
                "pending_signal": None, "last_processed": last_processed,
            }
            return self.save_transition(next_state, outcomes) if outcomes else self.save_state(next_state)

        signal_document = self.build_signal(window)
        next_state = {
            **state, "strategy_version": 2,
            "phase": "awaiting_result" if signal_document["status"] == "pending" else "watching",
            "buffer": window,
            "pending_signal": signal_document if signal_document["status"] == "pending" else None,
            "last_processed": last_processed,
        }
        if signal_document["status"] == "skipped":
            outcomes.append(signal_document)
            log.info("Janela ignorada trio=%s motivo=%s", signal_document["trio"], signal_document["skip_reason"])
            return self.save_transition(next_state, outcomes)
        log.info("Entrada criada trio=%s top6=%s", signal_document["trio"], signal_document["top_numbers"])
        return self.save_transition(next_state, outcomes) if outcomes else self.save_state(next_state)

    def heartbeat(self, state: dict[str, Any]) -> dict[str, Any]:
        return self.save_state(state)

    def run(self) -> None:
        self.redis.ping()
        state = self.bootstrap()
        log.info("Worker iniciado phase=%s", state.get("phase"))
        while running:
            try:
                documents = self.unseen(state)
                if documents:
                    for document in documents:
                        state = self.process(state, document)
                else:
                    state = self.heartbeat(state)
            except (PyMongoError, RedisError):
                log.exception("Falha temporária de persistência")
            except Exception:
                log.exception("Falha ao processar resultado")
            time.sleep(POLL_SECONDS)


def stop(*_: Any) -> None:
    global running
    running = False


def main() -> None:
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    mongo = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    mongo.admin.command("ping")
    redis_client = Redis.from_url(
        REDIS_URL, decode_responses=True,
        socket_connect_timeout=5, socket_timeout=5,
        health_check_interval=30,
    )
    TripleContextLiveWorker(mongo[MONGO_DATABASE], redis_client).run()


if __name__ == "__main__":
    main()
