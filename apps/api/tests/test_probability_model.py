from __future__ import annotations

import pytest

from shared.python.roulette.probability_model import (
    ProbabilityModelConfig,
    calculate_number_probabilities,
)


def test_probability_model_returns_normalized_ranking() -> None:
    chronological = list(range(37)) * 8

    result = calculate_number_probabilities(
        chronological,
        order="chronological",
        number_count=10,
    )

    assert len(result["ranking"]) == 37
    assert len(result["selected"]) == 10
    assert len(set(result["selected"])) == 10
    assert sum(row["probability"] for row in result["ranking"]) == pytest.approx(1.0)
    assert result["diagnostics"]["probabilities_sum"] == pytest.approx(1.0)
    assert result["diagnostics"]["score_is_calibrated_probability"] is False


def test_newest_first_and_chronological_orders_are_equivalent() -> None:
    chronological = [number % 37 for number in range(240)]

    chronological_result = calculate_number_probabilities(
        chronological,
        order="chronological",
        number_count=8,
    )
    newest_first_result = calculate_number_probabilities(
        list(reversed(chronological)),
        order="newest_first",
        number_count=8,
    )

    assert newest_first_result["last_number"] == chronological[-1]
    assert newest_first_result["selected"] == chronological_result["selected"]
    assert [row["probability"] for row in newest_first_result["ranking"]] == pytest.approx(
        [row["probability"] for row in chronological_result["ranking"]]
    )


def test_recent_repetition_changes_the_ranking_without_breaking_bounds() -> None:
    history = list(range(37)) * 5 + [7] * 30
    result = calculate_number_probabilities(
        history,
        number_count=5,
        config=ProbabilityModelConfig(minimum_history=10),
    )

    assert 7 in result["selected"]
    assert all(0.0 < row["probability"] < 1.0 for row in result["ranking"])


def test_probability_model_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError, match="historico insuficiente"):
        calculate_number_probabilities([1, 2, 3])

    with pytest.raises(ValueError, match="inteiros entre 0 e 36"):
        calculate_number_probabilities([1] * 10 + [40])

    with pytest.raises(ValueError, match="number_count"):
        calculate_number_probabilities([1] * 20, number_count=37)
