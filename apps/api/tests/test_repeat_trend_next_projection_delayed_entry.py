from __future__ import annotations

import json

from api.patterns.engine import PatternDefinition, PatternEngine


SAFE_FILLER = [1, 2, 3, 4, 5, 9, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]


def _definition() -> PatternDefinition:
    return PatternDefinition(
        id="repeat_trend_next_projection_delayed_entry",
        name="Repeat Trend Next Projection Delayed Entry",
        version="1.0.0",
        kind="positive",
        active=True,
        priority=99,
        weight=3.9,
        evaluator="repeat_trend_next_projection_delayed_entry",
        max_numbers=7,
        params={
            "wait_spins": 4,
            "attempts_per_count": 5,
            "target_score": 1.0,
            "neighbor_score": 0.85,
            "zero_score": 0.7,
        },
    )


def _history_from_timeline(timeline: list[int]) -> list[int]:
    return list(reversed(timeline))


def test_forms_with_example_14_15_7() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline([14, 15, 7, 1, 2, 3, 4])
    result = engine._eval_repeat_trend_next_projection_delayed_entry(history, [], 0, definition, None)

    assert set(result["numbers"]) == {0, 6, 8, 23, 27, 30, 34}
    signal = result["meta"]["active_signals"][0]
    assert signal["trend_pair"] == [14, 15]
    assert signal["base_number"] == 7
    assert signal["direction"] == "up"
    assert signal["window_start"] == 5
    assert signal["window_end"] == 9
    assert signal["attempt"] == 1


def test_valid_increasing_repetition_projects_next_number() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline([3, 4, 20, 1, 5, 6, 7])
    result = engine._eval_repeat_trend_next_projection_delayed_entry(history, [], 0, definition, None)

    signal = result["meta"]["active_signals"][0]
    assert signal["trend_pair"] == [3, 4]
    assert signal["base_number"] == 20
    assert signal["direction"] == "up"


def test_valid_decreasing_repetition_projects_next_number() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline([15, 14, 7, 1, 2, 3, 4])
    result = engine._eval_repeat_trend_next_projection_delayed_entry(history, [], 0, definition, None)

    signal = result["meta"]["active_signals"][0]
    assert signal["trend_pair"] == [15, 14]
    assert signal["base_number"] == 7
    assert signal["direction"] == "down"


def test_does_not_form_when_pair_is_not_consecutive_trend() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline([14, 16, 7])
    result = engine._eval_repeat_trend_next_projection_delayed_entry(history, [], 0, definition, None)

    assert result["numbers"] == []
    assert "nenhuma projecao de tendencia" in result["explanation"].lower()


def test_cancel_rule_blocks_when_target_hits_during_wait() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline([14, 15, 7, 1, 8, 3, 4])
    result = engine._eval_repeat_trend_next_projection_delayed_entry(history, [], 0, definition, None)

    assert result["numbers"] == []
    assert "anulada" in result["explanation"].lower()
    assert result["meta"]["cancelled_signals"][0]["trend_pair"] == [14, 15]


def test_temporal_orientation_uses_base_after_trend_as_wait_origin() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = [4, 7, 15, 14, 22]
    result = engine._eval_repeat_trend_next_projection_delayed_entry(history, [], 0, definition, None)

    assert result["numbers"] == []
    assert result["pending_items"][0]["trend_pair"] == [14, 15]
    assert result["pending_items"][0]["base_number"] == 7
    assert result["pending_items"][0]["spins_since_base"] == 1
    assert result["pending_items"][0]["remaining"] == 3


def test_bet_composition_has_targets_neighbors_zero_without_duplicates() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline([14, 15, 7, 1, 2, 3, 4])
    result = engine._eval_repeat_trend_next_projection_delayed_entry(history, [], 0, definition, None)

    numbers = result["numbers"]
    assert len(numbers) == len(set(numbers))
    assert {6, 8, 0}.issubset(set(numbers))
    assert {34, 27, 30, 23}.issubset(set(numbers))


def test_pattern_is_registered_and_contributes_in_engine_ensemble(tmp_path) -> None:
    definition = {
        "id": "repeat_trend_next_projection_delayed_entry",
        "name": "Repeat Trend Next Projection Delayed Entry",
        "kind": "positive",
        "version": "1.0.0",
        "active": True,
        "priority": 99,
        "weight": 3.9,
        "evaluator": "repeat_trend_next_projection_delayed_entry",
        "max_numbers": 7,
        "params": {
            "wait_spins": 4,
            "attempts_per_count": 5,
            "target_score": 1.0,
            "neighbor_score": 0.85,
            "zero_score": 0.7,
        },
    }
    (tmp_path / "repeat_trend_next_projection_delayed_entry.json").write_text(json.dumps(definition), encoding="utf-8")

    engine = PatternEngine(patterns_dir=tmp_path)
    history = _history_from_timeline([14, 15, 7, 1, 2, 3, 4])
    result = engine.evaluate(history, use_adaptive_weights=False, use_fallback=False)

    assert result["available"] is False
    assert result["filter_reason"] == "Padroes insuficientes: 1/3"
    assert any(
        contribution["pattern_id"].startswith("repeat_trend_next_projection_delayed_entry")
        for contribution in result["contributions"]
    )
    assert {0, 6, 8, 23, 27, 30, 34}.issubset(set(result["contributions"][0]["numbers"]))
