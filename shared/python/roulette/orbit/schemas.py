"""Tipos de dominio do motor orbital, sem dependencias de framework."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class NumberFeatures:
    number: int
    wheel_index: int
    parity: str
    color: str
    dozen: int
    column: int
    sector: str
    digit_sum_group: int
    digit_sum_position: int
    mirror: int | None
    terminal_family: str | None
    terminal_position: int
    wheel_neighbors: tuple[int, int]


@dataclass(frozen=True, slots=True)
class PairRelation:
    source: int
    target: int
    exact: bool
    numeric_delta: int
    numeric_distance: int
    numeric_sequence_distance: int | None
    wheel_delta: int
    wheel_distance: int
    mirror: bool
    same_parity: bool
    same_color: bool
    same_dozen: bool
    same_column: bool
    same_sector: bool
    same_digit_sum: bool
    same_terminal_family: bool

    def active_types(self) -> tuple[str, ...]:
        active: list[str] = []
        if self.exact:
            active.append("exact")
        if self.numeric_sequence_distance == 1:
            active.append("numeric_sequence")
        if self.wheel_distance == 1:
            active.append("wheel_neighbor")
        if self.mirror:
            active.append("mirror")
        if self.same_digit_sum:
            active.append("digit_sum")
        if self.same_terminal_family:
            active.append("terminal_family")
        if self.same_sector:
            active.append("sector")
        if self.same_color:
            active.append("color")
        if self.same_parity:
            active.append("parity")
        if self.same_dozen:
            active.append("dozen")
        if self.same_column:
            active.append("column")
        return tuple(active)


@dataclass(frozen=True, slots=True)
class OrbitObservation:
    pivot: int
    number: int
    occurrence_lag: int
    relative_offset: int
    spin_index: int
    occurrence_index: int
    known_at_anchor: bool = True

    @property
    def side(self) -> str:
        return "before" if self.relative_offset < 0 else "after"

    @property
    def distance(self) -> int:
        return abs(self.relative_offset)


@dataclass(frozen=True, slots=True)
class OrbitOccurrence:
    pivot: int
    occurrence_lag: int
    pivot_spin_index: int
    observations: tuple[OrbitObservation, ...]
    completed_at_anchor: bool


@dataclass(frozen=True, slots=True)
class OrbitContext:
    pivot: int
    anchor_index: int
    occurrences: tuple[OrbitOccurrence, ...]
    pre_window: int
    post_window: int
    memory_occurrences: int

    @property
    def observations(self) -> tuple[OrbitObservation, ...]:
        return tuple(observation for occurrence in self.occurrences for observation in occurrence.observations)


@dataclass(frozen=True, slots=True)
class Evidence:
    candidate: int
    source_number: int
    source_spin_index: int
    occurrence_lag: int
    relative_offset: int
    relation_type: str
    raw_weight: float
    path: tuple[int, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class CandidateScore:
    number: int
    positive_score: float
    negative_score: float
    final_score: float
    probability: float
    uncertainty: float
    lower_probability: float
    upper_probability: float
    evidence_count: int
    independent_sources: int
    relation_types: tuple[str, ...]
    explanations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Prediction:
    pivot: int
    anchor_index: int
    horizon: int
    ranking: tuple[CandidateScore, ...]
    selected_top9: tuple[int, ...]
    selected_top12: tuple[int, ...]
    excluded: tuple[int, ...]
    abstained: bool
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReplayDecision:
    context: OrbitContext
    targets: tuple[int, ...]
    timestamp: Any | None = None


@dataclass(frozen=True, slots=True)
class PivotVotePrediction:
    position: int
    pivot: int
    weight: float
    prediction: Prediction


@dataclass(frozen=True, slots=True)
class MultiPivotCandidate:
    number: int
    probability: float
    weighted_rank_score: float
    top9_support: int
    top12_support: int
    pivot_ranks: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class MultiPivotPrediction:
    recent_pivots: tuple[int, ...]
    anchor_index: int
    horizon: int
    ranking: tuple[MultiPivotCandidate, ...]
    selected_top9: tuple[int, ...]
    selected_top12: tuple[int, ...]
    pivot_predictions: tuple[PivotVotePrediction, ...]
    excluded: tuple[int, ...]
    abstained: bool
    metadata: Mapping[str, Any] = field(default_factory=dict)


def as_int_sequence(values: Sequence[Any]) -> tuple[int, ...]:
    return tuple(int(value) for value in values)
