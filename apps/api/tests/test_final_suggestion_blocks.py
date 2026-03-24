from __future__ import annotations

from api.patterns.final_suggestion import build_final_suggestion


def _build_result(
    *,
    base_list: list[int],
    optimized_list: list[int] | None = None,
    block_bets_enabled: bool,
) -> dict:
    return build_final_suggestion(
        base_list=base_list,
        optimized_list=optimized_list or list(base_list),
        optimized_confidence=72,
        number_details=[],
        base_confidence_score=68,
        max_size=len(base_list),
        history_arr=[],
        from_index=0,
        pulled_counts={},
        base_weight=0.5,
        optimized_weight=0.5,
        block_bets_enabled=block_bets_enabled,
        inversion_enabled=False,
    )


def test_keeps_current_result_when_block_toggle_is_disabled() -> None:
    result = _build_result(
        base_list=[4, 2, 30, 14],
        block_bets_enabled=False,
    )

    assert result["list"] == [4, 2, 30, 14]
    assert result["blockCompaction"]["changed"] is False


def test_fills_single_gap_on_wheel_without_changing_quantity() -> None:
    result = _build_result(
        base_list=[4, 2, 30, 14],
        block_bets_enabled=True,
    )

    assert len(result["list"]) == 4
    assert 21 in result["list"]
    assert 14 not in result["list"]
    assert result["blockCompaction"]["changed"] is True
    assert 21 in result["blockCompaction"]["added"]
    assert 14 in result["blockCompaction"]["removed"]


def test_adds_neighbor_for_isolated_number_and_removes_lower_ranked_number() -> None:
    result = _build_result(
        base_list=[8, 4, 21, 14, 31],
        block_bets_enabled=True,
    )

    assert len(result["list"]) == 5
    assert 8 in result["list"]
    assert any(n in result["list"] for n in (23, 30))
    assert 31 not in result["list"]
    assert result["breakdown"]["block_compaction_applied"] is True
