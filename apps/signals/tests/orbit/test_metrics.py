import pytest

from shared.python.roulette.orbit.metrics import random_hit_probability
from shared.python.roulette.orbit.orbit_builder import OrbitBuilder
from shared.python.roulette.orbit.scoring import OrbitalRuleScorer


def test_random_baselines_for_three_attempts():
    assert random_hit_probability(9, 3) == pytest.approx(1 - (28 / 37) ** 3)
    assert random_hit_probability(12, 3) == pytest.approx(1 - (25 / 37) ** 3)


def test_rule_only_layer_never_claims_exclusions():
    history = tuple(index % 37 for index in range(300))
    context = OrbitBuilder(memory_occurrences=4).build_context(history, len(history) - 1)
    prediction = OrbitalRuleScorer().score_context(context, horizon=3)
    assert prediction.excluded == ()
    assert prediction.abstained is True
    assert prediction.metadata["exclusions_enabled"] is False
