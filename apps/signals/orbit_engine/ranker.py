"""Ranker tabular incremental para 37 candidatos por decisao."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping

from shared.python.roulette.orbit.probability import softmax
from shared.python.roulette.orbit.evidence_graph import EvidenceGraphConfig
from shared.python.roulette.orbit.schemas import ReplayDecision

from .features import FEATURE_NAMES, CandidateFeatureBuilder, OrbitFeaturePipeline


@dataclass(frozen=True, slots=True)
class RankerPrediction:
    scores: Mapping[int, float]
    probabilities: Mapping[int, float]
    ranking: tuple[int, ...]


class OnlineCandidateRanker:
    """Regressao logistica por candidato com normalizacao listwise via softmax.

    O treinamento usa ``partial_fit`` para nao materializar centenas de milhoes
    de linhas candidatas em memoria.
    """

    def __init__(
        self,
        *,
        alpha: float = 0.0005,
        positive_weight: float = 18.0,
        random_state: int = 42,
        feature_pipeline: OrbitFeaturePipeline | None = None,
    ) -> None:
        try:
            from sklearn.linear_model import SGDClassifier
            from sklearn.preprocessing import StandardScaler
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("scikit-learn e necessario para o ranker orbital") from exc
        self.scaler = StandardScaler()
        self.model = SGDClassifier(
            loss="log_loss",
            penalty="elasticnet",
            alpha=float(alpha),
            l1_ratio=0.05,
            learning_rate="optimal",
            average=True,
            random_state=int(random_state),
        )
        self.positive_weight = max(1.0, float(positive_weight))
        self.pipeline = feature_pipeline or OrbitFeaturePipeline()
        self._fitted = False
        self.training_decisions = 0

    def fit(
        self,
        decisions: Iterable[ReplayDecision],
        *,
        max_decisions: int | None = None,
        batch_decisions: int = 128,
    ) -> "OnlineCandidateRanker":
        import numpy as np

        rows: list[dict[str, float]] = []
        labels: list[int] = []
        weights: list[float] = []
        decision_count = 0

        def flush() -> None:
            if not rows:
                return
            matrix = np.asarray(CandidateFeatureBuilder.vectorize(rows), dtype=np.float64)
            target = np.asarray(labels, dtype=np.int8)
            sample_weights = np.asarray(weights, dtype=np.float64)
            self.scaler.partial_fit(matrix)
            transformed = self.scaler.transform(matrix)
            self.model.partial_fit(
                transformed,
                target,
                classes=np.asarray([0, 1], dtype=np.int8),
                sample_weight=sample_weights,
            )
            self._fitted = True
            rows.clear()
            labels.clear()
            weights.clear()

        for decision in decisions:
            target_number = int(decision.targets[0])
            candidate_rows, _states = self.pipeline.extract(decision.context)
            rows.extend(candidate_rows)
            labels.extend(1 if candidate == target_number else 0 for candidate in range(37))
            weights.extend(
                self.positive_weight if candidate == target_number else 1.0
                for candidate in range(37)
            )
            decision_count += 1
            if decision_count % max(1, int(batch_decisions)) == 0:
                flush()
            if max_decisions is not None and decision_count >= int(max_decisions):
                break
        flush()
        self.training_decisions += decision_count
        if not self._fitted:
            raise ValueError("nenhuma decisao disponivel para treinar o ranker")
        return self

    def predict(self, context) -> RankerPrediction:
        if not self._fitted:
            raise RuntimeError("ranker ainda nao foi treinado")
        import numpy as np

        rows, _states = self.pipeline.extract(context)
        matrix = np.asarray(CandidateFeatureBuilder.vectorize(rows), dtype=np.float64)
        transformed = self.scaler.transform(matrix)
        raw = self.model.decision_function(transformed)
        scores = {number: float(raw[number]) for number in range(37)}
        probabilities = softmax(scores)
        ranking = tuple(sorted(range(37), key=lambda number: (-probabilities[number], number)))
        return RankerPrediction(scores=scores, probabilities=probabilities, ranking=ranking)

    def save(self, path: Path) -> None:
        if not self._fitted:
            raise RuntimeError("nao e possivel salvar ranker nao treinado")
        import joblib

        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "model": self.model,
                "scaler": self.scaler,
                "positive_weight": self.positive_weight,
                "feature_names": FEATURE_NAMES,
                "training_decisions": self.training_decisions,
                "graph_config": asdict(self.pipeline.graph.config),
            },
            path,
        )

    @classmethod
    def load(cls, path: Path) -> "OnlineCandidateRanker":
        import joblib

        payload = joblib.load(path)
        if tuple(payload.get("feature_names") or ()) != tuple(FEATURE_NAMES):
            raise ValueError("artefato usa conjunto de features incompativel")
        graph_payload = dict(payload.get("graph_config") or {})
        pipeline = OrbitFeaturePipeline(EvidenceGraphConfig(**graph_payload)) if graph_payload else None
        instance = cls(
            positive_weight=float(payload.get("positive_weight", 18.0)),
            feature_pipeline=pipeline,
        )
        instance.model = payload["model"]
        instance.scaler = payload["scaler"]
        instance.training_decisions = int(payload.get("training_decisions", 0))
        instance._fitted = True
        return instance
