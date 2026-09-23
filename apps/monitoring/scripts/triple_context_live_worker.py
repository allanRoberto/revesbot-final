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


def next_phase(phase: str, buffer: list[dict[str, Any]], spin: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """Pure transition used by the runtime and unit tests."""
    if phase == "awaiting_result":
        return "collecting", []
    updated = [*buffer, spin]
    if len(updated) >= 3:
        return "awaiting_result", updated[-3:]
    return "collecting", updated


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

    def save_outcome(self, state: dict[str, Any], outcome: dict[str, Any]) -> dict[str, Any]:
        state = {**state, "roulette_id": ROULETTE_ID, "updated_at": utcnow(), "worker_heartbeat_at": utcnow()}
        pipeline = self.redis.pipeline(transaction=True)
        pipeline.lpush(HISTORY_KEY, encode(outcome))
        pipeline.ltrim(HISTORY_KEY, 0, MAX_HISTORY - 1)
        pipeline.hincrby(SUMMARY_KEY, outcome["status"], 1)
        pipeline.set(STATE_KEY, encode(state))
        pipeline.execute()
        return state

    def bootstrap(self) -> dict[str, Any]:
        state = decode(self.redis.get(STATE_KEY))
        if state:
            return self.save_state({**state, "worker_started_at": utcnow()})
        documents = list(
            self.history.find({"roulette_id": ROULETTE_ID}, {"value": 1, "timestamp": 1})
            .sort([("timestamp", DESCENDING), ("_id", DESCENDING)]).limit(3)
        )
        if len(documents) < 3:
            return self.save_state({
                "phase": "collecting", "buffer": [], "pending_signal": None,
                "last_processed": None, "worker_started_at": utcnow(),
            })
        spins = [spin_ref(row) for row in reversed(documents)]
        signal_document = self.build_signal(spins)
        base = {
            "buffer": spins if signal_document["status"] == "pending" else [],
            "pending_signal": signal_document if signal_document["status"] == "pending" else None,
            "phase": "awaiting_result" if signal_document["status"] == "pending" else "collecting",
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
        if state.get("phase") == "awaiting_result":
            pending = state.get("pending_signal")
            next_state = {
                **state, "phase": "collecting", "buffer": [],
                "pending_signal": None, "last_processed": last_processed,
            }
            if not pending:
                return self.save_state(next_state)
            outcome = self.settle(pending, spin)
            log.info("Entrada finalizada resultado=%d status=%s", spin["number"], outcome["status"])
            return self.save_outcome(next_state, outcome)

        buffer = [*(state.get("buffer") or []), spin]
        if len(buffer) < 3:
            return self.save_state({
                **state, "phase": "collecting", "buffer": buffer,
                "pending_signal": None, "last_processed": last_processed,
            })
        signal_document = self.build_signal(buffer[-3:])
        next_state = {
            **state,
            "phase": "awaiting_result" if signal_document["status"] == "pending" else "collecting",
            "buffer": buffer[-3:] if signal_document["status"] == "pending" else [],
            "pending_signal": signal_document if signal_document["status"] == "pending" else None,
            "last_processed": last_processed,
        }
        if signal_document["status"] == "skipped":
            log.info("Bloco ignorado trio=%s motivo=%s", signal_document["trio"], signal_document["skip_reason"])
            return self.save_outcome(next_state, signal_document)
        log.info("Entrada criada trio=%s top6=%s", signal_document["trio"], signal_document["top_numbers"])
        return self.save_state(next_state)

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
