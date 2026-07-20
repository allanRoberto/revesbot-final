from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator, Mapping, Sequence

from shared.python.roulette.orbit.metrics import EvaluationAccumulator
from shared.python.roulette.orbit.schemas import CandidateScore, OrbitContext, Prediction, ReplayDecision
from shared.python.roulette.orbit.scoring import OrbitalRuleScorer


def prediction_from_probabilities(
    context: OrbitContext,
    probabilities: Mapping[int, float],
    *,
    horizon: int,
    engine: str,
    excluded: Sequence[int] = (),
) -> Prediction:
    normalized_total = sum(max(0.0, float(probabilities.get(number, 0.0))) for number in range(37))
    if normalized_total <= 0:
        normalized = {number: 1.0 / 37.0 for number in range(37)}
    else:
        normalized = {
            number: max(0.0, float(probabilities.get(number, 0.0))) / normalized_total
            for number in range(37)
        }
    ranking_numbers = sorted(range(37), key=lambda number: (-normalized[number], number))
    rows = tuple(
        CandidateScore(
            number=number,
            positive_score=0.0,
            negative_score=0.0,
            final_score=normalized[number],
            probability=normalized[number],
            uncertainty=0.0,
            lower_probability=normalized[number],
            upper_probability=normalized[number],
            evidence_count=0,
            independent_sources=0,
            relation_types=(),
            explanations=(),
        )
        for number in ranking_numbers
    )
    top9 = tuple(ranking_numbers[:9])
    top12 = tuple(ranking_numbers[:12])
    return Prediction(
        pivot=context.pivot,
        anchor_index=context.anchor_index,
        horizon=max(1, int(horizon)),
        ranking=rows,
        selected_top9=top9,
        selected_top12=top12,
        excluded=tuple(int(value) for value in excluded),
        abstained=False,
        metadata={"engine": engine, "top9_probability_mass": sum(normalized[n] for n in top9)},
    )


@dataclass(frozen=True, slots=True)
class ReplayResult:
    engine: str
    metrics: Mapping[str, float | int]
    evaluated_decisions: int
    predictions: tuple[tuple[Prediction, tuple[int, ...]], ...]


class RuleReplayRunner:
    def __init__(self, scorer: OrbitalRuleScorer | None = None) -> None:
        self.scorer = scorer or OrbitalRuleScorer()

    def run(
        self,
        decisions: Iterable[ReplayDecision],
        *,
        horizon: int = 3,
        max_decisions: int | None = None,
        stride: int = 1,
        keep_predictions: int = 100,
    ) -> ReplayResult:
        accumulator = EvaluationAccumulator()
        kept: list[tuple[Prediction, tuple[int, ...]]] = []
        evaluated = 0
        for source_index, decision in enumerate(decisions):
            if source_index % max(1, int(stride)) != 0:
                continue
            prediction = self.scorer.score_context(decision.context, horizon=horizon)
            targets = tuple(decision.targets[: max(1, int(horizon))])
            accumulator.add(prediction, targets)
            if len(kept) < max(0, int(keep_predictions)):
                kept.append((prediction, targets))
            evaluated += 1
            if max_decisions is not None and evaluated >= int(max_decisions):
                break
        return ReplayResult(
            engine="orbital_rule_v1",
            metrics=accumulator.to_dict(horizon=horizon),
            evaluated_decisions=evaluated,
            predictions=tuple(kept),
        )


def iter_sampled_decisions(
    decisions: Iterable[ReplayDecision],
    *,
    stride: int = 1,
    maximum: int | None = None,
) -> Iterator[ReplayDecision]:
    emitted = 0
    for index, decision in enumerate(decisions):
        if index % max(1, int(stride)):
            continue
        yield decision
        emitted += 1
        if maximum is not None and emitted >= int(maximum):
            return
