from __future__ import annotations

import json

from api.patterns.engine import PatternDefinition, PatternEngine


def _definition() -> PatternDefinition:
    return PatternDefinition(
        id="maquina_mortifera_sector_memory",
        name="Maquina Mortifera - Memoria Setorial",
        version="1.0.0",
        kind="positive",
        active=True,
        priority=78,
        weight=2.85,
        evaluator="maquina_mortifera_sector_memory",
        max_numbers=13,
        params={
            "min_history": 60,
            "history_window": 200,
            "required_occurrences": 4,
            "context_window": 4,
            "min_gap_between_occurrences": 4,
            "min_context_matches": 3,
            "interval_window": 30,
            "interval_tolerance": 2.0,
            "include_zero": True,
            "region_base_score": 1.0,
            "context_bonus_per_match": 0.18,
            "sync_bonus": 0.35,
            "zero_score_ratio": 0.82,
        },
    )


def _valid_history() -> list[int]:
    return [
        9, 4, 22, 21, 18, 17, 14, 25, 7, 20,
        9, 4, 22, 21, 18, 32, 29, 15, 12, 1,
        9, 4, 22, 21, 18, 34, 28, 13, 35, 24,
        9, 4, 22, 21, 18, 6, 31, 19, 26, 2,
        11, 14, 21, 18, 25, 7, 17, 12, 34, 28,
        15, 22, 27, 31, 13, 18, 6, 35, 21, 7,
    ]


def test_identifies_target_region_from_repeated_sector_context() -> None:
    engine = PatternEngine()
    definition = _definition()

    result = engine._eval_maquina_mortifera_sector_memory(_valid_history(), [], 0, definition, None)

    assert set(result["numbers"]) == {0, 1, 5, 8, 10, 11, 16, 20, 23, 24, 30, 33, 36}
    assert result["meta"]["target_region"] == 2
    assert result["meta"]["best_match_score"] == 4
    assert result["meta"]["current_delay"] == 9
    assert "memoria setorial da maquina mortifera" in result["explanation"].lower()


def test_stays_inactive_without_enough_occurrences() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = [9, 4, 22, 21, 18] + ([17, 14, 25, 7, 20, 8, 4, 22, 21, 18] * 6)
    result = engine._eval_maquina_mortifera_sector_memory(history, [], 0, definition, None)

    assert result["numbers"] == []
    assert "ocorrencias" in result["explanation"].lower()


def test_pattern_is_registered_and_contributes_in_engine_ensemble(tmp_path) -> None:
    definition = {
        "id": "maquina_mortifera_sector_memory",
        "name": "Maquina Mortifera - Memoria Setorial",
        "kind": "positive",
        "version": "1.0.0",
        "active": True,
        "priority": 78,
        "weight": 2.85,
        "evaluator": "maquina_mortifera_sector_memory",
        "max_numbers": 13,
        "params": {
            "min_history": 60,
            "history_window": 200,
            "required_occurrences": 4,
            "context_window": 4,
            "min_gap_between_occurrences": 4,
            "min_context_matches": 3,
            "interval_window": 30,
            "interval_tolerance": 2.0,
            "include_zero": True,
            "region_base_score": 1.0,
            "context_bonus_per_match": 0.18,
            "sync_bonus": 0.35,
            "zero_score_ratio": 0.82,
        },
    }
    (tmp_path / "maquina_mortifera_sector_memory.json").write_text(
        json.dumps(definition),
        encoding="utf-8",
    )

    engine = PatternEngine(patterns_dir=tmp_path)
    result = engine.evaluate(_valid_history(), use_adaptive_weights=False, use_fallback=False)

    assert any(
        contribution["pattern_id"] == "maquina_mortifera_sector_memory"
        for contribution in result["contributions"]
    )
    contribution = next(
        contribution
        for contribution in result["contributions"]
        if contribution["pattern_id"] == "maquina_mortifera_sector_memory"
    )
    assert {0, 1, 5, 8, 10, 11, 16, 20, 23, 24, 30, 33, 36}.issubset(set(contribution["numbers"]))
