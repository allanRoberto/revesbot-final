from __future__ import annotations

import pytest

from api.services.jev_meta_ranking import (
    _relation_samples,
    build_meta_rankings,
)
from api.services.jev_ranking import build_ranking_payload


def _strong_source_history(repetitions: int = 120) -> list[int]:
    return [value for _ in range(repetitions) for value in (17, 0, 1, 2)] + [17]


def test_walk_forward_prediction_does_not_read_its_own_future() -> None:
    training = [value for _ in range(12) for value in (17, 0, 1, 2)]
    misses_zero = training + [17, 4, 5, 6]
    hits_zero = training + [17, 0, 5, 6]

    misses = _relation_samples(
        misses_zero,
        source_number=17,
        horizon=3,
    )[0][0]
    hits = _relation_samples(
        hits_zero,
        source_number=17,
        horizon=3,
    )[0][0]

    assert len(misses) == len(hits) == 1
    assert misses[0][0] == hits[0][0]
    assert misses[0][1] == 0
    assert hits[0][1] == 1


def test_walk_forward_catalog_validates_repeatable_source_pattern() -> None:
    payload = build_ranking_payload(_strong_source_history())
    zero = payload["walk_forward"]["numbers"][0]["horizon_3"]

    assert zero["models"]["relation"]["sample_count"] >= 100
    assert zero["models"]["relation"]["brier_improvement"] > 0
    assert zero["combined"]["status"] == "validated"
    assert zero["combined"]["calibrated_probability"] > zero["fair_baseline"]
    assert payload["state"]["walk_forward_validation"]["method"] == (
        "chronological_source_conditioned_no_future_leakage"
    )


def test_meta_ranking_covers_zero_normalizes_next_spin_and_can_abstain() -> None:
    payload = build_ranking_payload(_strong_source_history())
    quality = {
        number: {"score_normalizado": 0.8, "confidence": 0.8}
        for number in range(37)
    }
    meta = build_meta_rankings(
        walk_forward=payload["walk_forward"],
        jev_three_spin_probabilities={
            number: 0.9 if number == 0 else 0.05 for number in range(37)
        },
        jev_next_spin_probabilities={
            number: 0.2 if number == 0 else 0.8 / 36 for number in range(37)
        },
        pattern_quality_by_target=quality,
        regime="transition_driven",
    )

    assert len(meta["ranking_tres_rodadas"]) == 37
    assert {item["numero"] for item in meta["ranking_tres_rodadas"]} == set(range(37))
    assert meta["ranking_tres_rodadas"][0]["numero"] == 0
    assert sum(
        item["probabilidade_meta"] for item in meta["ranking_proxima_rodada"]
    ) == pytest.approx(1)
    assert meta["signal"]["available"] is True

    unstable = build_meta_rankings(
        walk_forward=payload["walk_forward"],
        jev_three_spin_probabilities={number: 0.08 for number in range(37)},
        jev_next_spin_probabilities={number: 1 / 37 for number in range(37)},
        pattern_quality_by_target=quality,
        regime="unstable",
    )
    assert unstable["signal"]["status"] == "no_reliable_signal"
    assert unstable["signal"]["available"] is False
