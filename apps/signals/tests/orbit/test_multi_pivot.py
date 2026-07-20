import pytest

from shared.python.roulette.orbit.multi_pivot import MultiPivotOrbitScorer
from shared.python.roulette.orbit.orbit_builder import OrbitBuilder


def test_multi_pivot_ranking_combines_three_recent_numbers_deterministically():
    history = [index % 37 for index in range(500)] + [35, 19, 7]
    scorer = MultiPivotOrbitScorer()
    builder = OrbitBuilder(memory_occurrences=6)

    prediction = scorer.score_history(
        history,
        builder=builder,
        pivot_count=3,
        horizon=3,
    )
    repeated = scorer.score_history(
        history,
        builder=builder,
        pivot_count=3,
        horizon=3,
    )

    assert prediction.recent_pivots == (7, 19, 35)
    assert [vote.weight for vote in prediction.pivot_predictions] == [1.0, 0.85, 0.70]
    assert len(prediction.ranking) == 37
    assert len(prediction.selected_top9) == 9
    assert len(prediction.selected_top12) == 12
    assert prediction.selected_top9 == prediction.selected_top12[:9]
    assert sum(row.probability for row in prediction.ranking) == pytest.approx(1.0)
    assert prediction.selected_top12 == repeated.selected_top12
    assert prediction.excluded == ()
    assert prediction.abstained is True
