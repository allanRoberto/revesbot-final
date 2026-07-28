"""Runtime resiliente dos workers de sinais de terminais.

Redis reduz a latência. MongoDB permanece como fonte autoritativa e é reconciliado
periodicamente para que quedas de Pub/Sub ou reinícios não eliminem giros.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

import redis as redis_lib
from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection

from shared.python.roulette.terminal_signals.catalog import (
    DEFAULT_MAX_ATTEMPTS,
    ENGINE_VERSION,
    get_variant,
)
from shared.python.roulette.terminal_signals.engine import detect_variant
from shared.python.roulette.terminal_signals.state_machine import advance_trial


LOGGER = logging.getLogger("terminal-signals-worker")


def _utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def _parse_object_id(value: Any) -> ObjectId | None:
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(str(value))
    except Exception:
        return None


@dataclass
class RouletteRuntimeState:
    roulette_id: str
    history: list[int] = field(default_factory=list)
    last_history_id: ObjectId | None = None
    last_timestamp_utc: datetime | None = None
    active_trials: dict[str, dict[str, Any]] = field(default_factory=dict)


class TerminalSignalWorker:
    def __init__(
        self,
        *,
        variant_slug: str,
        roulette_ids_raw: str = "all",
        mongo_url: str | None = None,
        redis_url: str | None = None,
        result_channel: str = "new_result",
        history_limit: int = 500,
        reconcile_seconds: float = 5.0,
        discovery_seconds: float = 60.0,
        max_batch: int = 2_000,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        self.variant = get_variant(variant_slug)
        self.roulette_ids_raw = str(roulette_ids_raw or "all")
        self.result_channel = str(result_channel or "new_result")
        self.history_limit = max(50, min(5_000, int(history_limit)))
        self.reconcile_seconds = max(0.5, float(reconcile_seconds))
        self.discovery_seconds = max(10.0, float(discovery_seconds))
        self.max_batch = max(100, min(20_000, int(max_batch)))
        self.max_attempts = max(1, min(20, int(max_attempts)))

        effective_mongo = mongo_url or os.getenv("MONGO_URL") or "mongodb://127.0.0.1:27017/roleta_db"
        self.mongo = MongoClient(
            effective_mongo,
            connectTimeoutMS=20_000,
            serverSelectionTimeoutMS=20_000,
        )
        self.db = self.mongo["roleta_db"]
        self.history_coll: Collection = self.db["history"]
        self.trials_coll: Collection = self.db["terminal_signal_trials"]
        self.worker_state_coll: Collection = self.db["terminal_signal_worker_state"]

        effective_redis = redis_url or os.getenv("REDIS_CONNECT") or "redis://127.0.0.1:6379"
        self.redis = redis_lib.from_url(effective_redis, decode_responses=True)
        self.states: dict[str, RouletteRuntimeState] = {}

    def ensure_indexes(self) -> None:
        self.trials_coll.create_index(
            [("event_id", ASCENDING)],
            name="terminal_signal_trials_event_id",
            unique=True,
        )
        self.trials_coll.create_index(
            [
                ("variant", ASCENDING),
                ("roulette_id", ASCENDING),
                ("activation_timestamp_utc", DESCENDING),
            ],
            name="terminal_signal_trials_variant_roulette_activation_desc",
        )
        self.trials_coll.create_index(
            [
                ("variant", ASCENDING),
                ("roulette_id", ASCENDING),
                ("status", ASCENDING),
                ("activation_timestamp_utc", DESCENDING),
            ],
            name="terminal_signal_trials_variant_roulette_status_desc",
        )
        self.trials_coll.create_index(
            [("roulette_id", ASCENDING), ("activation_history_id", ASCENDING)],
            name="terminal_signal_trials_roulette_history",
        )
        self.worker_state_coll.create_index(
            [("worker_variant", ASCENDING), ("roulette_id", ASCENDING)],
            name="terminal_signal_worker_variant_roulette",
            unique=True,
        )

    def _configured_roulettes(self) -> list[str]:
        raw = self.roulette_ids_raw.strip()
        if raw.lower() not in {"", "all", "*"}:
            return list(dict.fromkeys(value.strip() for value in raw.split(",") if value.strip()))
        return sorted(
            value
            for value in self.history_coll.distinct("roulette_id")
            if isinstance(value, str) and value.startswith("pragmatic-")
        )

    def _load_pending(self, roulette_id: str) -> dict[str, dict[str, Any]]:
        rows = self.trials_coll.find(
            {
                "variant": self.variant.slug,
                "roulette_id": roulette_id,
                "status": "pending",
            }
        ).sort([("activation_timestamp_utc", ASCENDING), ("_id", ASCENDING)])
        return {str(row["event_id"]): row for row in rows}

    def _history_at_offset(
        self,
        roulette_id: str,
        last_history_id: ObjectId | None,
    ) -> list[int]:
        query: dict[str, Any] = {"roulette_id": roulette_id}
        if last_history_id is not None:
            query["_id"] = {"$lte": last_history_id}
        rows = self.history_coll.find(query, {"value": 1}).sort("_id", DESCENDING).limit(
            self.history_limit
        )
        return [
            int(row["value"])
            for row in rows
            if 0 <= int(row.get("value", -1)) <= 36
        ]

    def _persist_offset(self, state: RouletteRuntimeState) -> None:
        now = datetime.now(timezone.utc)
        self.worker_state_coll.update_one(
            {
                "worker_variant": self.variant.slug,
                "roulette_id": state.roulette_id,
            },
            {
                "$set": {
                    "engine_version": ENGINE_VERSION,
                    "last_history_id": str(state.last_history_id) if state.last_history_id else None,
                    "last_timestamp_utc": state.last_timestamp_utc,
                    "updated_at_utc": now,
                },
                "$setOnInsert": {"created_at_utc": now},
            },
            upsert=True,
        )

    def _initialize_roulette(self, roulette_id: str) -> RouletteRuntimeState:
        stored = self.worker_state_coll.find_one(
            {
                "worker_variant": self.variant.slug,
                "roulette_id": roulette_id,
            }
        )
        last_history_id = _parse_object_id((stored or {}).get("last_history_id"))
        last_timestamp = (stored or {}).get("last_timestamp_utc")
        if last_history_id is None:
            latest = self.history_coll.find_one(
                {"roulette_id": roulette_id},
                {"_id": 1, "timestamp": 1},
                sort=[("_id", DESCENDING)],
            )
            if latest:
                last_history_id = latest["_id"]
                last_timestamp = latest.get("timestamp")

        state = RouletteRuntimeState(
            roulette_id=roulette_id,
            history=self._history_at_offset(roulette_id, last_history_id),
            last_history_id=last_history_id,
            last_timestamp_utc=_utc(last_timestamp) if last_timestamp else None,
            active_trials=self._load_pending(roulette_id),
        )
        self.states[roulette_id] = state
        self._persist_offset(state)
        LOGGER.info(
            "[%s][%s] inicializado history=%d pendentes=%d offset=%s",
            self.variant.slug,
            roulette_id,
            len(state.history),
            len(state.active_trials),
            state.last_history_id,
        )
        return state

    def discover_roulettes(self) -> int:
        created = 0
        for roulette_id in self._configured_roulettes():
            if roulette_id not in self.states:
                self._initialize_roulette(roulette_id)
                created += 1
        return created

    def _advance_pending(
        self,
        state: RouletteRuntimeState,
        *,
        number: int,
        history_id: str,
        timestamp: datetime,
    ) -> None:
        remaining: dict[str, dict[str, Any]] = {}
        for event_id, trial in list(state.active_trials.items()):
            update = advance_trial(
                trial,
                number=number,
                history_id=history_id,
                timestamp=timestamp,
            )
            if update is None:
                if str(trial.get("status") or "") == "pending":
                    remaining[event_id] = trial
                continue
            result = self.trials_coll.update_one(
                {
                    "event_id": event_id,
                    "status": "pending",
                    "attempt_history_ids": {"$ne": history_id},
                },
                {"$set": update},
            )
            if result.modified_count:
                trial.update(update)
                if update["status"] == "pending":
                    remaining[event_id] = trial
                else:
                    LOGGER.info(
                        "[%s][%s] resolvido event=%s outcome=%s tentativa=%s",
                        self.variant.slug,
                        state.roulette_id,
                        event_id,
                        update["outcome"],
                        update["first_hit_attempt"],
                    )
            else:
                latest = self.trials_coll.find_one({"event_id": event_id})
                if latest and latest.get("status") == "pending":
                    remaining[event_id] = latest
        state.active_trials = remaining

    def _create_candidate(
        self,
        state: RouletteRuntimeState,
        *,
        history_id: str,
        timestamp: datetime,
    ) -> None:
        candidate = detect_variant(self.variant, state.history)
        if candidate is None:
            return
        event_id = ":".join(
            [ENGINE_VERSION, self.variant.slug, state.roulette_id, history_id]
        )
        now = datetime.now(timezone.utc)
        document = {
            "event_id": event_id,
            "engine_version": ENGINE_VERSION,
            "variant": self.variant.slug,
            "roulette_id": state.roulette_id,
            "activation_history_id": history_id,
            "activation_timestamp_utc": timestamp,
            "activation_snapshot": list(state.history[:20]),
            **candidate.as_document(),
            "max_attempts": self.max_attempts,
            "attempts": [],
            "attempt_history_ids": [],
            "attempts_observed": 0,
            "first_hit_attempt": None,
            "status": "pending",
            "outcome": "pending",
            "shadow_only": True,
            "publishes_betting_signal": False,
            "execution_eligible": True,
            "created_at_utc": now,
            "updated_at_utc": now,
            "resolved_at_utc": None,
        }
        result = self.trials_coll.update_one(
            {"event_id": event_id},
            {"$setOnInsert": document},
            upsert=True,
        )
        if result.upserted_id:
            document["_id"] = result.upserted_id
            state.active_trials[event_id] = document
            LOGGER.info(
                "[%s][%s] sinal event=%s terminais=%s/%s alvos=%s",
                self.variant.slug,
                state.roulette_id,
                event_id,
                document.get("terminal_a"),
                document.get("terminal_b"),
                document["targets"],
            )
        elif event_id not in state.active_trials:
            existing = self.trials_coll.find_one({"event_id": event_id, "status": "pending"})
            if existing:
                state.active_trials[event_id] = existing

    def process_history_document(
        self,
        state: RouletteRuntimeState,
        document: Mapping[str, Any],
    ) -> None:
        history_object_id = _parse_object_id(document.get("_id"))
        if history_object_id is None:
            return
        if state.last_history_id is not None and history_object_id <= state.last_history_id:
            return
        number = int(document.get("value"))
        if not 0 <= number <= 36:
            return
        timestamp = _utc(document.get("timestamp"))
        history_id = str(history_object_id)

        # O giro atual resolve sinais anteriores antes de poder formar um novo.
        self._advance_pending(
            state,
            number=number,
            history_id=history_id,
            timestamp=timestamp,
        )
        state.history.insert(0, number)
        del state.history[self.history_limit :]
        self._create_candidate(state, history_id=history_id, timestamp=timestamp)

        state.last_history_id = history_object_id
        state.last_timestamp_utc = timestamp
        self._persist_offset(state)

    def reconcile_roulette(self, roulette_id: str) -> int:
        state = self.states.get(roulette_id) or self._initialize_roulette(roulette_id)
        query: dict[str, Any] = {"roulette_id": roulette_id}
        if state.last_history_id is not None:
            query["_id"] = {"$gt": state.last_history_id}
        rows = list(
            self.history_coll.find(
                query,
                {"value": 1, "timestamp": 1},
            )
            .sort("_id", ASCENDING)
            .limit(self.max_batch)
        )
        for row in rows:
            self.process_history_document(state, row)
        if len(rows) >= self.max_batch:
            LOGGER.warning(
                "[%s][%s] lote máximo atingido; o próximo ciclo continuará a reconciliação",
                self.variant.slug,
                roulette_id,
            )
        return len(rows)

    def reconcile_all(self) -> int:
        processed = 0
        for roulette_id in tuple(self.states):
            try:
                processed += self.reconcile_roulette(roulette_id)
            except Exception:
                LOGGER.exception("[%s][%s] falha na reconciliação", self.variant.slug, roulette_id)
        return processed

    @staticmethod
    def _message_slug(raw: Any) -> str | None:
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        slug = str(payload.get("slug") or payload.get("roulette_id") or "").strip()
        return slug or None

    def run_forever(self) -> None:
        self.ensure_indexes()
        self.discover_roulettes()
        LOGGER.info(
            "worker iniciado variant=%s mesas=%d canal=%s reconcile=%.1fs",
            self.variant.slug,
            len(self.states),
            self.result_channel,
            self.reconcile_seconds,
        )

        pubsub = self.redis.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(self.result_channel)
        last_reconcile = 0.0
        last_discovery = 0.0
        while True:
            try:
                message = pubsub.get_message(timeout=1.0)
                if message:
                    slug = self._message_slug(message.get("data"))
                    if slug and slug.startswith("pragmatic-"):
                        if slug not in self.states:
                            self._initialize_roulette(slug)
                        self.reconcile_roulette(slug)

                now = time.monotonic()
                if now - last_reconcile >= self.reconcile_seconds:
                    self.reconcile_all()
                    last_reconcile = now
                if now - last_discovery >= self.discovery_seconds:
                    self.discover_roulettes()
                    last_discovery = now
                time.sleep(0.05)
            except KeyboardInterrupt:
                LOGGER.info("encerrando worker variant=%s", self.variant.slug)
                return
            except Exception:
                LOGGER.exception("erro no loop variant=%s; tentando novamente", self.variant.slug)
                time.sleep(2.0)
