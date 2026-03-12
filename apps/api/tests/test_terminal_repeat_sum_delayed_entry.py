from __future__ import annotations

import json

from api.patterns.engine import PatternDefinition, PatternEngine


SAFE_FILLER = [1, 2, 3, 4, 6, 9, 12, 13, 14, 15, 16, 17, 19, 20, 21, 22, 24, 25, 26, 27]


def _definition() -> PatternDefinition:
    return PatternDefinition(
        id="terminal_repeat_sum_delayed_entry",
        name="Terminal Repeat Sum Delayed Entry",
        version="1.0.0",
        kind="positive",
        active=True,
        priority=100,
        weight=4.1,
        evaluator="terminal_repeat_sum_delayed_entry",
        max_numbers=10,
        params={
            "wait_spins": 4,
            "attempts_per_count": 5,
            "cancel_lookback": 4,
            "target_score": 1.0,
            "near_neighbor_score": 0.9,
            "far_neighbor_score": 0.75,
            "terminal_score": 0.8,
            "zero_score": 0.7,
        },
    )


def _history_from_timeline(timeline: list[int]) -> list[int]:
    return list(reversed(timeline))


def test_forms_with_17_and_7_using_oldest_number_sum() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline([17, 7, 1, 2, 3, 4])
    result = engine._eval_terminal_repeat_sum_delayed_entry(history, [], 0, definition, None)

    assert set(result["numbers"]) == {0, 8, 10, 11, 18, 23, 28, 30}
    signal = result["meta"]["active_signals"][0]
    assert signal["pair"] == [17, 7]
    assert signal["sum_target"] == 8
    assert signal["window_start"] == 5
    assert signal["window_end"] == 9
    assert signal["attempt"] == 1


def test_invalid_when_repeat_is_exact_same_number() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline([17, 17, *SAFE_FILLER[:6]])
    result = engine._eval_terminal_repeat_sum_delayed_entry(history, [], 0, definition, None)

    assert result["numbers"] == []
    assert "nenhuma repeticao de terminal" in result["explanation"].lower()


def test_invalid_when_terminals_are_different() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline([17, 8, *SAFE_FILLER[:6]])
    result = engine._eval_terminal_repeat_sum_delayed_entry(history, [], 0, definition, None)

    assert result["numbers"] == []
    assert "nenhuma repeticao de terminal" in result["explanation"].lower()


def test_cancel_rule_blocks_signal_when_target_hits_during_wait() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline([17, 7, 1, 23, 3, 4])
    result = engine._eval_terminal_repeat_sum_delayed_entry(history, [], 0, definition, None)

    assert result["numbers"] == []
    assert "anulada" in result["explanation"].lower()
    assert result["meta"]["cancelled_signals"][0]["pair"] == [17, 7]


def test_temporal_orientation_respects_history_zero_as_most_recent() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = [4, 7, 17, 13, 18]
    result = engine._eval_terminal_repeat_sum_delayed_entry(history, [], 0, definition, None)

    assert result["numbers"] == []
    assert result["pending_items"][0]["pair"] == [17, 7]
    assert result["pending_items"][0]["spins_since_trigger"] == 1
    assert result["pending_items"][0]["remaining"] == 3


def test_bet_composition_has_sum_neighbors_terminal_matches_zero_without_duplicates() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline([17, 7, 1, 2, 3, 4])
    result = engine._eval_terminal_repeat_sum_delayed_entry(history, [], 0, definition, None)

    numbers = result["numbers"]
    assert len(numbers) == len(set(numbers))
    assert {8, 18, 28, 0}.issubset(set(numbers))
    assert {11, 30, 23, 10}.issubset(set(numbers))


def test_pattern_is_registered_and_contributes_in_engine_ensemble(tmp_path) -> None:
    definition = {
        "id": "terminal_repeat_sum_delayed_entry",
        "name": "Terminal Repeat Sum Delayed Entry",
        "kind": "positive",
        "version": "1.0.0",
        "active": True,
        "priority": 100,
        "weight": 4.1,
        "evaluator": "terminal_repeat_sum_delayed_entry",
        "max_numbers": 10,
        "params": {
            "wait_spins": 4,
            "attempts_per_count": 5,
            "cancel_lookback": 4,
            "target_score": 1.0,
            "near_neighbor_score": 0.9,
            "far_neighbor_score": 0.75,
            "terminal_score": 0.8,
            "zero_score": 0.7,
        },
    }
    (tmp_path / "terminal_repeat_sum_delayed_entry.json").write_text(json.dumps(definition), encoding="utf-8")

    engine = PatternEngine(patterns_dir=tmp_path)
    history = _history_from_timeline([17, 7, 1, 2, 3, 4])
    result = engine.evaluate(history, use_adaptive_weights=False, use_fallback=False)

    assert result["available"] is False
    assert result["filter_reason"] == "Padroes insuficientes: 1/3"
    assert any(
        contribution["pattern_id"].startswith("terminal_repeat_sum_delayed_entry")
        for contribution in result["contributions"]
    )
    assert {0, 8, 10, 11, 18, 23, 28, 30}.issubset(set(result["contributions"][0]["numbers"]))
