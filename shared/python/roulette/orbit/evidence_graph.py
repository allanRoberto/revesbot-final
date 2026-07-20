"""Propagacao controlada de evidencias em um grafo numerico de 37 nos."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .relation_matrix import RELATION_MATRIX, RelationMatrix
from .schemas import Evidence, OrbitContext, OrbitObservation


DEFAULT_RELATION_WEIGHTS = {
    "exact": 3.0,
    "numeric_sequence": 1.0,
    "wheel_neighbor": 1.0,
    "mirror": 1.5,
    "digit_sum": 1.2,
    "terminal_family": 0.45,
    "sector": 0.15,
    "color": 0.0,
    "parity": 0.0,
    "dozen": 0.0,
    "column": 0.0,
}


@dataclass(frozen=True, slots=True)
class EvidenceGraphConfig:
    relation_weights: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_RELATION_WEIGHTS))
    occurrence_decay: float = 0.78
    second_hop_damping: float = 0.20
    max_hops: int = 2
    max_intermediates_per_source: int = 8
    max_evidence_per_candidate: int = 128
    completed_occurrence_bonus: float = 1.0
    current_occurrence_bonus: float = 1.15


def _position_weight(observation: OrbitObservation) -> float:
    return 1.0 / max(1, observation.distance)


def _occurrence_weight(observation: OrbitObservation, decay: float) -> float:
    return float(decay) ** abs(int(observation.occurrence_lag))


class EvidenceGraph:
    def __init__(
        self,
        config: EvidenceGraphConfig | None = None,
        relation_matrix: RelationMatrix = RELATION_MATRIX,
    ) -> None:
        self.config = config or EvidenceGraphConfig()
        self.relation_matrix = relation_matrix
        self._direct_cache: tuple[tuple[tuple[int, str, float], ...], ...] = tuple(
            self._build_direct_cache(source) for source in range(37)
        )
        self._second_hop_cache: tuple[
            tuple[tuple[int, str, float, tuple[int, ...]], ...], ...
        ] = tuple(self._build_second_hop_cache(source) for source in range(37))

    def _build_direct_cache(self, source: int) -> tuple[tuple[int, str, float], ...]:
        rows: list[tuple[int, str, float]] = []
        for candidate in range(37):
            relation = self.relation_matrix.get(source, candidate)
            for relation_type in relation.active_types():
                weight = float(self.config.relation_weights.get(relation_type, 0.0))
                if weight > 0:
                    rows.append((candidate, relation_type, weight))
        return tuple(rows)

    def _build_second_hop_cache(
        self,
        source: int,
    ) -> tuple[tuple[int, str, float, tuple[int, ...]], ...]:
        if self.config.max_hops < 2 or self.config.second_hop_damping <= 0:
            return ()
        intermediates = [
            row
            for row in self._direct_cache[source]
            if row[1] in {"exact", "mirror", "wheel_neighbor", "digit_sum"}
        ]
        intermediates.sort(key=lambda item: (-item[2], item[0], item[1]))
        rows: list[tuple[int, str, float, tuple[int, ...]]] = []
        for intermediate, first_relation, first_weight in intermediates[
            : self.config.max_intermediates_per_source
        ]:
            for candidate, second_relation, second_weight in self._direct_cache[intermediate]:
                if candidate in {source, intermediate}:
                    continue
                if second_relation not in {"numeric_sequence", "wheel_neighbor", "mirror", "digit_sum"}:
                    continue
                rows.append((
                    candidate,
                    f"{first_relation}>{second_relation}",
                    first_weight * second_weight * float(self.config.second_hop_damping),
                    (source, intermediate, candidate),
                ))
        return tuple(rows)

    def _base_weight(self, observation: OrbitObservation) -> float:
        current_bonus = (
            self.config.current_occurrence_bonus
            if observation.occurrence_lag == 0
            else self.config.completed_occurrence_bonus
        )
        return (
            _position_weight(observation)
            * _occurrence_weight(observation, self.config.occurrence_decay)
            * current_bonus
        )

    def build(self, context: OrbitContext) -> dict[int, tuple[Evidence, ...]]:
        # Uma janela pode conter o mesmo giro em varias ocorrencias proximas do
        # pivo. A chave abaixo conserva somente a evidencia mais forte do giro.
        deduplicated: dict[tuple[int, int, str, tuple[int, ...]], Evidence] = {}

        for observation in context.observations:
            base_weight = self._base_weight(observation)
            for candidate, relation_type, relation_weight in self._direct_cache[observation.number]:
                weight = base_weight * relation_weight
                path = (observation.number, candidate)
                evidence = Evidence(
                    candidate=candidate,
                    source_number=observation.number,
                    source_spin_index=observation.spin_index,
                    occurrence_lag=observation.occurrence_lag,
                    relative_offset=observation.relative_offset,
                    relation_type=relation_type,
                    raw_weight=weight,
                    path=path,
                )
                key = (observation.spin_index, candidate, relation_type, path)
                previous = deduplicated.get(key)
                if previous is None or evidence.raw_weight > previous.raw_weight:
                    deduplicated[key] = evidence

            for candidate, relation_type, weight_factor, path in self._second_hop_cache[
                observation.number
            ]:
                evidence = Evidence(
                    candidate=candidate,
                    source_number=observation.number,
                    source_spin_index=observation.spin_index,
                    occurrence_lag=observation.occurrence_lag,
                    relative_offset=observation.relative_offset,
                    relation_type=relation_type,
                    raw_weight=base_weight * weight_factor,
                    path=path,
                )
                key = (observation.spin_index, candidate, relation_type, path)
                previous = deduplicated.get(key)
                if previous is None or evidence.raw_weight > previous.raw_weight:
                    deduplicated[key] = evidence

        by_candidate: dict[int, list[Evidence]] = {number: [] for number in range(37)}
        for evidence in deduplicated.values():
            by_candidate[evidence.candidate].append(evidence)
        result: dict[int, tuple[Evidence, ...]] = {}
        for candidate, evidence_rows in by_candidate.items():
            evidence_rows.sort(
                key=lambda item: (
                    -item.raw_weight,
                    -item.occurrence_lag,
                    abs(item.relative_offset),
                    item.source_spin_index,
                    item.relation_type,
                )
            )
            result[candidate] = tuple(evidence_rows[: self.config.max_evidence_per_candidate])
        return result
