"""Modelo discreto da probabilidade de materializacao dentro do horizonte."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping

from shared.python.roulette.orbit.schemas import ReplayDecision
from shared.python.roulette.orbit.evidence_graph import EvidenceGraphConfig

from .features import FEATURE_NAMES, CandidateFeatureBuilder, OrbitFeaturePipeline


@dataclass(frozen=True, slots=True)
class SurvivalPrediction:
    appearance_probability: Mapping[int, float]
    nonappearance_probability: Mapping[int, float]
    ranking: tuple[int, ...]


class CandidateSurvivalModel:
    def __init__(self, *, random_state: int = 43, pipeline: OrbitFeaturePipeline | None = None) -> None:
        try:
            from sklearn.linear_model import SGDClassifier
            from sklearn.preprocessing import StandardScaler
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("scikit-learn e necessario para o modelo de sobrevivencia") from exc
        self.scaler = StandardScaler()
        self.model = SGDClassifier(
            loss="log_loss",
            penalty="l2",
            alpha=0.001,
            average=True,
            random_state=int(random_state),
        )
        self.pipeline = pipeline or OrbitFeaturePipeline()
        self._fitted = False
        self.horizon = 3

    def fit(
        self,
        decisions: Iterable[ReplayDecision],
        *,
        horizon: int = 3,
        max_decisions: int | None = None,
        batch_decisions: int = 128,
    ) -> "CandidateSurvivalModel":
        import numpy as np

        self.horizon = max(1, int(horizon))
        rows: list[dict[str, float]] = []
        labels: list[int] = []
        count = 0

        def flush() -> None:
            if not rows:
                return
            matrix = np.asarray(CandidateFeatureBuilder.vectorize(rows), dtype=np.float64)
            target = np.asarray(labels, dtype=np.int8)
            self.scaler.partial_fit(matrix)
            transformed = self.scaler.transform(matrix)
            self.model.partial_fit(transformed, target, classes=np.asarray([0, 1], dtype=np.int8))
            self._fitted = True
            rows.clear()
            labels.clear()

        for decision in decisions:
            future = set(int(value) for value in decision.targets[: self.horizon])
            candidate_rows, _states = self.pipeline.extract(decision.context)
            rows.extend(candidate_rows)
            labels.extend(1 if candidate in future else 0 for candidate in range(37))
            count += 1
            if count % max(1, int(batch_decisions)) == 0:
                flush()
            if max_decisions is not None and count >= int(max_decisions):
                break
        flush()
        if not self._fitted:
            raise ValueError("nenhuma decisao para treinar sobrevivencia")
        return self

    def predict(self, context) -> SurvivalPrediction:
        if not self._fitted:
            raise RuntimeError("modelo de sobrevivencia nao treinado")
        import numpy as np

        rows, _states = self.pipeline.extract(context)
        matrix = np.asarray(CandidateFeatureBuilder.vectorize(rows), dtype=np.float64)
        probabilities = self.model.predict_proba(self.scaler.transform(matrix))[:, 1]
        appearance = {number: float(probabilities[number]) for number in range(37)}
        nonappearance = {number: 1.0 - appearance[number] for number in range(37)}
        ranking = tuple(sorted(range(37), key=lambda number: (-appearance[number], number)))
        return SurvivalPrediction(appearance, nonappearance, ranking)

    def save(self, path: Path) -> None:
        if not self._fitted:
            raise RuntimeError("nao e possivel salvar sobrevivencia nao treinada")
        import joblib

        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "model": self.model,
                "scaler": self.scaler,
                "horizon": self.horizon,
                "feature_names": FEATURE_NAMES,
                "graph_config": asdict(self.pipeline.graph.config),
            },
            path,
        )

    @classmethod
    def load(cls, path: Path) -> "CandidateSurvivalModel":
        import joblib

        payload = joblib.load(path)
        if tuple(payload.get("feature_names") or ()) != tuple(FEATURE_NAMES):
            raise ValueError("artefato usa conjunto de features incompativel")
        graph_payload = dict(payload.get("graph_config") or {})
        pipeline = OrbitFeaturePipeline(EvidenceGraphConfig(**graph_payload)) if graph_payload else None
        instance = cls(pipeline=pipeline)
        instance.model = payload["model"]
        instance.scaler = payload["scaler"]
        instance.horizon = max(1, int(payload.get("horizon", 3)))
        instance._fitted = True
        return instance
