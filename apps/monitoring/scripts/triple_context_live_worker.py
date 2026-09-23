"""Monitor the published ordered trio catalog in live paper-trading mode.

The worker consumes Pragmatic Auto Roulette results in non-overlapping blocks:
three results create one top-six entry and the following result settles its only
attempt. State lives in MongoDB so a restart does not duplicate or lose entries.
"""
from __future__ import annotations

import logging
import os
import signal
import time
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError


ROULETTE_ID = "pragmatic-auto-roulette"
STATE_ID = f"triple-context-live:{ROULETTE_ID}:ordered:forward:top6:v1"
POLL_SECONDS = max(0.25, float(os.getenv("TRIPLE_CONTEXT_LIVE_POLL_SECONDS", "1")))
MONGO_URL = os.getenv("MONGO_URL", "mongodb://127.0.0.1:27017")
MONGO_DATABASE = os.getenv("MONGO_DATABASE", "roleta_db")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("triple-context-live")
running = True


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
    def __init__(self, database):
        self.db = database
        self.history = database["history"]
        self.active = database["triple_context_active_v1"]
        self.builds = database["triple_context_builds_v1"]
        self.rankings = database["triple_context_rankings_v1"]
        self.signals = database["triple_context_live_signals_v1"]
        self.states = database["triple_context_live_state_v1"]

    def ensure_indexes(self) -> None:
        self.signals.create_index(
            [("roulette_id", ASCENDING), ("trigger_history_id", ASCENDING)],
            unique=True,
            name="roulette_trigger_unique",
        )
        self.signals.create_index(
            [("roulette_id", ASCENDING), ("created_at", DESCENDING)],
            name="roulette_created_desc",
        )
        self.signals.create_index(
            [("roulette_id", ASCENDING), ("status", ASCENDING)],
            name="roulette_status",
        )

    def catalog_ranking(self, trio: list[int]) -> dict[str, Any] | None:
        if len(trio) != 3 or len(set(trio)) != 3:
            return None
        pointer = self.active.find_one({"_id": ROULETTE_ID}, {"build_id": 1})
        if not pointer or not pointer.get("build_id"):
            raise RuntimeError("Catálogo ativo não encontrado")
        build_id = pointer["build_id"]
        build = self.builds.find_one(
            {"_id": build_id, "roulette_id": ROULETTE_ID},
            {"status": 1},
        )
        if not build or build.get("status") not in {"ready", "verified"}:
            raise RuntimeError("Catálogo ativo ainda não está pronto")
        key = ",".join(map(str, trio))
        document = self.rankings.find_one(
            {
                "build_id": build_id,
                "roulette_id": ROULETTE_ID,
                "mode": "ordered",
                "key": key,
            },
            {
                "occurrences": 1,
                "forward.context_events": 1,
                "forward.ranking": 1,
            },
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
                "position": position,
                "number": number,
                "score": float(row.get("score", 0)),
                "direct_hits": int(row.get("direct_hits", 0)),
            })
        return {
            "build_id": build_id,
            "key": key,
            "occurrences": int(document.get("occurrences", 0)),
            "context_events": int(side["context_events"]),
            "top": top,
        }

    def record_signal(self, spins: list[dict[str, Any]]) -> Any | None:
        trio = [int(spin["number"]) for spin in spins]
        ranking = self.catalog_ranking(trio)
        now = utcnow()
        common = {
            "roulette_id": ROULETTE_ID,
            "trigger_history_id": spins[-1]["history_id"],
            "trigger_timestamp": spins[-1]["timestamp"],
            "trio": trio,
            "trio_spins": spins,
            "configuration": {
                "ordered": True,
                "direction": "forward",
                "top_n": 6,
                "attempts": 1,
                "overlap": False,
            },
            "created_at": now,
            "resolved_at": None,
            "result": None,
        }
        if ranking is None:
            reason = "repeated_numbers" if len(set(trio)) != 3 else "no_evidence"
            document = {**common, "status": "skipped", "skip_reason": reason, "ranking": []}
        else:
            document = {
                **common,
                "status": "pending",
                "skip_reason": None,
                "build_id": ranking["build_id"],
                "catalog_key": ranking["key"],
                "occurrences": ranking["occurrences"],
                "context_events": ranking["context_events"],
                "ranking": ranking["top"],
                "top_numbers": [row["number"] for row in ranking["top"]],
            }
        try:
            inserted = self.signals.insert_one(document)
        except DuplicateKeyError:
            existing = self.signals.find_one({
                "roulette_id": ROULETTE_ID,
                "trigger_history_id": spins[-1]["history_id"],
            })
            return existing.get("_id") if existing and existing.get("status") == "pending" else None
        if document["status"] == "pending":
            log.info("Entrada criada trio=%s top6=%s", trio, document["top_numbers"])
            return inserted.inserted_id
        log.info("Bloco ignorado trio=%s motivo=%s", trio, document["skip_reason"])
        return None

    def settle(self, signal_id: Any, result: dict[str, Any]) -> None:
        pending = self.signals.find_one({"_id": signal_id, "status": "pending"})
        if not pending:
            return
        number = int(result["number"])
        hit = number in pending.get("top_numbers", [])
        self.signals.update_one(
            {"_id": signal_id, "status": "pending"},
            {"$set": {
                "status": "won" if hit else "lost",
                "result": {
                    "history_id": result["history_id"],
                    "number": number,
                    "timestamp": result["timestamp"],
                    "hit": hit,
                },
                "resolved_at": utcnow(),
            }},
        )
        log.info("Entrada finalizada resultado=%d status=%s", number, "won" if hit else "lost")

    def _save_state(self, **values: Any) -> dict[str, Any]:
        values.update({"roulette_id": ROULETTE_ID, "updated_at": utcnow(), "worker_heartbeat_at": utcnow()})
        return self.states.find_one_and_update(
            {"_id": STATE_ID},
            {"$set": values, "$setOnInsert": {"created_at": utcnow()}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )

    def bootstrap(self) -> dict[str, Any]:
        state = self.states.find_one({"_id": STATE_ID})
        if state:
            self._save_state(worker_started_at=utcnow())
            return state
        documents = list(
            self.history.find(
                {"roulette_id": ROULETTE_ID},
                {"value": 1, "timestamp": 1},
            ).sort([("timestamp", DESCENDING), ("_id", DESCENDING)]).limit(3)
        )
        if len(documents) < 3:
            return self._save_state(
                phase="collecting",
                buffer=[],
                pending_signal_id=None,
                last_processed=None,
                worker_started_at=utcnow(),
            )
        spins = [spin_ref(row) for row in reversed(documents)]
        pending_id = self.record_signal(spins)
        return self._save_state(
            phase="awaiting_result" if pending_id else "collecting",
            buffer=spins if pending_id else [],
            pending_signal_id=pending_id,
            last_processed={"history_id": spins[-1]["history_id"], "timestamp": spins[-1]["timestamp"]},
            worker_started_at=utcnow(),
        )

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
            .sort([("timestamp", ASCENDING), ("_id", ASCENDING)])
            .limit(100)
        )

    def process(self, state: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
        spin = spin_ref(document)
        phase = state.get("phase", "collecting")
        buffer = list(state.get("buffer") or [])
        pending_id = state.get("pending_signal_id")
        if phase == "awaiting_result":
            if pending_id:
                self.settle(pending_id, spin)
            next_state = self._save_state(
                phase="collecting",
                buffer=[],
                pending_signal_id=None,
                last_processed={"history_id": spin["history_id"], "timestamp": spin["timestamp"]},
            )
            return next_state

        next_buffer = [*buffer, spin]
        if len(next_buffer) == 3:
            new_pending_id = self.record_signal(next_buffer)
            next_state = self._save_state(
                phase="awaiting_result" if new_pending_id else "collecting",
                buffer=next_buffer if new_pending_id else [],
                pending_signal_id=new_pending_id,
                last_processed={"history_id": spin["history_id"], "timestamp": spin["timestamp"]},
            )
            return next_state
        return self._save_state(
            phase="collecting",
            buffer=next_buffer,
            pending_signal_id=None,
            last_processed={"history_id": spin["history_id"], "timestamp": spin["timestamp"]},
        )

    def heartbeat(self) -> None:
        self.states.update_one({"_id": STATE_ID}, {"$set": {"worker_heartbeat_at": utcnow()}})

    def run(self) -> None:
        self.ensure_indexes()
        state = self.bootstrap()
        log.info("Worker iniciado phase=%s", state.get("phase"))
        while running:
            try:
                documents = self.unseen(state)
                if documents:
                    for document in documents:
                        state = self.process(state, document)
                else:
                    self.heartbeat()
            except PyMongoError:
                log.exception("Falha temporária no MongoDB")
            except Exception:
                log.exception("Falha ao processar resultado")
            time.sleep(POLL_SECONDS)


def stop(*_: Any) -> None:
    global running
    running = False


def main() -> None:
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    TripleContextLiveWorker(client[MONGO_DATABASE]).run()


if __name__ == "__main__":
    main()
