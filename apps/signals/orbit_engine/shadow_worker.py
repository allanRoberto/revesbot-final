"""Worker observacional e telemetria prospectiva do motor orbital.

O processo registra previsoes imutaveis e acompanha ate dez giros posteriores.
Ele nao publica eventos no Redis e nao possui integracao com apostas.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

from shared.python.roulette.orbit.evidence_graph import EvidenceGraphConfig
from shared.python.roulette.orbit.multi_pivot import MultiPivotOrbitScorer
from shared.python.roulette.orbit.orbit_builder import OrbitBuilder
from shared.python.roulette.orbit.scoring import OrbitalRuleScorer

from .config import OrbitEngineSettings, load_engine_settings
from .snapshot import _mongo_url


LOGGER = logging.getLogger("orbit-shadow")
MULTI_ENGINE_VERSION = "orbital_multi_pivot_v1"
DEFAULT_ROULETTES = (
    "pragmatic-auto-roulette",
    "pragmatic-brazilian-roulette",
    "pragmatic-immersive-roulette-deluxe",
)


def _enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class ShadowWorkerSettings:
    enabled: bool
    roulette_ids: tuple[str, ...]
    history_limit: int
    poll_seconds: float
    horizon: int
    max_attempts: int

    @classmethod
    def from_env(cls) -> "ShadowWorkerSettings":
        roulette_ids = tuple(
            dict.fromkeys(
                value.strip()
                for value in os.getenv(
                    "ORBIT_ROULETTE_IDS", ",".join(DEFAULT_ROULETTES)
                ).split(",")
                if value.strip()
            )
        )
        return cls(
            enabled=_enabled(os.getenv("ORBIT_SHADOW_ENABLED")),
            roulette_ids=roulette_ids,
            history_limit=max(100, min(50_000, int(os.getenv("ORBIT_HISTORY_LIMIT", "600")))),
            poll_seconds=max(0.5, float(os.getenv("ORBIT_POLL_SECONDS", "2"))),
            horizon=max(1, min(10, int(os.getenv("ORBIT_HORIZON", "3")))),
            max_attempts=max(1, min(20, int(os.getenv("ORBIT_MAX_ATTEMPTS", "10")))),
        )


def _scorer(settings: OrbitEngineSettings) -> OrbitalRuleScorer:
    graph = EvidenceGraphConfig(
        relation_weights=settings.relation_weights,
        occurrence_decay=settings.occurrence_decay,
        second_hop_damping=settings.second_hop_damping,
        max_hops=settings.max_hops,
    )
    return OrbitalRuleScorer(graph_config=graph)


def _prediction_payload(prediction) -> dict[str, Any]:
    pivot_rows = [
        {
            "position": vote.position,
            "pivot": vote.pivot,
            "weight": vote.weight,
            "top9": list(vote.prediction.selected_top9),
            "top12": list(vote.prediction.selected_top12),
        }
        for vote in prediction.pivot_predictions
    ]
    return {
        "recent_pivots": list(prediction.recent_pivots),
        "anchor_index": prediction.anchor_index,
        "horizon": prediction.horizon,
        "top9": list(prediction.selected_top9),
        "top12": list(prediction.selected_top12),
        "excluded": list(prediction.excluded),
        "abstained": prediction.abstained,
        "metadata": dict(prediction.metadata),
        "pivots": pivot_rows,
        "ranking": [asdict(row) for row in prediction.ranking],
    }


def advance_trial_document(
    trial: dict[str, Any],
    *,
    number: int,
    history_id: str,
    timestamp: Any,
    max_attempts: int,
) -> dict[str, Any] | None:
    """Retorna somente os campos mutaveis da proxima tentativa, de forma idempotente."""

    existing_ids = [str(value) for value in trial.get("attempt_history_ids") or []]
    if str(history_id) in existing_ids:
        return None
    attempts = [int(value) for value in trial.get("attempt_numbers") or []]
    safe_attempts = max(1, int(max_attempts))
    if len(attempts) >= safe_attempts:
        return None

    attempts.append(int(number))
    existing_ids.append(str(history_id))
    attempt_timestamps = list(trial.get("attempt_timestamps_utc") or [])
    attempt_timestamps.append(timestamp)
    top9_first = trial.get("top9_first_hit_attempt")
    top12_first = trial.get("top12_first_hit_attempt")
    attempt_index = len(attempts)
    if top9_first is None and int(number) in set(trial.get("top9") or []):
        top9_first = attempt_index
    if top12_first is None and int(number) in set(trial.get("top12") or []):
        top12_first = attempt_index
    resolved = attempt_index >= safe_attempts
    payload = {
        "attempt_numbers": attempts,
        "attempt_history_ids": existing_ids,
        "attempt_timestamps_utc": attempt_timestamps,
        "attempts_observed": attempt_index,
        "top9_first_hit_attempt": top9_first,
        "top12_first_hit_attempt": top12_first,
        "status": "resolved" if resolved else "pending",
        "updated_at_utc": datetime.now(timezone.utc),
    }
    if resolved:
        payload["resolved_at_utc"] = timestamp
    return payload


class OrbitShadowWorker:
    def __init__(
        self,
        runtime: ShadowWorkerSettings,
        engine: OrbitEngineSettings,
        *,
        mongo_url: str | None = None,
    ) -> None:
        from pymongo import MongoClient

        self.runtime = runtime
        self.engine = engine
        self.client = MongoClient(
            mongo_url or _mongo_url(),
            connectTimeoutMS=20_000,
            serverSelectionTimeoutMS=20_000,
        )
        database = self.client["roleta_db"]
        self.history = database["history"]
        self.predictions = database["orbit_predictions"]
        self.trials = database["orbit_prediction_trials"]
        self.builder = OrbitBuilder(
            pre_window=engine.pre_window,
            post_window=engine.post_window,
            memory_occurrences=engine.memory_occurrences,
        )
        self.scorer = MultiPivotOrbitScorer(_scorer(engine))
        self._last_anchor: dict[str, str] = {}

    def ensure_indexes(self) -> None:
        from pymongo import ASCENDING, DESCENDING

        self.predictions.create_index(
            [("prediction_id", ASCENDING)],
            name="orbit_predictions_prediction_id",
            unique=True,
        )
        self.predictions.create_index(
            [("roulette_id", ASCENDING), ("anchor_timestamp_utc", DESCENDING)],
            name="orbit_predictions_roulette_anchor_desc",
        )
        self.trials.create_index(
            [("trial_id", ASCENDING)],
            name="orbit_trials_trial_id",
            unique=True,
        )
        self.trials.create_index(
            [("roulette_id", ASCENDING), ("anchor_timestamp_utc", DESCENDING)],
            name="orbit_trials_roulette_anchor_desc",
        )
        self.trials.create_index(
            [("roulette_id", ASCENDING), ("status", ASCENDING), ("anchor_timestamp_utc", DESCENDING)],
            name="orbit_trials_status_anchor_desc",
        )

    def _previous_anchor_id(self, roulette_id: str) -> str | None:
        if roulette_id in self._last_anchor:
            return self._last_anchor[roulette_id]
        latest = self.trials.find_one(
            {"roulette_id": roulette_id},
            {"anchor_history_id": 1},
            sort=[("anchor_timestamp_utc", -1), ("_id", -1)],
        )
        if not latest:
            return None
        return str(latest.get("anchor_history_id") or "") or None

    def _advance_pending(self, roulette_id: str, spin: dict[str, Any]) -> int:
        spin_id = str(spin["_id"])
        updated = 0
        pending = self.trials.find(
            {"roulette_id": roulette_id, "status": "pending"}
        ).sort([("anchor_timestamp_utc", 1), ("_id", 1)])
        for trial in pending:
            payload = advance_trial_document(
                trial,
                number=int(spin["value"]),
                history_id=spin_id,
                timestamp=spin.get("timestamp"),
                max_attempts=self.runtime.max_attempts,
            )
            if payload is None:
                continue
            current_count = int(trial.get("attempts_observed") or 0)
            result = self.trials.update_one(
                {
                    "_id": trial["_id"],
                    "attempts_observed": current_count,
                    "attempt_history_ids": {"$ne": spin_id},
                },
                {"$set": payload},
            )
            updated += int(result.modified_count > 0)
        return updated

    def _create_trial(
        self,
        roulette_id: str,
        documents: Sequence[dict[str, Any]],
    ) -> bool:
        if len(documents) < 3:
            return False
        anchor = documents[-1]
        anchor_id = str(anchor["_id"])
        values = tuple(int(document["value"]) for document in documents)
        prediction = self.scorer.score_history(
            values,
            builder=self.builder,
            pivot_count=3,
            horizon=self.runtime.horizon,
        )
        prediction_payload = _prediction_payload(prediction)
        prediction_id = f"{MULTI_ENGINE_VERSION}:{roulette_id}:{anchor_id}"
        now = datetime.now(timezone.utc)
        common = {
            "roulette_id": roulette_id,
            "engine_version": MULTI_ENGINE_VERSION,
            "anchor_timestamp_utc": anchor.get("timestamp"),
            "anchor_history_id": anchor_id,
            "created_at_utc": now,
            "updated_at_utc": now,
            "shadow_only": True,
            "publishes_betting_signal": False,
        }
        self.predictions.update_one(
            {"prediction_id": prediction_id},
            {
                "$setOnInsert": {
                    **common,
                    "prediction_id": prediction_id,
                    "history_size": len(values),
                    "result": prediction_payload,
                }
            },
            upsert=True,
        )
        result = self.trials.update_one(
            {"trial_id": prediction_id},
            {
                "$setOnInsert": {
                    **common,
                    "trial_id": prediction_id,
                    "recent_pivots": list(prediction.recent_pivots),
                    "top9": list(prediction.selected_top9),
                    "top12": list(prediction.selected_top12),
                    "attempt_numbers": [],
                    "attempt_history_ids": [],
                    "attempt_timestamps_utc": [],
                    "attempts_observed": 0,
                    "top9_first_hit_attempt": None,
                    "top12_first_hit_attempt": None,
                    "status": "pending",
                    "max_attempts": self.runtime.max_attempts,
                }
            },
            upsert=True,
        )
        LOGGER.info(
            "previsao orbital registrada roulette=%s anchor=%s pivots=%s top9=%s",
            roulette_id,
            anchor_id,
            list(prediction.recent_pivots),
            list(prediction.selected_top9),
        )
        return bool(result.upserted_id)

    def process_roulette(self, roulette_id: str) -> bool:
        from pymongo import DESCENDING

        latest = self.history.find_one(
            {"roulette_id": roulette_id},
            {"_id": 1, "value": 1, "timestamp": 1},
            sort=[("timestamp", DESCENDING), ("_id", DESCENDING)],
        )
        if not latest:
            return False
        previous_anchor_id = self._previous_anchor_id(roulette_id)
        if previous_anchor_id == str(latest["_id"]):
            self._last_anchor[roulette_id] = previous_anchor_id
            return False

        documents = list(
            self.history.find(
                {"roulette_id": roulette_id},
                {"_id": 1, "value": 1, "timestamp": 1},
            )
            .sort([("timestamp", DESCENDING), ("_id", DESCENDING)])
            .limit(self.runtime.history_limit)
        )
        if not documents:
            return False
        documents.reverse()
        if previous_anchor_id is None:
            new_indexes = [len(documents) - 1]
        else:
            previous_index = next(
                (
                    index
                    for index, document in enumerate(documents)
                    if str(document["_id"]) == previous_anchor_id
                ),
                None,
            )
            if previous_index is None:
                LOGGER.warning(
                    "ancora anterior saiu da janela; reiniciando do giro atual roulette=%s",
                    roulette_id,
                )
                new_indexes = [len(documents) - 1]
            else:
                new_indexes = list(range(previous_index + 1, len(documents)))

        changed = False
        for index in new_indexes:
            spin = documents[index]
            self._advance_pending(roulette_id, spin)
            changed = self._create_trial(roulette_id, documents[: index + 1]) or changed
            self._last_anchor[roulette_id] = str(spin["_id"])
        return changed

    def run_forever(self) -> None:
        self.ensure_indexes()
        LOGGER.info(
            "shadow mode ativo para %s; nenhuma mensagem de aposta sera publicada",
            ",".join(self.runtime.roulette_ids),
        )
        try:
            while True:
                for roulette_id in self.runtime.roulette_ids:
                    try:
                        self.process_roulette(roulette_id)
                    except Exception:
                        LOGGER.exception("falha ao processar %s", roulette_id)
                time.sleep(self.runtime.poll_seconds)
        finally:
            self.client.close()


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    logging.basicConfig(
        level=os.getenv("ORBIT_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    runtime = ShadowWorkerSettings.from_env()
    if not runtime.enabled:
        LOGGER.warning("ORBIT_SHADOW_ENABLED nao esta ativo; worker encerrado sem efeitos")
        return 0
    if not runtime.roulette_ids:
        raise RuntimeError("ORBIT_ROULETTE_IDS nao contem IDs validos")
    engine = load_engine_settings()
    if not engine.shadow_only:
        raise RuntimeError("configuracao orbital precisa permanecer em shadow_only")
    OrbitShadowWorker(runtime, engine).run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
