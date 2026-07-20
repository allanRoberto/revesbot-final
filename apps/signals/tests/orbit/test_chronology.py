from shared.python.roulette.orbit.orbit_builder import OrbitBuilder
from shared.python.roulette.orbit.scoring import OrbitalRuleScorer


def test_current_pivot_never_contains_future_side():
    history = [1, 2, 19, 3, 4, 19, 5, 6]
    context = OrbitBuilder(pre_window=2, post_window=2).build_context(history, 5)
    current = context.occurrences[0]
    assert current.occurrence_lag == 0
    assert all(observation.relative_offset < 0 for observation in current.observations)
    assert {observation.spin_index for observation in current.observations} == {3, 4}


def test_prior_occurrence_uses_only_values_known_at_anchor():
    history = [7, 19, 8, 9, 19, 10, 11, 12]
    context = OrbitBuilder(pre_window=1, post_window=5).build_context(history, 4)
    prior = context.occurrences[1]
    assert prior.pivot_spin_index == 1
    assert max(observation.spin_index for observation in prior.observations) <= 4


def test_future_suffix_cannot_change_context_or_prediction():
    prefix = [index % 37 for index in range(200)] + [19]
    history_a = prefix + [1, 2, 3]
    history_b = prefix + [36, 35, 34]
    anchor = len(prefix) - 1
    builder = OrbitBuilder(memory_occurrences=8)
    context_a = builder.build_context(history_a, anchor)
    context_b = builder.build_context(history_b, anchor)
    assert context_a == context_b
    scorer = OrbitalRuleScorer()
    prediction_a = scorer.score_context(context_a)
    prediction_b = scorer.score_context(context_b)
    assert prediction_a.selected_top12 == prediction_b.selected_top12
    assert [row.probability for row in prediction_a.ranking] == [
        row.probability for row in prediction_b.ranking
    ]


def test_replay_targets_are_strictly_after_anchor():
    history = [index % 37 for index in range(350)]
    decision = next(OrbitBuilder().replay_decisions(history, warmup=300, horizon=3))
    anchor = decision.context.anchor_index
    assert decision.targets == tuple(history[anchor + 1 : anchor + 4])


def test_recent_pivot_contexts_share_current_decision_anchor():
    history = [index % 37 for index in range(250)] + [35, 19, 7]
    builder = OrbitBuilder(memory_occurrences=6)

    contexts = builder.build_recent_pivot_contexts(history, pivot_count=3)

    assert [context.pivot for context in contexts] == [7, 19, 35]
    assert all(context.anchor_index == len(history) - 1 for context in contexts)
    assert all(len(context.occurrences) <= 6 for context in contexts)

    penultimate = contexts[1].occurrences[0]
    assert penultimate.pivot_spin_index == len(history) - 2
    assert any(
        observation.number == 7 and observation.relative_offset == 1
        for observation in penultimate.observations
    )
