from __future__ import annotations

import json

from api.patterns.engine import PatternDefinition, PatternEngine


SAFE_FILLER = [1, 2, 3, 4]


def _definition() -> PatternDefinition:
    return PatternDefinition(
        id="terminal_alternation_middle_entry",
        name="Terminal Alternation Middle Entry",
        version="1.0.0",
        kind="positive",
        active=True,
        priority=96,
        weight=3.9,
        evaluator="terminal_alternation_middle_entry",
        max_numbers=8,
        params={
            "wait_spins": 4,
            "attempts_per_count": 4,
            "neighbor_span": 3,
            "target_score": 1.0,
            "near_neighbor_score": 0.9,
            "mid_neighbor_score": 0.8,
            "far_neighbor_score": 0.7,
            "zero_score": 0.7,
        },
    )


def _history_from_timeline(timeline: list[int]) -> list[int]:
    return list(reversed(timeline))


def test_forms_with_27_5_17() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline([27, 5, 17, *SAFE_FILLER])
    result = engine._eval_terminal_alternation_middle_entry(history, [], 0, definition, None)

    assert result["numbers"] == [8, 23, 10, 5, 24, 16, 33, 0]
    signal = result["meta"]["active_signals"][0]
    assert signal["formation"] == [27, 5, 17]
    assert signal["target_number"] == 5
    assert signal["window_start"] == 5
    assert signal["window_end"] == 8
    assert signal["attempt"] == 1


def test_does_not_form_when_outer_numbers_do_not_share_terminal() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline([27, 5, 18])
    result = engine._eval_terminal_alternation_middle_entry(history, [], 0, definition, None)

    assert result["numbers"] == []
    assert "nenhuma alternancia de terminais" in result["explanation"].lower()


def test_cancel_rule_blocks_when_target_hits_during_wait() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline([27, 5, 17, 1, 24, 3, 4])
    result = engine._eval_terminal_alternation_middle_entry(history, [], 0, definition, None)

    assert result["numbers"] == []
    assert "anulada" in result["explanation"].lower()
    assert result["meta"]["cancelled_signals"][0]["formation"] == [27, 5, 17]


def test_temporal_orientation_respects_history_zero_as_most_recent() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = [7, 17, 5, 27]
    result = engine._eval_terminal_alternation_middle_entry(history, [], 0, definition, None)

    assert result["numbers"] == []
    assert result["pending_items"][0]["formation"] == [27, 5, 17]
    assert result["pending_items"][0]["target_number"] == 5
    assert result["pending_items"][0]["spins_since_trigger"] == 1
    assert result["pending_items"][0]["remaining"] == 3


def test_bet_composition_has_target_neighbors_and_zero_without_duplicates() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = _history_from_timeline([27, 5, 17, *SAFE_FILLER])
    result = engine._eval_terminal_alternation_middle_entry(history, [], 0, definition, None)

    numbers = result["numbers"]
    assert numbers == [8, 23, 10, 5, 24, 16, 33, 0]
    assert len(numbers) == len(set(numbers))


def test_pattern_is_registered_and_contributes_in_engine_ensemble(tmp_path) -> None:
    definition = {
        "id": "terminal_alternation_middle_entry",
        "name": "Terminal Alternation Middle Entry",
        "kind": "positive",
        "version": "1.0.0",
        "active": True,
        "priority": 96,
        "weight": 3.9,
        "evaluator": "terminal_alternation_middle_entry",
        "max_numbers": 8,
        "params": {
            "wait_spins": 4,
            "attempts_per_count": 4,
            "neighbor_span": 3,
            "target_score": 1.0,
            "near_neighbor_score": 0.9,
            "mid_neighbor_score": 0.8,
            "far_neighbor_score": 0.7,
            "zero_score": 0.7,
        },
    }
    (tmp_path / "terminal_alternation_middle_entry.json").write_text(json.dumps(definition), encoding="utf-8")

    engine = PatternEngine(patterns_dir=tmp_path)
    history = _history_from_timeline([27, 5, 17, *SAFE_FILLER])
    result = engine.evaluate(history, use_adaptive_weights=False, use_fallback=False)

    assert result["available"] is False
    assert result["filter_reason"] == "Padroes insuficientes: 1/3"
    assert any(
        contribution["pattern_id"].startswith("terminal_alternation_middle_entry")
        for contribution in result["contributions"]
    )
    assert set(result["contributions"][0]["numbers"]) == {0, 5, 8, 10, 16, 23, 24, 33}
