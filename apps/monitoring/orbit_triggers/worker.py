"""Worker prospectivo para as sete estrategias de gatilho orbital.

O processo consome somente previsoes previamente congeladas pelo shadow worker,
nao reconstrui entradas depois do resultado e nao publica sinais de aposta.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.signals.orbit_engine.shadow_worker import DEFAULT_ROULETTES, MULTI_ENGINE_VERSION
from apps.signals.orbit_engine.snapshot import _mongo_url
from shared.python.roulette.orbit.triggers.catalog import (
    DEFAULT_MAX_ATTEMPTS,
    TRIGGER_ENGINE_VERSION,
)
from shared.python.roulette.orbit.triggers.state_machine import (
    TriggerActivation,
    advance_candidate,
    advance_trigger_trial_document,
    build_ryan_entry,
    expand_with_neighbors,
)


LOGGER = logging.getLogger("orbit-trigger-monitor")


def _enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


class OrbitTriggerWorker:
    def __init__(
        self,
        *,
        roulette_ids: Sequence[str],
        poll_seconds: float = 2.0,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        mongo_url: str | None = None,
    ) -> None:
        from pymongo import MongoClient

        self.roulette_ids = tuple(dict.fromkeys(str(value) for value in roulette_ids if str(value)))
        self.poll_seconds = max(0.5, float(poll_seconds))
        self.max_attempts = max(1, min(20, int(max_attempts)))
        self.client = MongoClient(
            mongo_url or _mongo_url(),
            connectTimeoutMS=20_000,
            serverSelectionTimeoutMS=20_000,
        )
        database = self.client["roleta_db"]
        self.orbit_trials = database["orbit_prediction_trials"]
        self.trigger_trials = database["orbit_trigger_trials"]
        self.candidates = database["orbit_trigger_candidates"]
        self.state = database["orbit_trigger_worker_state"]

    def ensure_indexes(self) -> None:
        from pymongo import ASCENDING, DESCENDING

        self.trigger_trials.create_index(
            [("event_id", ASCENDING)],
            name="orbit_trigger_trials_event_id",
            unique=True,
        )
        self.trigger_trials.create_index(
            [
                ("strategy_slug", ASCENDING),
                ("roulette_id", ASCENDING),
                ("activation_timestamp_utc", DESCENDING),
            ],
            name="orbit_trigger_trials_strategy_roulette_activation_desc",
        )
        self.trigger_trials.create_index(
            [
                ("strategy_slug", ASCENDING),
                ("roulette_id", ASCENDING),
                ("status", ASCENDING),
                ("activation_timestamp_utc", DESCENDING),
            ],
            name="orbit_trigger_trials_strategy_status_activation_desc",
        )
        self.candidates.create_index(
            [("candidate_id", ASCENDING)],
            name="orbit_trigger_candidates_candidate_id",
            unique=True,
        )
        self.candidates.create_index(
            [
                ("roulette_id", ASCENDING),
                ("strategy_slug", ASCENDING),
                ("status", ASCENDING),
                ("created_at_utc", ASCENDING),
            ],
            name="orbit_trigger_candidates_active",
        )

    @staticmethod
    def _prediction_payload(document: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "trial_id": str(document.get("trial_id") or ""),
            "roulette_id": str(document.get("roulette_id") or ""),
            "anchor_history_id": str(document.get("anchor_history_id") or ""),
            "anchor_timestamp_utc": document.get("anchor_timestamp_utc"),
            "recent_pivots": [int(value) for value in document.get("recent_pivots") or []],
            "top9": [int(value) for value in document.get("top9") or []][:9],
        }

    def _event_id(
        self,
        strategy_slug: str,
        roulette_id: str,
        activation_history_id: str,
        source_trial_id: str,
    ) -> str:
        parts = [TRIGGER_ENGINE_VERSION, strategy_slug, roulette_id, activation_history_id]
        if strategy_slug == "distancia":
            parts.append(source_trial_id)
        return ":".join(parts)

    def _create_trigger_trial(
        self,
        *,
        activation: TriggerActivation,
        current_prediction: Mapping[str, Any],
    ) -> bool:
        entry_numbers = list(dict.fromkeys(int(value) for value in activation.entry_numbers))
        if not entry_numbers:
            return False
        strategy = activation.strategy_slug
        roulette_id = str(current_prediction["roulette_id"])
        anchor_id = str(current_prediction["anchor_history_id"])
        event_id = self._event_id(strategy, roulette_id, anchor_id, activation.source_trial_id)
        now = datetime.now(timezone.utc)
        document = {
            "event_id": event_id,
            "engine_version": TRIGGER_ENGINE_VERSION,
            "orbit_engine_version": MULTI_ENGINE_VERSION,
            "strategy_slug": strategy,
            "roulette_id": roulette_id,
            "activation_history_id": anchor_id,
            "activation_timestamp_utc": current_prediction.get("anchor_timestamp_utc"),
            "activation_number": int(current_prediction["recent_pivots"][0]),
            "activation_prediction_id": str(current_prediction["trial_id"]),
            "source_trial_id": activation.source_trial_id,
            "recent_pivots": list(current_prediction.get("recent_pivots") or []),
            "base_numbers": list(activation.base_numbers),
            "entry_numbers": entry_numbers,
            "target_size": len(entry_numbers),
            "metadata": dict(activation.metadata),
            "attempt_numbers": [],
            "attempt_history_ids": [],
            "attempt_timestamps_utc": [],
            "attempts_observed": 0,
            "first_hit_attempt": None,
            "max_attempts": self.max_attempts,
            "status": "pending",
            "shadow_only": True,
            "publishes_betting_signal": False,
            "created_at_utc": now,
            "updated_at_utc": now,
        }
        result = self.trigger_trials.update_one(
            {"event_id": event_id},
            {"$setOnInsert": document},
            upsert=True,
        )
        if result.upserted_id:
            LOGGER.info(
                "entrada registrada strategy=%s roulette=%s anchor=%s targets=%s",
                strategy,
                roulette_id,
                anchor_id,
                entry_numbers,
            )
        return bool(result.upserted_id)

    def _create_candidate(
        self,
        *,
        strategy_slug: str,
        source_prediction: Mapping[str, Any],
        extra: Mapping[str, Any] | None = None,
    ) -> bool:
        source_trial_id = str(source_prediction["trial_id"])
        candidate_id = f"{TRIGGER_ENGINE_VERSION}:{strategy_slug}:{source_trial_id}"
        now = datetime.now(timezone.utc)
        document = {
            "candidate_id": candidate_id,
            "engine_version": TRIGGER_ENGINE_VERSION,
            "strategy_slug": strategy_slug,
            "roulette_id": str(source_prediction["roulette_id"]),
            "source_trial_id": source_trial_id,
            "source_anchor_history_id": str(source_prediction["anchor_history_id"]),
            "source_anchor_timestamp_utc": source_prediction.get("anchor_timestamp_utc"),
            "source_recent_pivots": list(source_prediction.get("recent_pivots") or []),
            "source_top9": list(source_prediction.get("top9") or [])[:9],
            "observed_spins": 0,
            "status": "armed",
            "created_at_utc": now,
            "updated_at_utc": now,
            **dict(extra or {}),
        }
        result = self.candidates.update_one(
            {"candidate_id": candidate_id},
            {"$setOnInsert": document},
            upsert=True,
        )
        return bool(result.upserted_id)

    def _advance_pending_trials(self, prediction: Mapping[str, Any]) -> int:
        roulette_id = str(prediction["roulette_id"])
        history_id = str(prediction["anchor_history_id"])
        number = int(prediction["recent_pivots"][0])
        updated = 0
        pending = self.trigger_trials.find(
            {"roulette_id": roulette_id, "status": "pending"}
        ).sort([("activation_timestamp_utc", 1), ("_id", 1)])
        for trial in pending:
            payload = advance_trigger_trial_document(
                trial,
                number=number,
                history_id=history_id,
                timestamp=prediction.get("anchor_timestamp_utc"),
                max_attempts=self.max_attempts,
            )
            if payload is None:
                continue
            current_count = int(trial.get("attempts_observed") or 0)
            result = self.trigger_trials.update_one(
                {
                    "_id": trial["_id"],
                    "attempts_observed": current_count,
                    "attempt_history_ids": {"$ne": history_id},
                },
                {"$set": payload},
            )
            updated += int(result.modified_count > 0)
        return updated

    def _advance_candidates(self, prediction: Mapping[str, Any]) -> int:
        roulette_id = str(prediction["roulette_id"])
        number = int(prediction["recent_pivots"][0])
        activated = 0
        rows = self.candidates.find(
            {"roulette_id": roulette_id, "status": "armed"}
        ).sort([("created_at_utc", 1), ("_id", 1)])
        for candidate in rows:
            transition = advance_candidate(
                candidate,
                number=number,
                current_prediction=prediction,
            )
            current_observed = int(candidate.get("observed_spins") or 0)
            result = self.candidates.update_one(
                {
                    "_id": candidate["_id"],
                    "status": "armed",
                    "observed_spins": current_observed,
                },
                {"$set": dict(transition.update)},
            )
            if not result.modified_count or transition.activation is None:
                continue
            activated += int(
                self._create_trigger_trial(
                    activation=transition.activation,
                    current_prediction=prediction,
                )
            )
        return activated

    def _previous_prediction(self, document: Mapping[str, Any]) -> dict[str, Any] | None:
        previous = self.orbit_trials.find_one(
            {
                "roulette_id": str(document["roulette_id"]),
                "_id": {"$lt": document["_id"]},
            },
            sort=[("_id", -1)],
        )
        return self._prediction_payload(previous) if previous else None

    def _create_direct_entries(self, prediction: Mapping[str, Any]) -> int:
        top9 = tuple(int(value) for value in prediction.get("top9") or [])[:9]
        source_id = str(prediction["trial_id"])
        created = 0
        allan_numbers = expand_with_neighbors(top9, span=1)
        created += int(
            self._create_trigger_trial(
                activation=TriggerActivation(
                    strategy_slug="allan",
                    entry_numbers=allan_numbers,
                    base_numbers=top9,
                    source_trial_id=source_id,
                    metadata={"neighbor_span": 1},
                ),
                current_prediction=prediction,
            )
        )

        ryan = build_ryan_entry(prediction.get("recent_pivots") or [], top9)
        if ryan:
            created += int(
                self._create_trigger_trial(
                    activation=TriggerActivation(
                        strategy_slug="ryan",
                        entry_numbers=ryan["entry_numbers"],
                        base_numbers=ryan["base_numbers"],
                        source_trial_id=source_id,
                        metadata={
                            "confluence": list(ryan["confluence"]),
                            "remaining_pivots": list(ryan["remaining_pivots"]),
                            "pivot_neighbors": list(ryan["pivot_neighbors"]),
                            "neighbor_span": 2,
                        },
                    ),
                    current_prediction=prediction,
                )
            )
        return created

    def _arm_new_candidates(
        self,
        prediction: Mapping[str, Any],
        previous_prediction: Mapping[str, Any] | None,
    ) -> int:
        created = 0
        current_number = int(prediction["recent_pivots"][0])
        if previous_prediction and current_number in set(previous_prediction.get("top9") or []):
            created += int(
                self._create_candidate(
                    strategy_slug="green-primeira",
                    source_prediction=previous_prediction,
                    extra={
                        "wait_remaining": 1,
                        "first_hit_history_id": str(prediction["anchor_history_id"]),
                    },
                )
            )

        if current_number == 0:
            created += int(
                self._create_candidate(
                    strategy_slug="inception",
                    source_prediction=prediction,
                )
            )
            created += int(
                self._create_candidate(
                    strategy_slug="inception-primeiros-4",
                    source_prediction=prediction,
                )
            )

        created += int(
            self._create_candidate(
                strategy_slug="interrompimento",
                source_prediction=prediction,
                extra={"phase": "learning", "gap": 0, "rhythm_hits": 0},
            )
        )
        created += int(
            self._create_candidate(
                strategy_slug="distancia",
                source_prediction=prediction,
                extra={"phase": "observing", "wait_remaining": 0},
            )
        )
        return created

    def _process_prediction(self, document: Mapping[str, Any]) -> None:
        prediction = self._prediction_payload(document)
        if len(prediction["recent_pivots"]) < 3 or not prediction["top9"]:
            return
        self._advance_pending_trials(prediction)
        self._advance_candidates(prediction)
        previous = self._previous_prediction(document)
        self._create_direct_entries(prediction)
        self._arm_new_candidates(prediction, previous)

    def process_roulette(self, roulette_id: str) -> int:
        state = self.state.find_one({"_id": roulette_id})
        if not state:
            latest = self.orbit_trials.find_one(
                {"roulette_id": roulette_id},
                sort=[("_id", -1)],
            )
            if latest:
                self.state.update_one(
                    {"_id": roulette_id},
                    {
                        "$set": {
                            "last_prediction_object_id": latest["_id"],
                            "last_prediction_id": str(latest.get("trial_id") or ""),
                            "bootstrapped_at_utc": datetime.now(timezone.utc),
                            "updated_at_utc": datetime.now(timezone.utc),
                        }
                    },
                    upsert=True,
                )
                LOGGER.info("baseline prospectiva iniciada roulette=%s", roulette_id)
            return 0

        query: dict[str, Any] = {"roulette_id": roulette_id}
        if state.get("last_prediction_object_id") is not None:
            query["_id"] = {"$gt": state["last_prediction_object_id"]}
        documents = list(self.orbit_trials.find(query).sort([("_id", 1)]))
        processed = 0
        for document in documents:
            self._process_prediction(document)
            self.state.update_one(
                {"_id": roulette_id},
                {
                    "$set": {
                        "last_prediction_object_id": document["_id"],
                        "last_prediction_id": str(document.get("trial_id") or ""),
                        "updated_at_utc": datetime.now(timezone.utc),
                    }
                },
                upsert=True,
            )
            processed += 1
        return processed

    def run_forever(self) -> None:
        self.ensure_indexes()
        LOGGER.info(
            "monitor prospectivo ativo strategies=7 attempts=%s roulettes=%s",
            self.max_attempts,
            ",".join(self.roulette_ids),
        )
        try:
            while True:
                for roulette_id in self.roulette_ids:
                    try:
                        self.process_roulette(roulette_id)
                    except Exception:
                        LOGGER.exception("falha ao processar %s", roulette_id)
                time.sleep(self.poll_seconds)
        finally:
            self.client.close()


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    logging.basicConfig(
        level=os.getenv("ORBIT_TRIGGER_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if not _enabled(os.getenv("ORBIT_TRIGGER_ENABLED")):
        LOGGER.warning("ORBIT_TRIGGER_ENABLED nao esta ativo; monitor encerrado sem efeitos")
        return 0
    roulette_ids = tuple(
        value.strip()
        for value in os.getenv("ORBIT_ROULETTE_IDS", ",".join(DEFAULT_ROULETTES)).split(",")
        if value.strip()
    )
    worker = OrbitTriggerWorker(
        roulette_ids=roulette_ids,
        poll_seconds=float(os.getenv("ORBIT_TRIGGER_POLL_SECONDS", "2")),
        max_attempts=int(os.getenv("ORBIT_TRIGGER_MAX_ATTEMPTS", "5")),
    )
    worker.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
