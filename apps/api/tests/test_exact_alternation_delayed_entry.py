from __future__ import annotations

import json

from api.patterns.engine import PatternDefinition, PatternEngine


SAFE_FILLER_14 = [2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 13, 15, 16]
SAFE_FILLER_16_19 = [2, 3, 6, 7, 8, 9, 10, 11, 12, 13, 14, 17, 18, 20, 22, 23, 25, 26]


def _definition() -> PatternDefinition:
    return PatternDefinition(
        id="exact_alternation_delayed_entry",
        name="Exact Alternation Delayed Entry",
        version="1.0.0",
        kind="positive",
        active=True,
        priority=98,
        weight=4.0,
        evaluator="exact_alternation_delayed_entry",
        max_numbers=16,
        params={
            "attempts_per_count": 6,
            "cancel_lookback": 4,
            "base_score": 1.0,
            "near_neighbor_score": 0.9,
            "far_neighbor_score": 0.75,
            "zero_score": 0.7,
        },
    )


def _history_from_timeline(timeline: list[int]) -> list[int]:
    return list(reversed(timeline))


def test_forms_with_24_14_24_and_targets_middle_number_cluster() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline([24, 14, 24, *SAFE_FILLER_14])
    result = engine._eval_exact_alternation_delayed_entry(history, [], 0, definition, None)

    assert result["numbers"] == [9, 31, 14, 20, 1, 0]
    signal = result["meta"]["active_signals"][0]
    assert signal["formation"] == [24, 14, 24]
    assert signal["target_bases"] == [14]
    assert signal["count_values"] == [14]
    assert signal["next_count"] == 14
    assert signal["attempt"] == 1


def test_does_not_form_when_sequence_is_not_a_b_a() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline([24, 14, 25])
    result = engine._eval_exact_alternation_delayed_entry(history, [], 0, definition, None)

    assert result["numbers"] == []
    assert "nenhuma alternancia exata" in result["explanation"].lower()


def test_cancel_rule_blocks_when_target_appeared_before_first_entry() -> None:
    engine = PatternEngine()
    definition = _definition()

    filler = [2, 3, 4, 5, 6, 7, 8, 10, 11, 1, 12, 13, 15]
    history = _history_from_timeline([24, 14, 24, *filler])
    result = engine._eval_exact_alternation_delayed_entry(history, [], 0, definition, None)

    assert result["numbers"] == []
    assert "anulada" in result["explanation"].lower()
    assert result["meta"]["cancelled_signals"][0]["formation"] == [24, 14, 24]


def test_temporal_orientation_respects_history_zero_as_most_recent() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = [7, 24, 14, 24]
    result = engine._eval_exact_alternation_delayed_entry(history, [], 0, definition, None)

    assert result["numbers"] == []
    assert result["pending_items"][0]["formation"] == [24, 14, 24]
    assert result["pending_items"][0]["spins_since_trigger"] == 1
    assert result["pending_items"][0]["remaining"] == 12


def test_bet_composition_has_middle_number_neighbors_zero_without_duplicates() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline([24, 14, 24, *SAFE_FILLER_14])
    result = engine._eval_exact_alternation_delayed_entry(history, [], 0, definition, None)

    numbers = result["numbers"]
    assert numbers == [9, 31, 14, 20, 1, 0]
    assert len(numbers) == len(set(numbers))


def test_mirror_or_twin_case_uses_two_count_windows() -> None:
    engine = PatternEngine()
    definition = _definition()

    filler = SAFE_FILLER_16_19 + [2, 3, 6]
    history = _history_from_timeline([24, 16, 24, *filler])
    result = engine._eval_exact_alternation_delayed_entry(history, [], 0, definition, None)

    signal = result["meta"]["active_signals"][0]
    assert signal["formation"] == [24, 16, 24]
    assert signal["target_bases"] == [16, 19]
    assert signal["count_values"] == [16, 19]
    assert signal["next_count"] == 19
    assert signal["attempt"] == 4
    assert {0, 1, 4, 5, 15, 16, 19, 21, 24, 32, 33}.issubset(set(result["numbers"]))


def test_pattern_is_registered_and_contributes_in_engine_ensemble(tmp_path) -> None:
    definition = {
        "id": "exact_alternation_delayed_entry",
        "name": "Exact Alternation Delayed Entry",
        "kind": "positive",
        "version": "1.0.0",
        "active": True,
        "priority": 98,
        "weight": 4.0,
        "evaluator": "exact_alternation_delayed_entry",
        "max_numbers": 16,
        "params": {
            "attempts_per_count": 6,
            "cancel_lookback": 4,
            "base_score": 1.0,
            "near_neighbor_score": 0.9,
            "far_neighbor_score": 0.75,
            "zero_score": 0.7,
        },
    }
    (tmp_path / "exact_alternation_delayed_entry.json").write_text(json.dumps(definition), encoding="utf-8")

    engine = PatternEngine(patterns_dir=tmp_path)
    history = _history_from_timeline([24, 14, 24, *SAFE_FILLER_14])
    result = engine.evaluate(history, use_adaptive_weights=False, use_fallback=False)

    assert result["available"] is False
    assert result["filter_reason"] == "Padroes insuficientes: 1/3"
    assert any(
        contribution["pattern_id"].startswith("exact_alternation_delayed_entry")
        for contribution in result["contributions"]
    )
    assert set(result["contributions"][0]["numbers"]) == {0, 1, 9, 14, 20, 31}
