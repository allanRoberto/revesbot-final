from __future__ import annotations

import json
import pytest

from api.patterns.engine import PatternEngine


SAFE_NUMBERS = [1, 2, 3, 4, 6, 7, 8, 9, 11, 12, 13, 14, 15, 17, 18, 19, 20, 21, 22, 23, 25, 26, 27, 28]


def _timeline_with_repeat(number: int, filler: list[int]) -> list[int]:
    return [number, number, *filler]


def _history_from_timeline(timeline: list[int]) -> list[int]:
    return list(reversed(timeline))


def test_weight_profile_multiplies_pattern_weight_in_engine_result(tmp_path) -> None:
    definition = {
        "id": "exact_repeat_delayed_entry",
        "name": "Exact Repeat Delayed Entry",
        "kind": "positive",
        "version": "1.0.0",
        "active": True,
        "priority": 102,
        "weight": 4.2,
        "evaluator": "exact_repeat_delayed_entry",
        "max_numbers": 16,
        "params": {
            "attempts_per_count": 3,
            "cancel_lookback": 4,
            "base_score": 1.0,
            "near_neighbor_score": 0.9,
            "far_neighbor_score": 0.75,
            "zero_score": 0.7,
        },
    }
    (tmp_path / "exact_repeat_delayed_entry.json").write_text(json.dumps(definition), encoding="utf-8")

    engine = PatternEngine(patterns_dir=tmp_path)
    history = _history_from_timeline(_timeline_with_repeat(24, SAFE_NUMBERS[:23]))

    baseline = engine.evaluate(history, use_adaptive_weights=False, use_fallback=False)
    weighted = engine.evaluate(
        history,
        use_adaptive_weights=False,
        use_fallback=False,
        weight_profile_id="treino-a",
        weight_profile_weights={"exact_repeat_delayed_entry": 1.5},
    )

    assert baseline["contributions"][0]["weight"] == 4.2
    assert weighted["contributions"][0]["weight"] == pytest.approx(6.3)
    assert weighted["contributions"][0]["base_weight"] == pytest.approx(6.3)
