from __future__ import annotations

import json

from api.patterns.engine import PatternDefinition, PatternEngine


SAFE_FILLER = [1, 2, 3, 4]
SAFE_FILLER_WITH_MIRROR = [2, 3, 4, 6]


def _definition() -> PatternDefinition:
    return PatternDefinition(
        id="trend_alternation_middle_projection_entry",
        name="Trend Alternation Middle Projection Entry",
        version="1.0.0",
        kind="positive",
        active=True,
        priority=95,
        weight=4.0,
        evaluator="trend_alternation_middle_projection_entry",
        max_numbers=16,
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


def test_forms_with_14_7_15() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline([14, 7, 15, *SAFE_FILLER])
    result = engine._eval_trend_alternation_middle_projection_entry(history, [], 0, definition, None)

    assert result["numbers"] == [34, 6, 27, 30, 8, 23, 0]
    signal = result["meta"]["active_signals"][0]
    assert signal["formation"] == [14, 7, 15]
    assert signal["middle_bases"] == [7]
    assert signal["window_start"] == 5
    assert signal["window_end"] == 9
    assert signal["attempt"] == 1


def test_does_not_form_when_sequence_is_not_trend_alternation() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline([14, 7, 5])
    result = engine._eval_trend_alternation_middle_projection_entry(history, [], 0, definition, None)

    assert result["numbers"] == []
    assert "nenhuma alternancia de tendencia" in result["explanation"].lower()


def test_cancel_rule_blocks_when_target_hits_during_wait() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline([14, 7, 15, 1, 8, 3, 4])
    result = engine._eval_trend_alternation_middle_projection_entry(history, [], 0, definition, None)

    assert result["numbers"] == []
    assert "anulada" in result["explanation"].lower()
    assert result["meta"]["cancelled_signals"][0]["formation"] == [14, 7, 15]


def test_temporal_orientation_respects_history_zero_as_most_recent() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = [4, 15, 7, 14]
    result = engine._eval_trend_alternation_middle_projection_entry(history, [], 0, definition, None)

    assert result["numbers"] == []
    assert result["pending_items"][0]["formation"] == [14, 7, 15]
    assert result["pending_items"][0]["middle_bases"] == [7]
    assert result["pending_items"][0]["spins_since_trigger"] == 1
    assert result["pending_items"][0]["remaining"] == 3


def test_bet_composition_has_targets_neighbors_and_zero_without_duplicates() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline([14, 7, 15, *SAFE_FILLER])
    result = engine._eval_trend_alternation_middle_projection_entry(history, [], 0, definition, None)

    numbers = result["numbers"]
    assert numbers == [34, 6, 27, 30, 8, 23, 0]
    assert len(numbers) == len(set(numbers))


def test_mirror_or_twin_case_expands_projections_from_middle_number() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline([20, 16, 19, *SAFE_FILLER_WITH_MIRROR])
    result = engine._eval_trend_alternation_middle_projection_entry(history, [], 0, definition, None)

    signal = result["meta"]["active_signals"][0]
    assert signal["formation"] == [20, 16, 19]
    assert signal["middle_bases"] == [16, 19]
    assert {0, 32, 15, 19, 25, 17, 34, 22, 18, 29, 1, 20, 14}.issubset(set(result["numbers"]))
    assert len(result["numbers"]) == len(set(result["numbers"]))


def test_pattern_is_registered_and_contributes_in_engine_ensemble(tmp_path) -> None:
    definition = {
        "id": "trend_alternation_middle_projection_entry",
        "name": "Trend Alternation Middle Projection Entry",
        "kind": "positive",
        "version": "1.0.0",
        "active": True,
        "priority": 95,
        "weight": 4.0,
        "evaluator": "trend_alternation_middle_projection_entry",
        "max_numbers": 16,
        "params": {
            "wait_spins": 4,
            "attempts_per_count": 5,
            "target_score": 1.0,
            "neighbor_score": 0.85,
            "zero_score": 0.7,
        },
    }
    (tmp_path / "trend_alternation_middle_projection_entry.json").write_text(json.dumps(definition), encoding="utf-8")

    engine = PatternEngine(patterns_dir=tmp_path)
    history = _history_from_timeline([14, 7, 15, *SAFE_FILLER])
    result = engine.evaluate(history, use_adaptive_weights=False, use_fallback=False)

    assert result["available"] is False
    assert result["filter_reason"] == "Padroes insuficientes: 1/3"
    assert any(
        contribution["pattern_id"].startswith("trend_alternation_middle_projection_entry")
        for contribution in result["contributions"]
    )
    assert set(result["contributions"][0]["numbers"]) == {0, 6, 8, 23, 27, 30, 34}
