"""Ranker orbital explicavel; serve como baseline e gerador de atributos."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .candidate_state import CandidateLedger, CandidateState
from .evidence_graph import EvidenceGraph, EvidenceGraphConfig
from .probability import softmax
from .schemas import CandidateScore, OrbitContext, Prediction


@dataclass(frozen=True, slots=True)
class RuleScorerConfig:
    temperature: float = 2.2
    source_diversity_bonus: float = 0.08
    relation_diversity_bonus: float = 0.12
    crossed_side_bonus: float = 0.08
    exclusion_upper_probability: float = 1.0 / 37.0
    enable_exclusions: bool = False
    uncertainty_scale: float = 0.70
    abstain_top9_mass_threshold: float = 9.0 / 37.0 + 0.015
    force_abstention: bool = True
    max_explanations: int = 6


class OrbitalRuleScorer:
    def __init__(
        self,
        *,
        graph_config: EvidenceGraphConfig | None = None,
        scorer_config: RuleScorerConfig | None = None,
    ) -> None:
        self.graph = EvidenceGraph(graph_config)
        self.ledger = CandidateLedger()
        self.config = scorer_config or RuleScorerConfig()

    def _score_state(self, state: CandidateState) -> float:
        score = float(state.positive_energy) - float(state.negative_energy)
        score *= 1.0 + (self.config.source_diversity_bonus * math.log1p(state.independent_sources))
        score *= 1.0 + (self.config.relation_diversity_bonus * math.log1p(len(state.relation_types)))
        if state.crossed_sides:
            score *= 1.0 + self.config.crossed_side_bonus
        return score

    def score_context(self, context: OrbitContext, *, horizon: int = 1) -> Prediction:
        evidence = self.graph.build(context)
        states = self.ledger.build_states(context, evidence)
        raw_scores = {number: self._score_state(state) for number, state in states.items()}
        probabilities = softmax(raw_scores, temperature=self.config.temperature)
        candidate_rows: list[CandidateScore] = []
        for number in range(37):
            state = states[number]
            probability = float(probabilities[number])
            uncertainty = min(
                probability,
                self.config.uncertainty_scale / math.sqrt(max(1, state.independent_sources + 1)) / 37.0,
            )
            explanations = tuple(
                f"{row.source_number}->{number}:{row.relation_type} "
                f"T{row.occurrence_lag:+d}/{row.relative_offset:+d} ({row.raw_weight:.3f})"
                for row in state.evidence[: self.config.max_explanations]
            )
            candidate_rows.append(
                CandidateScore(
                    number=number,
                    positive_score=state.positive_energy,
                    negative_score=state.negative_energy,
                    final_score=raw_scores[number],
                    probability=probability,
                    uncertainty=uncertainty,
                    lower_probability=max(0.0, probability - uncertainty),
                    upper_probability=min(1.0, probability + uncertainty),
                    evidence_count=state.evidence_count,
                    independent_sources=state.independent_sources,
                    relation_types=state.relation_types,
                    explanations=explanations,
                )
            )
        candidate_rows.sort(key=lambda item: (-item.probability, -item.final_score, item.number))
        top9 = tuple(item.number for item in candidate_rows[:9])
        top12 = tuple(item.number for item in candidate_rows[:12])
        excluded = (
            tuple(
                item.number
                for item in candidate_rows[12:]
                if item.upper_probability < self.config.exclusion_upper_probability
            )
            if self.config.enable_exclusions
            else ()
        )
        top9_mass = sum(item.probability for item in candidate_rows[:9])
        abstained = self.config.force_abstention or (
            top9_mass < self.config.abstain_top9_mass_threshold
        )
        return Prediction(
            pivot=context.pivot,
            anchor_index=context.anchor_index,
            horizon=max(1, int(horizon)),
            ranking=tuple(candidate_rows),
            selected_top9=top9,
            selected_top12=top12,
            excluded=excluded,
            abstained=abstained,
            metadata={
                "engine": "orbital_rule_v1",
                "top9_probability_mass": round(top9_mass, 8),
                "evidence_rows": sum(len(rows) for rows in evidence.values()),
                "occurrence_count": len(context.occurrences),
                "exclusions_enabled": self.config.enable_exclusions,
                "force_abstention": self.config.force_abstention,
            },
        )
