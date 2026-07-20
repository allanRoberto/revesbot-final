from __future__ import annotations

from typing import Callable, Iterable, Sequence

from shared.python.roulette.orbit.evidence_graph import DEFAULT_RELATION_WEIGHTS, EvidenceGraphConfig
from shared.python.roulette.orbit.schemas import ReplayDecision
from shared.python.roulette.orbit.scoring import OrbitalRuleScorer

from .replay import RuleReplayRunner


DEFAULT_ABLATIONS = (
    "exact",
    "numeric_sequence",
    "wheel_neighbor",
    "mirror",
    "digit_sum",
    "terminal_family",
    "sector",
)


def run_relation_ablations(
    decisions_factory: Callable[[], Iterable[ReplayDecision]],
    *,
    horizon: int = 3,
    maximum: int = 2000,
    relation_names: Sequence[str] = DEFAULT_ABLATIONS,
) -> dict:
    base_runner = RuleReplayRunner()
    base = base_runner.run(
        decisions_factory(), horizon=horizon, max_decisions=maximum, keep_predictions=0
    )
    variants: dict[str, dict] = {}
    for relation_name in relation_names:
        weights = dict(DEFAULT_RELATION_WEIGHTS)
        weights[str(relation_name)] = 0.0
        scorer = OrbitalRuleScorer(
            graph_config=EvidenceGraphConfig(relation_weights=weights)
        )
        result = RuleReplayRunner(scorer).run(
            decisions_factory(), horizon=horizon, max_decisions=maximum, keep_predictions=0
        )
        variants[str(relation_name)] = {
            "metrics": dict(result.metrics),
            "delta_top9_at_1": float(result.metrics["top9_at_1"]) - float(base.metrics["top9_at_1"]),
            "delta_log_loss": float(result.metrics["multiclass_log_loss"]) - float(base.metrics["multiclass_log_loss"]),
        }
    return {
        "base": dict(base.metrics),
        "ablations": variants,
        "horizon": horizon,
        "maximum_decisions": maximum,
    }
