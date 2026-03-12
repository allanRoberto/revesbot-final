from __future__ import annotations

import json

from api.patterns.engine import PatternDefinition, PatternEngine


SAFE_FILLER = [1, 2, 3, 4]
SAFE_FILLER_16 = [2, 3, 6, 7]


def _definition() -> PatternDefinition:
    return PatternDefinition(
        id="color_neighbor_alternation_missing_entry",
        name="Color Neighbor Alternation Missing Entry",
        version="1.0.0",
        kind="positive",
        active=True,
        priority=97,
        weight=3.8,
        evaluator="color_neighbor_alternation_missing_entry",
        max_numbers=16,
        params={
            "wait_spins": 4,
            "attempts_per_count": 6,
            "base_score": 1.0,
            "near_neighbor_score": 0.9,
            "far_neighbor_score": 0.75,
            "zero_score": 0.7,
        },
    )


def _history_from_timeline(timeline: list[int]) -> list[int]:
    return list(reversed(timeline))


def test_forms_with_5_and_16_and_finds_24_as_missing() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline([5, 16, *SAFE_FILLER])
    result = engine._eval_color_neighbor_alternation_missing_entry(history, [], 0, definition, None)

    assert result["numbers"] == [10, 5, 24, 16, 33, 0]
    signal = result["meta"]["active_signals"][0]
    assert signal["pair"] == [5, 16]
    assert signal["missing_target"] == 24
    assert signal["target_bases"] == [24]
    assert signal["window_start"] == 5
    assert signal["window_end"] == 10
    assert signal["attempt"] == 1


def test_does_not_form_when_pair_is_not_color_neighbors_with_single_gap() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline([5, 14])
    result = engine._eval_color_neighbor_alternation_missing_entry(history, [], 0, definition, None)

    assert result["numbers"] == []
    assert "nenhum faltante de vizinhos de cor" in result["explanation"].lower()


def test_cancel_rule_blocks_when_target_hits_during_wait() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline([5, 16, 1, 24, 3, 4])
    result = engine._eval_color_neighbor_alternation_missing_entry(history, [], 0, definition, None)

    assert result["numbers"] == []
    assert "anulada" in result["explanation"].lower()
    assert result["meta"]["cancelled_signals"][0]["pair"] == [5, 16]


def test_temporal_orientation_respects_history_zero_as_most_recent() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = [7, 16, 5]
    result = engine._eval_color_neighbor_alternation_missing_entry(history, [], 0, definition, None)

    assert result["numbers"] == []
    assert result["pending_items"][0]["pair"] == [5, 16]
    assert result["pending_items"][0]["missing_target"] == 24
    assert result["pending_items"][0]["spins_since_trigger"] == 1
    assert result["pending_items"][0]["remaining"] == 3


def test_bet_composition_has_missing_plus_two_neighbors_each_side_and_zero_without_duplicates() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline([5, 16, *SAFE_FILLER])
    result = engine._eval_color_neighbor_alternation_missing_entry(history, [], 0, definition, None)

    numbers = result["numbers"]
    assert numbers == [10, 5, 24, 16, 33, 0]
    assert len(numbers) == len(set(numbers))


def test_mirror_or_twin_case_expands_targets_without_duplicates() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline([24, 33, *SAFE_FILLER_16])
    result = engine._eval_color_neighbor_alternation_missing_entry(history, [], 0, definition, None)

    signal = result["meta"]["active_signals"][0]
    assert signal["pair"] == [24, 33]
    assert signal["missing_target"] == 16
    assert signal["target_bases"] == [16, 19]
    assert {0, 5, 24, 16, 33, 1, 32, 15, 19, 4, 21}.issubset(set(result["numbers"]))
    assert len(result["numbers"]) == len(set(result["numbers"]))


def test_pattern_is_registered_and_contributes_in_engine_ensemble(tmp_path) -> None:
    definition = {
        "id": "color_neighbor_alternation_missing_entry",
        "name": "Color Neighbor Alternation Missing Entry",
        "kind": "positive",
        "version": "1.0.0",
        "active": True,
        "priority": 97,
        "weight": 3.8,
        "evaluator": "color_neighbor_alternation_missing_entry",
        "max_numbers": 16,
        "params": {
            "wait_spins": 4,
            "attempts_per_count": 6,
            "base_score": 1.0,
            "near_neighbor_score": 0.9,
            "far_neighbor_score": 0.75,
            "zero_score": 0.7,
        },
    }
    (tmp_path / "color_neighbor_alternation_missing_entry.json").write_text(json.dumps(definition), encoding="utf-8")

    engine = PatternEngine(patterns_dir=tmp_path)
    history = _history_from_timeline([5, 16, *SAFE_FILLER])
    result = engine.evaluate(history, use_adaptive_weights=False, use_fallback=False)

    assert result["available"] is False
    assert result["filter_reason"] == "Padroes insuficientes: 1/3"
    assert any(
        contribution["pattern_id"].startswith("color_neighbor_alternation_missing_entry")
        for contribution in result["contributions"]
    )
    assert set(result["contributions"][0]["numbers"]) == {0, 5, 10, 16, 24, 33}
