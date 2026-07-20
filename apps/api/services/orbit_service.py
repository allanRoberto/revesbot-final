from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Sequence
from uuid import uuid4

from shared.python.roulette.orbit.identifiers import build_orbital_identifier
from shared.python.roulette.orbit.multi_pivot import MultiPivotOrbitScorer
from shared.python.roulette.orbit.number_features import get_number_features
from shared.python.roulette.orbit.orbit_builder import OrbitBuilder
from shared.python.roulette.orbit.relation_matrix import RELATION_MATRIX
from shared.python.roulette.orbit.scoring import OrbitalRuleScorer

from api.core.db import ensure_orbit_indexes, history_coll, orbit_predictions_coll


def _prediction_payload(prediction) -> Dict[str, Any]:
    return {
        "pivot": prediction.pivot,
        "anchor_index": prediction.anchor_index,
        "horizon": prediction.horizon,
        "top9": list(prediction.selected_top9),
        "top12": list(prediction.selected_top12),
        "excluded": list(prediction.excluded),
        "abstained": prediction.abstained,
        "metadata": dict(prediction.metadata),
        "ranking": [asdict(row) for row in prediction.ranking],
    }


def _multi_prediction_payload(prediction) -> Dict[str, Any]:
    pivot_rows: List[Dict[str, Any]] = []
    for vote in prediction.pivot_predictions:
        pivot_rows.append({
            "position": vote.position,
            "pivot": vote.pivot,
            "weight": vote.weight,
            "top9": list(vote.prediction.selected_top9),
            "top12": list(vote.prediction.selected_top12),
            "abstained": vote.prediction.abstained,
        })
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


def _context_payload(context) -> Dict[str, Any]:
    occurrences: List[Dict[str, Any]] = []
    for occurrence in context.occurrences:
        observations = []
        for observation in occurrence.observations:
            observations.append({
                **asdict(observation),
                "side": observation.side,
                "distance": observation.distance,
                "identifier": build_orbital_identifier(
                    pivot=observation.pivot,
                    number=observation.number,
                    occurrence_lag=observation.occurrence_lag,
                    relative_offset=observation.relative_offset,
                ),
            })
        occurrences.append({
            "pivot": occurrence.pivot,
            "occurrence_lag": occurrence.occurrence_lag,
            "pivot_spin_index": occurrence.pivot_spin_index,
            "completed_at_anchor": occurrence.completed_at_anchor,
            "observations": observations,
        })
    return {
        "pivot": context.pivot,
        "anchor_index": context.anchor_index,
        "pre_window": context.pre_window,
        "post_window": context.post_window,
        "memory_occurrences": context.memory_occurrences,
        "occurrences": occurrences,
    }


class OrbitService:
    def __init__(self) -> None:
        self.scorer = OrbitalRuleScorer()
        self.multi_pivot_scorer = MultiPivotOrbitScorer(self.scorer)

    @staticmethod
    def describe_number(number: int, pivot: int | None = None) -> Dict[str, Any]:
        features = get_number_features(number)
        payload: Dict[str, Any] = {"features": asdict(features)}
        if pivot is not None:
            payload["pivot"] = int(pivot)
            payload["relation_to_pivot"] = asdict(RELATION_MATRIX.get(int(pivot), int(number)))
        return payload

    def analyze_history(
        self,
        history_chronological: Sequence[int],
        *,
        pivot: int | None = None,
        pre_window: int = 5,
        post_window: int = 5,
        memory_occurrences: int = 6,
        horizon: int = 3,
    ) -> Dict[str, Any]:
        history = tuple(int(value) for value in history_chronological)
        if not history:
            raise ValueError("historico vazio")
        if pivot is None:
            anchor_index = len(history) - 1
        else:
            matches = [index for index, value in enumerate(history) if value == int(pivot)]
            if not matches:
                raise ValueError(f"pivo {pivot} nao encontrado no historico")
            anchor_index = matches[-1]
        builder = OrbitBuilder(
            pre_window=pre_window,
            post_window=post_window,
            memory_occurrences=memory_occurrences,
        )
        context = builder.build_context(history, anchor_index)
        prediction = self.scorer.score_context(context, horizon=horizon)
        return {
            "available": True,
            "engine_version": "orbital_rule_v1",
            "history_size": len(history),
            "context": _context_payload(context),
            "prediction": _prediction_payload(prediction),
        }

    async def analyze_latest(
        self,
        roulette_id: str,
        *,
        pivot: int | None = None,
        history_limit: int = 2000,
        pre_window: int = 5,
        post_window: int = 5,
        memory_occurrences: int = 6,
        horizon: int = 3,
        persist: bool = False,
    ) -> Dict[str, Any]:
        safe_limit = max(50, min(50_000, int(history_limit)))
        documents = await (
            history_coll.find(
                {"roulette_id": str(roulette_id)},
                {"_id": 1, "value": 1, "timestamp": 1},
            )
            .sort([("timestamp", -1), ("_id", -1)])
            .limit(safe_limit)
            .to_list(length=safe_limit)
        )
        if not documents:
            raise LookupError(f"sem historico para {roulette_id}")
        documents.reverse()
        result = self.analyze_history(
            [int(document["value"]) for document in documents],
            pivot=pivot,
            pre_window=pre_window,
            post_window=post_window,
            memory_occurrences=memory_occurrences,
            horizon=horizon,
        )
        result["roulette_id"] = str(roulette_id)
        anchor_index = int(result["context"]["anchor_index"])
        anchor_document = documents[anchor_index]
        result["anchor_timestamp_utc"] = anchor_document.get("timestamp")
        result["anchor_history_id"] = str(anchor_document.get("_id"))
        if persist:
            await ensure_orbit_indexes()
            prediction_id = str(uuid4())
            document = {
                "prediction_id": prediction_id,
                "roulette_id": str(roulette_id),
                "engine_version": result["engine_version"],
                "anchor_timestamp_utc": anchor_document.get("timestamp"),
                "anchor_history_id": str(anchor_document.get("_id")),
                "created_at_utc": datetime.now(timezone.utc),
                "shadow_only": True,
                "result": result,
            }
            await orbit_predictions_coll.insert_one(document)
            result["prediction_id"] = prediction_id
        return result

    def analyze_multi_pivot_history(
        self,
        history_chronological: Sequence[int],
        *,
        pivot_count: int = 3,
        pre_window: int = 5,
        post_window: int = 5,
        memory_occurrences: int = 6,
        horizon: int = 3,
    ) -> Dict[str, Any]:
        history = tuple(int(value) for value in history_chronological)
        safe_pivot_count = max(1, min(5, int(pivot_count)))
        if len(history) < safe_pivot_count:
            raise ValueError(
                f"historico precisa de ao menos {safe_pivot_count} numeros"
            )
        builder = OrbitBuilder(
            pre_window=pre_window,
            post_window=post_window,
            memory_occurrences=memory_occurrences,
        )
        prediction = self.multi_pivot_scorer.score_history(
            history,
            builder=builder,
            pivot_count=safe_pivot_count,
            horizon=horizon,
        )
        return {
            "available": True,
            "engine_version": "orbital_multi_pivot_v1",
            "history_size": len(history),
            "prediction": _multi_prediction_payload(prediction),
        }

    async def analyze_multi_latest(
        self,
        roulette_id: str,
        *,
        pivot_count: int = 3,
        history_limit: int = 600,
        pre_window: int = 5,
        post_window: int = 5,
        memory_occurrences: int = 6,
        horizon: int = 3,
    ) -> Dict[str, Any]:
        safe_limit = max(100, min(20_000, int(history_limit)))
        documents = await (
            history_coll.find(
                {"roulette_id": str(roulette_id)},
                {"_id": 1, "value": 1, "timestamp": 1},
            )
            .sort([("timestamp", -1), ("_id", -1)])
            .limit(safe_limit)
            .to_list(length=safe_limit)
        )
        if not documents:
            raise LookupError(f"sem historico para {roulette_id}")
        documents.reverse()
        result = self.analyze_multi_pivot_history(
            [int(document["value"]) for document in documents],
            pivot_count=pivot_count,
            pre_window=pre_window,
            post_window=post_window,
            memory_occurrences=memory_occurrences,
            horizon=horizon,
        )
        result["roulette_id"] = str(roulette_id)
        result["anchor_timestamp_utc"] = documents[-1].get("timestamp")
        result["anchor_history_id"] = str(documents[-1].get("_id"))
        return result


orbit_service = OrbitService()
