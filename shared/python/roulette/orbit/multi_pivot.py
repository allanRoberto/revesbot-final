"""Consenso de ranking produzido pelos ultimos pivôs conhecidos."""

from __future__ import annotations

from typing import Sequence

from .orbit_builder import OrbitBuilder
from .schemas import (
    MultiPivotCandidate,
    MultiPivotPrediction,
    PivotVotePrediction,
)
from .scoring import OrbitalRuleScorer


DEFAULT_PIVOT_WEIGHTS = (1.0, 0.85, 0.70)


class MultiPivotOrbitScorer:
    """Agrega rankings por Borda ponderada, sem somar energias incompatíveis."""

    def __init__(self, scorer: OrbitalRuleScorer | None = None) -> None:
        self.scorer = scorer or OrbitalRuleScorer()

    @staticmethod
    def _weights(count: int) -> tuple[float, ...]:
        if count <= len(DEFAULT_PIVOT_WEIGHTS):
            return DEFAULT_PIVOT_WEIGHTS[:count]
        values = list(DEFAULT_PIVOT_WEIGHTS)
        while len(values) < count:
            values.append(values[-1] * 0.82)
        return tuple(values)

    def score_history(
        self,
        history_chronological: Sequence[int],
        *,
        builder: OrbitBuilder | None = None,
        pivot_count: int = 3,
        horizon: int = 3,
    ) -> MultiPivotPrediction:
        orbit_builder = builder or OrbitBuilder(memory_occurrences=6)
        contexts = orbit_builder.build_recent_pivot_contexts(
            history_chronological,
            pivot_count=pivot_count,
        )
        weights = self._weights(len(contexts))
        votes = tuple(
            PivotVotePrediction(
                position=position,
                pivot=context.pivot,
                weight=weights[position],
                prediction=self.scorer.score_context(context, horizon=horizon),
            )
            for position, context in enumerate(contexts)
        )
        weight_total = sum(weights)
        rank_maps = [
            {row.number: rank for rank, row in enumerate(vote.prediction.ranking)}
            for vote in votes
        ]
        probability_maps = [
            {row.number: row.probability for row in vote.prediction.ranking}
            for vote in votes
        ]
        rows: list[MultiPivotCandidate] = []
        for number in range(37):
            pivot_ranks = tuple(rank_map[number] + 1 for rank_map in rank_maps)
            weighted_rank_score = sum(
                weight * ((37 - (rank - 1)) / 37.0)
                for weight, rank in zip(weights, pivot_ranks)
            ) / weight_total
            probability = sum(
                weight * probability_map[number]
                for weight, probability_map in zip(weights, probability_maps)
            ) / weight_total
            rows.append(
                MultiPivotCandidate(
                    number=number,
                    probability=probability,
                    weighted_rank_score=weighted_rank_score,
                    top9_support=sum(rank <= 9 for rank in pivot_ranks),
                    top12_support=sum(rank <= 12 for rank in pivot_ranks),
                    pivot_ranks=pivot_ranks,
                )
            )
        rows.sort(
            key=lambda row: (
                -row.weighted_rank_score,
                -row.top9_support,
                -row.top12_support,
                -row.probability,
                row.number,
            )
        )
        top9 = tuple(row.number for row in rows[:9])
        top12 = tuple(row.number for row in rows[:12])
        return MultiPivotPrediction(
            recent_pivots=tuple(context.pivot for context in contexts),
            anchor_index=contexts[0].anchor_index,
            horizon=max(1, int(horizon)),
            ranking=tuple(rows),
            selected_top9=top9,
            selected_top12=top12,
            pivot_predictions=votes,
            excluded=(),
            abstained=True,
            metadata={
                "engine": "orbital_multi_pivot_v1",
                "aggregation": "weighted_borda",
                "pivot_weights": weights,
                "memory_occurrences_per_pivot": orbit_builder.memory_occurrences,
            },
        )
