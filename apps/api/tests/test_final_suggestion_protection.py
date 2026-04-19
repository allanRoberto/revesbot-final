from __future__ import annotations

import api.services.final_suggestion_protection as protection_module
from api.services.final_suggestion_protection import (
    build_protected_coverage_suggestion,
)


def _build_history_with_prefix(prefix: list[int]) -> list[int]:
    history = [int(number) for number in prefix]
    history.extend(list(range(37)))
    return history


def _build_frequency_map_for_cold_order(cold_order: list[int]) -> dict[int, int]:
    frequency_map = {number: len(cold_order) + 10 for number in range(37)}
    for index, number in enumerate(cold_order):
        frequency_map[int(number)] = index
    return frequency_map


def _run_protected(
    monkeypatch,
    *,
    prefix: list[int],
    cold_order: list[int],
    focus_number: int,
    protected_swap_enabled: bool = False,
):
    monkeypatch.setattr(
        protection_module,
        "_build_frequency_map",
        lambda history_slice: _build_frequency_map_for_cold_order(cold_order),
    )
    return build_protected_coverage_suggestion(
        history_arr=_build_history_with_prefix(prefix),
        from_index=0,
        focus_number=focus_number,
        base_list=[23, 13, 31, 32, 8, 10, 27, 36],
        candidate_list=[23, 13, 31, 32, 8, 10, 27, 36, 11, 22],
        protections=[22],
        number_details=[{"number": number, "net_score": float(37 - number)} for number in range(37)],
        target_size=35,
        cold_count=18,
        recent_anchor_count=2,
        protected_swap_enabled=protected_swap_enabled,
    )


def test_protected_coverage_ignores_disabled_mirror_neighbor_relation(monkeypatch) -> None:
    result = _run_protected(
        monkeypatch,
        prefix=[],
        cold_order=[3, 26, 8, 12],
        focus_number=8,
    )

    assert result["protected_excluded_numbers"] == [3, 26]
    assert result["protected_wait_triggered"] is False
    assert result["protected_wait_recommended_spins"] == 0
    assert result["protected_wait_matches"] == []
    assert result["protected_wait_reason"] == ""


def test_protected_coverage_ignores_disabled_sequence_mirror_relation(monkeypatch) -> None:
    result = _run_protected(
        monkeypatch,
        prefix=[30, 17],
        cold_order=[4, 9, 8, 12],
        focus_number=30,
    )

    assert result["protected_excluded_numbers"] == [4, 9]
    assert result["protected_wait_triggered"] is False
    assert result["protected_wait_recommended_spins"] == 0
    assert result["protected_wait_matches"] == []
    assert result["protected_wait_reason"] == ""


def test_protected_coverage_waits_on_direct_mirror_relation(monkeypatch) -> None:
    result = _run_protected(
        monkeypatch,
        prefix=[30, 17],
        cold_order=[3, 26, 8, 12],
        focus_number=30,
    )

    assert result["protected_excluded_numbers"] == [3, 26]
    assert result["protected_wait_triggered"] is True
    assert result["protected_wait_recommended_spins"] == 3
    assert any(
        match.get("relation") == "mirror"
        and match.get("source") == 3
        and match.get("via") == 30
        and match.get("trigger_number") == 30
        for match in result["protected_wait_matches"]
    )
    assert "espelho 30 de 3" in result["protected_wait_reason"]


def test_protected_coverage_swaps_same_terminal_conflict_when_enabled(monkeypatch) -> None:
    result = _run_protected(
        monkeypatch,
        prefix=[16, 5],
        cold_order=[3, 26, 8, 12],
        focus_number=16,
        protected_swap_enabled=True,
    )

    assert result["protected_original_excluded_numbers"] == [3, 26]
    assert result["protected_excluded_numbers"] == [3, 8]
    assert result["protected_swap_applied"] is True
    assert result["protected_wait_triggered"] is False
    assert result["protected_wait_recommended_spins"] == 0
    assert 26 in result["ordered_suggestion"]
    assert 8 not in result["ordered_suggestion"]
    assert result["protected_swap_details"] == [
        {
            "replaced_number": 26,
            "replacement_number": 8,
            "trigger_number": 16,
            "trigger_numbers": [16],
            "trigger_matches": [{"source": 26, "relation": "same_terminal", "trigger_number": 16}],
            "trigger_reason": "mesmo terminal de 26",
        }
    ]
    assert "26->8" in result["protected_swap_summary"]


def test_protected_coverage_swaps_when_previous_spin_hits_protected_zero_zone(monkeypatch) -> None:
    result = _run_protected(
        monkeypatch,
        prefix=[4, 26],
        cold_order=[0, 9, 8, 12],
        focus_number=4,
        protected_swap_enabled=True,
    )

    assert result["protected_original_excluded_numbers"] == [0, 9]
    assert result["protected_excluded_numbers"] == [0, 9]
    assert result["protected_swap_applied"] is False
    assert result["protected_wait_triggered"] is False
    assert result["protected_trigger_numbers"] == [4, 26]
    assert result["protected_swap_details"] == []


def test_protected_coverage_swaps_both_excluded_numbers_on_neighbor_mirror_context(monkeypatch) -> None:
    result = _run_protected(
        monkeypatch,
        prefix=[29, 4],
        cold_order=[0, 9, 8, 12, 17],
        focus_number=29,
        protected_swap_enabled=True,
    )

    assert result["protected_original_excluded_numbers"] == [0, 9]
    assert result["protected_excluded_numbers"] == [0, 8]
    assert result["protected_swap_applied"] is True
    assert result["protected_wait_triggered"] is False
    assert result["protected_swap_details"] == [
        {
            "replaced_number": 9,
            "replacement_number": 8,
            "trigger_number": 29,
            "trigger_numbers": [29],
            "trigger_matches": [{"source": 9, "relation": "same_terminal", "trigger_number": 29}],
            "trigger_reason": "mesmo terminal de 9",
        }
    ]


def test_protected_coverage_ignores_disabled_sequence_neighbor_and_neighbor_sequence_relations(monkeypatch) -> None:
    result = _run_protected(
        monkeypatch,
        prefix=[28, 20],
        cold_order=[6, 4, 8, 12],
        focus_number=28,
    )

    assert result["protected_excluded_numbers"] == [6, 4]
    assert result["protected_wait_triggered"] is False
    assert result["protected_wait_recommended_spins"] == 0
    assert result["protected_wait_matches"] == []


def test_protected_coverage_does_not_use_second_neighbor_for_mirror_chain(monkeypatch) -> None:
    result = _run_protected(
        monkeypatch,
        prefix=[29, 28],
        cold_order=[33, 25, 4, 20, 8, 12],
        focus_number=29,
        protected_swap_enabled=True,
    )

    assert result["protected_original_excluded_numbers"] == [33, 25]
    assert result["protected_excluded_numbers"] == [33, 25]
    assert result["protected_swap_applied"] is False
    assert result["protected_wait_triggered"] is False
    assert result["protected_swap_details"] == []


def test_protected_coverage_swaps_only_on_direct_sequence_relation(monkeypatch) -> None:
    result = _run_protected(
        monkeypatch,
        prefix=[6, 24],
        cold_order=[33, 25, 4, 20, 8, 12],
        focus_number=6,
        protected_swap_enabled=True,
    )

    assert result["protected_original_excluded_numbers"] == [33, 25]
    assert result["protected_excluded_numbers"] == [33, 20]
    assert result["protected_swap_applied"] is True
    assert result["protected_swap_details"] == [
        {
            "replaced_number": 25,
            "replacement_number": 20,
            "trigger_number": 24,
            "trigger_numbers": [24],
            "trigger_matches": [{"source": 25, "relation": "sequence", "trigger_number": 24}],
            "trigger_reason": "sequencia numerica de 25",
        },
    ]
    assert result["protected_wait_triggered"] is False


def test_protected_coverage_does_not_use_second_neighbor_for_direct_excluded_number(monkeypatch) -> None:
    result = _run_protected(
        monkeypatch,
        prefix=[28, 18],
        cold_order=[5, 9, 8, 12],
        focus_number=28,
    )

    assert result["protected_excluded_numbers"] == [5, 9]
    assert result["protected_wait_triggered"] is False
    assert result["protected_wait_recommended_spins"] == 0
    assert result["protected_wait_matches"] == []
