from __future__ import annotations

import json

from api.patterns.engine import PatternDefinition, PatternEngine


SAFE_FILLER = [1, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 18, 20, 22, 23, 24, 26]


def _definition() -> PatternDefinition:
    return PatternDefinition(
        id="neighbor_repeat_delayed_entry",
        name="Neighbor Repeat Delayed Entry",
        version="1.0.0",
        kind="positive",
        active=True,
        priority=101,
        weight=4.0,
        evaluator="neighbor_repeat_delayed_entry",
        max_numbers=7,
        params={
            "attempts_per_count": 5,
            "cancel_lookback": 4,
            "pair_score": 1.0,
            "near_neighbor_score": 0.9,
            "far_neighbor_score": 0.75,
            "zero_score": 0.7,
        },
    )


def _history_from_timeline(timeline: list[int]) -> list[int]:
    return list(reversed(timeline))


def test_forms_with_21_and_4_and_builds_expected_bet_cluster() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline([21, 4, *SAFE_FILLER])
    result = engine._eval_neighbor_repeat_delayed_entry(history, [], 0, definition, None)

    assert result["numbers"] == [25, 2, 21, 4, 19, 15, 0]
    signal = result["meta"]["active_signals"][0]
    assert signal["pair"] == [21, 4]
    assert signal["base_count"] == 21
    assert signal["window_start"] == 21
    assert signal["window_end"] == 25
    assert signal["attempt"] == 1


def test_does_not_form_when_pair_is_not_immediate_neighbors_on_race() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline([21, 5, *SAFE_FILLER])
    result = engine._eval_neighbor_repeat_delayed_entry(history, [], 0, definition, None)

    assert result["numbers"] == []
    assert result["pending_items"] == []
    assert "nenhuma dupla colada" in result["explanation"].lower()


def test_cancel_rule_blocks_entry_when_target_appeared_in_last_four_spins() -> None:
    engine = PatternEngine()
    definition = _definition()

    filler = SAFE_FILLER[:16] + [1, 3, 2, 6]
    history = _history_from_timeline([21, 4, *filler])
    result = engine._eval_neighbor_repeat_delayed_entry(history, [], 0, definition, None)

    assert result["numbers"] == []
    assert "anulada" in result["explanation"].lower()
    assert result["meta"]["cancelled_signals"][0]["pair"] == [21, 4]


def test_temporal_orientation_respects_history_zero_as_most_recent() -> None:
    engine = PatternEngine()
    definition = _definition()

    # Em tempo real: 21,4 formou a dupla e apenas um spin (7) veio depois.
    history = [7, 4, 21, 13, 18]
    result = engine._eval_neighbor_repeat_delayed_entry(history, [], 0, definition, None)

    assert result["numbers"] == []
    assert result["pending_items"][0]["pair"] == [21, 4]
    assert result["pending_items"][0]["spins_since_trigger"] == 1
    assert result["pending_items"][0]["remaining"] == 19


def test_bet_composition_keeps_pair_plus_two_neighbors_each_side_and_zero() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline([4, 21, *SAFE_FILLER])
    result = engine._eval_neighbor_repeat_delayed_entry(history, [], 0, definition, None)

    assert result["numbers"] == [15, 19, 4, 21, 2, 25, 0]
    signal = result["meta"]["active_signals"][0]
    assert signal["pair"] == [4, 21]


def test_pattern_is_registered_and_contributes_in_engine_ensemble(tmp_path) -> None:
    definition = {
        "id": "neighbor_repeat_delayed_entry",
        "name": "Neighbor Repeat Delayed Entry",
        "kind": "positive",
        "version": "1.0.0",
        "active": True,
        "priority": 101,
        "weight": 4.0,
        "evaluator": "neighbor_repeat_delayed_entry",
        "max_numbers": 7,
        "params": {
            "attempts_per_count": 5,
            "cancel_lookback": 4,
            "pair_score": 1.0,
            "near_neighbor_score": 0.9,
            "far_neighbor_score": 0.75,
            "zero_score": 0.7,
        },
    }
    (tmp_path / "neighbor_repeat_delayed_entry.json").write_text(json.dumps(definition), encoding="utf-8")

    engine = PatternEngine(patterns_dir=tmp_path)
    history = _history_from_timeline([21, 4, *SAFE_FILLER])
    result = engine.evaluate(history, use_adaptive_weights=False, use_fallback=False)

    assert result["available"] is False
    assert result["filter_reason"] == "Padroes insuficientes: 1/3"
    assert any(
        contribution["pattern_id"].startswith("neighbor_repeat_delayed_entry")
        for contribution in result["contributions"]
    )
    assert set(result["contributions"][0]["numbers"]) == {0, 2, 4, 15, 19, 21, 25}
