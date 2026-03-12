from __future__ import annotations

import json

from api.patterns.engine import PatternDefinition, PatternEngine


SAFE_NUMBERS = [1, 2, 3, 4, 6, 7, 8, 9, 11, 12, 13, 14, 15, 17, 18, 19, 20, 21, 22, 23, 25, 26, 27, 28]
SAFE_NUMBERS_16_19 = [2, 3, 6, 7, 8, 9, 10, 11, 12, 13, 14, 17, 18, 20, 22, 23, 25, 26]
SAFE_NUMBERS_11_22_33 = [2, 3, 4, 5, 6, 7, 10, 12, 14, 15, 17, 19, 21, 23, 25, 26, 27, 28, 32, 34, 35]


def _definition() -> PatternDefinition:
    return PatternDefinition(
        id="exact_repeat_delayed_entry",
        name="Exact Repeat Delayed Entry",
        version="1.0.0",
        kind="positive",
        active=True,
        priority=102,
        weight=4.2,
        evaluator="exact_repeat_delayed_entry",
        max_numbers=16,
        params={
            "attempts_per_count": 3,
            "cancel_lookback": 4,
            "base_score": 1.0,
            "near_neighbor_score": 0.9,
            "far_neighbor_score": 0.75,
            "zero_score": 0.7,
        },
    )


def _history_from_timeline(timeline: list[int]) -> list[int]:
    return list(reversed(timeline))


def _timeline_with_repeat(base: int, filler: list[int]) -> list[int]:
    return [base, base, *filler]


def test_simple_repeat_without_mirror_activates_target_cluster() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline(_timeline_with_repeat(24, SAFE_NUMBERS[:23]))
    result = engine._eval_exact_repeat_delayed_entry(history, [], 0, definition, None)

    assert set(result["numbers"]) == {0, 5, 10, 16, 24, 33}
    signal = result["meta"]["active_signals"][0]
    assert signal["trigger_number"] == 24
    assert signal["count_values"] == [24]
    assert signal["next_count"] == 24
    assert signal["attempt"] == 1


def test_repeat_with_mirror_uses_lower_window_first_then_next_window() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline(_timeline_with_repeat(16, SAFE_NUMBERS_16_19))
    result = engine._eval_exact_repeat_delayed_entry(history, [], 0, definition, None)

    assert set(result["numbers"]) == {0, 1, 4, 5, 15, 16, 19, 21, 24, 32, 33}
    signal = result["meta"]["active_signals"][0]
    assert signal["trigger_number"] == 16
    assert signal["count_values"] == [16, 19]
    assert signal["next_count"] == 19
    assert signal["attempt"] == 1


def test_repeat_with_11_22_33_trio_activates_third_window() -> None:
    engine = PatternEngine()
    definition = _definition()

    filler = [SAFE_NUMBERS_11_22_33[i % len(SAFE_NUMBERS_11_22_33)] for i in range(32)]
    history = _history_from_timeline(_timeline_with_repeat(11, filler))
    result = engine._eval_exact_repeat_delayed_entry(history, [], 0, definition, None)

    assert set(result["numbers"]) == {0, 1, 8, 9, 11, 13, 16, 18, 20, 22, 24, 29, 30, 31, 33, 36}
    signal = result["meta"]["active_signals"][0]
    assert signal["trigger_number"] == 11
    assert signal["count_values"] == [11, 22, 33]
    assert signal["next_count"] == 33
    assert signal["attempt"] == 1


def test_cancel_rule_blocks_entry_when_target_hit_in_previous_four_spins() -> None:
    engine = PatternEngine()
    definition = _definition()

    filler = SAFE_NUMBERS[:19] + [1, 2, 3, 5]
    history = _history_from_timeline(_timeline_with_repeat(24, filler))
    result = engine._eval_exact_repeat_delayed_entry(history, [], 0, definition, None)

    assert result["numbers"] == []
    assert "anulada" in result["explanation"].lower()
    assert result["meta"]["cancelled_signals"][0]["trigger_number"] == 24


def test_temporal_orientation_uses_history_zero_as_most_recent() -> None:
    engine = PatternEngine()
    definition = _definition()

    # Em tempo real: 24,24 aconteceu e apenas o 7 veio depois.
    history = [7, 24, 24, 13, 18]
    result = engine._eval_exact_repeat_delayed_entry(history, [], 0, definition, None)

    assert result["numbers"] == []
    assert result["pending_items"][0]["trigger_number"] == 24
    assert result["pending_items"][0]["spins_since_trigger"] == 1
    assert result["pending_items"][0]["remaining"] == 22


def test_pattern_is_loaded_and_contributes_in_engine_ensemble(tmp_path) -> None:
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
    result = engine.evaluate(history, use_adaptive_weights=False, use_fallback=False)

    assert result["available"] is False
    assert result["filter_reason"] == "Padroes insuficientes: 1/3"
    assert any(
        contribution["pattern_id"].startswith("exact_repeat_delayed_entry")
        for contribution in result["contributions"]
    )
    assert set(result["contributions"][0]["numbers"]) == {0, 5, 10, 16, 24, 33}
