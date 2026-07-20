from __future__ import annotations

from typing import Mapping, Sequence

from shared.python.roulette.orbit.candidate_state import CandidateState
from shared.python.roulette.orbit.candidate_state import CandidateLedger
from shared.python.roulette.orbit.evidence_graph import EvidenceGraph, EvidenceGraphConfig
from shared.python.roulette.orbit.number_features import get_number_features
from shared.python.roulette.orbit.relation_matrix import RELATION_MATRIX
from shared.python.roulette.orbit.schemas import OrbitContext


CORE_FEATURE_NAMES = (
    "wheel_delta",
    "wheel_distance",
    "numeric_delta",
    "numeric_distance",
    "pivot_mirror",
    "same_parity",
    "same_color",
    "same_dozen",
    "same_column",
    "same_sector",
    "same_digit_sum",
    "same_terminal_family",
    "candidate_wheel_index",
    "candidate_dozen",
    "candidate_column",
    "candidate_digit_sum_group",
    "candidate_digit_sum_position",
    "candidate_terminal_position",
    "positive_energy",
    "negative_energy",
    "independent_sources",
    "evidence_count",
    "relation_type_count",
    "direct_activations",
    "transformed_activations",
    "side_before_support",
    "side_after_support",
    "crossed_sides",
    "activation_age",
    "last_reinforcement_age",
)
RELATION_COUNT_NAMES = (
    "exact",
    "numeric_sequence",
    "wheel_neighbor",
    "mirror",
    "digit_sum",
    "terminal_family",
    "sector",
)
FEATURE_NAMES = (
    *CORE_FEATURE_NAMES,
    *(f"relation_count_{name}" for name in RELATION_COUNT_NAMES),
    *(f"candidate_id_{number}" for number in range(37)),
    *(f"pivot_id_{number}" for number in range(37)),
)


class CandidateFeatureBuilder:
    def build(
        self,
        context: OrbitContext,
        states: Mapping[int, CandidateState],
        candidate: int,
    ) -> dict[str, float]:
        candidate_number = int(candidate)
        state = states[candidate_number]
        relation = RELATION_MATRIX.get(context.pivot, candidate_number)
        features = get_number_features(candidate_number)
        relation_counts = {name: 0 for name in RELATION_COUNT_NAMES}
        for evidence in state.evidence:
            for name in RELATION_COUNT_NAMES:
                if name in evidence.relation_type.split(">"):
                    relation_counts[name] += 1
        row: dict[str, float] = {
            "wheel_delta": relation.wheel_delta / 18.0,
            "wheel_distance": relation.wheel_distance / 18.0,
            "numeric_delta": relation.numeric_delta / 36.0,
            "numeric_distance": relation.numeric_distance / 36.0,
            "pivot_mirror": float(relation.mirror),
            "same_parity": float(relation.same_parity),
            "same_color": float(relation.same_color),
            "same_dozen": float(relation.same_dozen),
            "same_column": float(relation.same_column),
            "same_sector": float(relation.same_sector),
            "same_digit_sum": float(relation.same_digit_sum),
            "same_terminal_family": float(relation.same_terminal_family),
            "candidate_wheel_index": features.wheel_index / 36.0,
            "candidate_dozen": features.dozen / 3.0,
            "candidate_column": features.column / 3.0,
            "candidate_digit_sum_group": features.digit_sum_group / 9.0,
            "candidate_digit_sum_position": features.digit_sum_position / 4.0,
            "candidate_terminal_position": features.terminal_position / 3.0,
            "positive_energy": state.positive_energy,
            "negative_energy": state.negative_energy,
            "independent_sources": float(state.independent_sources),
            "evidence_count": float(state.evidence_count),
            "relation_type_count": float(len(state.relation_types)),
            "direct_activations": float(state.direct_activations),
            "transformed_activations": float(state.transformed_activations),
            "side_before_support": state.side_before_support,
            "side_after_support": state.side_after_support,
            "crossed_sides": float(state.crossed_sides),
            "activation_age": float(abs(state.first_activation_lag or 0)),
            "last_reinforcement_age": float(abs(state.last_reinforcement_lag or 0)),
        }
        for name, count in relation_counts.items():
            row[f"relation_count_{name}"] = float(count)
        for number in range(37):
            row[f"candidate_id_{number}"] = float(candidate_number == number)
            row[f"pivot_id_{number}"] = float(context.pivot == number)
        return row

    @staticmethod
    def vectorize(rows: Sequence[Mapping[str, float]]) -> list[list[float]]:
        return [[float(row.get(name, 0.0)) for name in FEATURE_NAMES] for row in rows]


class OrbitFeaturePipeline:
    def __init__(self, graph_config: EvidenceGraphConfig | None = None) -> None:
        self.graph = EvidenceGraph(graph_config)
        self.ledger = CandidateLedger()
        self.builder = CandidateFeatureBuilder()

    def extract(self, context: OrbitContext) -> tuple[list[dict[str, float]], Mapping[int, CandidateState]]:
        evidence = self.graph.build(context)
        states = self.ledger.build_states(context, evidence)
        rows = [self.builder.build(context, states, candidate) for candidate in range(37)]
        return rows, states
