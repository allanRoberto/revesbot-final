from __future__ import annotations

from api.patterns.engine import PatternDefinition, PatternEngine


def _definition() -> PatternDefinition:
    return PatternDefinition(
        id="terminal_group_rotation_369_147_258",
        name="Terminal Group Rotation 369/147/258",
        version="1.0.0",
        kind="positive",
        active=True,
        priority=84,
        weight=3.8,
        evaluator="terminal_group_rotation_369_147_258",
        max_numbers=11,
        params={},
    )


def test_helpers_number_to_group_and_group_to_numbers() -> None:
    engine = PatternEngine()

    assert engine._terminal_group_rotation_group_for_number(36) == "A"
    assert engine._terminal_group_rotation_group_for_number(14) == "B"
    assert engine._terminal_group_rotation_group_for_number(15) == "C"
    assert engine._terminal_group_rotation_group_for_number(0) is None
    assert engine._terminal_group_rotation_group_for_number(30) is None

    assert engine._terminal_group_rotation_numbers_for_group("A") == [3, 6, 9, 13, 16, 19, 23, 26, 29, 33, 36]
    assert engine._terminal_group_rotation_numbers_for_group("B") == [1, 4, 7, 11, 14, 17, 21, 24, 27, 31, 34]
    assert engine._terminal_group_rotation_numbers_for_group("C") == [2, 5, 8, 12, 15, 18, 22, 25, 28, 32, 35]


def test_case_1_pattern_forms_and_bets_group_c() -> None:
    engine = PatternEngine()
    definition = _definition()

    # history[0] mais recente, history[2] mais antigo da janela.
    history = [14, 36, 15, 7, 9]
    result = engine._eval_terminal_group_rotation_369_147_258(history, [], 0, definition, None)

    assert result["numbers"] == [2, 5, 8, 12, 15, 18, 22, 25, 28, 32, 35]
    assert result["meta"]["window_numbers"] == [14, 36, 15]
    assert result["meta"]["window_groups"] == ["B", "A", "C"]
    assert result["meta"]["start_number"] == 15
    assert result["meta"]["target_group"] == "C"


def test_case_2_pattern_does_not_form_same_group_repeats() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = [14, 24, 15, 7, 9]  # B, B, C -> não forma
    result = engine._eval_terminal_group_rotation_369_147_258(history, [], 0, definition, None)

    assert result["numbers"] == []


def test_case_3_pattern_does_not_form_when_zero_exists() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = [0, 36, 15, 7, 9]
    result = engine._eval_terminal_group_rotation_369_147_258(history, [], 0, definition, None)

    assert result["numbers"] == []


def test_temporal_orientation_hist0_recent_hist2_pattern_start() -> None:
    engine = PatternEngine()
    definition = _definition()

    history = [14, 36, 15, 1, 2]
    result = engine._eval_terminal_group_rotation_369_147_258(history, [], 0, definition, None)

    # Confirma orientação: history[0] é recente e history[2] é o início do padrão.
    assert result["meta"]["window_numbers"][0] == history[0]
    assert result["meta"]["window_numbers"][2] == history[2]
    assert result["meta"]["start_number"] == history[2]
    # Se usasse o mais recente como origem, apostaria grupo B; o esperado é grupo C.
    assert result["meta"]["target_group"] == "C"
    assert 15 in result["numbers"] and 14 not in result["numbers"]

