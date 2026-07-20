"""Estado explicavel das pendencias produzidas pelo grafo orbital."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .schemas import Evidence, OrbitContext


@dataclass(frozen=True, slots=True)
class CandidateState:
    pivot: int
    candidate: int
    status: str
    positive_energy: float
    negative_energy: float
    independent_sources: int
    evidence_count: int
    relation_types: tuple[str, ...]
    first_activation_lag: int | None
    last_reinforcement_lag: int | None
    direct_activations: int
    transformed_activations: int
    side_before_support: float
    side_after_support: float
    crossed_sides: bool
    evidence: tuple[Evidence, ...]


class CandidateLedger:
    def __init__(
        self,
        *,
        activation_threshold: float = 0.65,
        reinforcement_threshold: float = 1.75,
        diversity_threshold: int = 2,
    ) -> None:
        self.activation_threshold = float(activation_threshold)
        self.reinforcement_threshold = float(reinforcement_threshold)
        self.diversity_threshold = max(1, int(diversity_threshold))

    def build_states(
        self,
        context: OrbitContext,
        evidence_by_candidate: Mapping[int, Sequence[Evidence]],
    ) -> dict[int, CandidateState]:
        states: dict[int, CandidateState] = {}
        for candidate in range(37):
            rows = tuple(evidence_by_candidate.get(candidate, ()))
            positive = sum(float(row.raw_weight) for row in rows)
            relation_types = tuple(sorted({row.relation_type for row in rows}))
            sources = {row.source_spin_index for row in rows}
            lags = [row.occurrence_lag for row in rows]
            direct = sum(1 for row in rows if row.relation_type == "exact")
            transformed = len(rows) - direct
            before = sum(row.raw_weight for row in rows if row.relative_offset < 0)
            after = sum(row.raw_weight for row in rows if row.relative_offset > 0)
            crossed = before > 0 and after > 0

            if positive < self.activation_threshold:
                status = "inactive"
            elif (
                positive >= self.reinforcement_threshold
                and len(relation_types) >= self.diversity_threshold
            ):
                status = "reinforced"
            elif lags and max(lags) < 0:
                status = "pending"
            else:
                status = "activated"

            states[candidate] = CandidateState(
                pivot=context.pivot,
                candidate=candidate,
                status=status,
                positive_energy=positive,
                negative_energy=0.0,
                independent_sources=len(sources),
                evidence_count=len(rows),
                relation_types=relation_types,
                first_activation_lag=(min(lags) if lags else None),
                last_reinforcement_lag=(max(lags) if lags else None),
                direct_activations=direct,
                transformed_activations=transformed,
                side_before_support=before,
                side_after_support=after,
                crossed_sides=crossed,
                evidence=rows,
            )
        return states
