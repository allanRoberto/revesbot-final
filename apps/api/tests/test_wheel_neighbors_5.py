from __future__ import annotations

import json

import pytest

from api.patterns.engine import PatternDefinition, PatternEngine
from api.services.wheel_neighbors_5 import (
    WHEEL_NEIGHBORS_5_HORIZON_PRIORS,
    build_wheel_neighbors_5_candidate_map,
    build_wheel_neighbors_5_pending_candidate_scores,
    build_wheel_neighbors_5_pending_state,
    build_wheel_neighbors_5_result,
    compute_wheel_neighbors_5_dynamic_multiplier,
    get_wheel_neighbors_5_feedback_store,
    get_wheel_neighbors_5_window,
)


def _definition(storage_path: str) -> PatternDefinition:
    return PatternDefinition(
        id="wheel_neighbors_5",
        name="Wheel Neighbors 5",
        version="1.0.0",
        kind="positive",
        active=True,
        priority=74,
        weight=8.0,
        evaluator="wheel_neighbors_5",
        max_numbers=11,
        params={
            "wheel_window": 5,
            "default_horizon_spins": 8,
            "horizon_spins": 8,
            "recent_window_size": 100,
            "feedback_anchor_size": 12,
            "feedback_storage_path": storage_path,
        },
    )


def test_generates_expected_window_for_number_9() -> None:
    assert get_wheel_neighbors_5_window(9) == [33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28]


def test_generates_expected_window_for_number_33() -> None:
    assert get_wheel_neighbors_5_window(33) == [23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9]


def test_wrap_around_works_for_zero() -> None:
    assert get_wheel_neighbors_5_window(0) == [28, 12, 35, 3, 26, 0, 32, 15, 19, 4, 21]


def test_pending_bases_follow_unpaid_sequence_logic() -> None:
    state = build_wheel_neighbors_5_pending_state(
        history=[23, 24, 27, 16, 7, 14, 2, 2, 31, 19],
        horizon_used=8,
    )

    assert state["pending_bases"] == [7, 27, 23]


def test_single_spin_can_resolve_multiple_pending_bases() -> None:
    state = build_wheel_neighbors_5_pending_state(
        history=[30, 23, 24, 27, 16, 7, 14, 2, 2, 31, 19],
        horizon_used=8,
    )

    assert state["pending_bases"] == [7, 30]
    resolved_by_30 = [
        item["base_number"]
        for item in state["resolved_activations"]
        if item["resolved_by_number"] == 30
    ]
    assert resolved_by_30 == [27, 23]


def test_candidate_positions_are_mapped_correctly() -> None:
    candidate_map = build_wheel_neighbors_5_candidate_map(33)

    assert candidate_map["candidate_details"]["23"]["position"] == "left_5"
    assert candidate_map["candidate_details"]["33"]["position"] == "self"
    assert candidate_map["candidate_details"]["9"]["position"] == "right_5"
    assert candidate_map["candidate_positions"]["20"]["wheel_offset"] == 2


def test_local_scores_are_normalized_and_non_uniform() -> None:
    result = build_wheel_neighbors_5_result(base_number=33)
    scores = result["scores"]

    assert all(0.0 <= float(score) <= 1.0 for score in scores.values())
    assert len({round(float(score), 6) for score in scores.values()}) > 1
    assert scores[20] > scores[33]
    assert scores[24] < scores[23]


def test_pending_overlap_boosts_shared_candidates() -> None:
    pending_scores = build_wheel_neighbors_5_pending_candidate_scores(
        history=[23, 24, 27, 16, 7, 14, 2, 2, 31, 19],
        horizon_used=8,
        latest_base_number=23,
    )
    candidate_30 = pending_scores["candidate_details"]["30"]

    assert candidate_30["overlap_count"] == 2
    assert candidate_30["supporting_base_numbers"] == [27, 23]
    assert 30 in pending_scores["selected_numbers"]


@pytest.mark.parametrize(
    ("horizon", "expected_rate"),
    [
        (6, 0.8829),
        (8, 0.9440),
        (10, 0.9645),
        (14, 0.9935),
    ],
)
def test_expected_hit_rate_by_horizon(horizon: int, expected_rate: float) -> None:
    result = build_wheel_neighbors_5_result(base_number=9, requested_horizon=horizon)

    assert result["meta"]["horizon_config_used"]["horizon_used"] == horizon
    assert result["meta"]["horizon_config_used"]["expected_hit_rate"] == pytest.approx(expected_rate)
    assert WHEEL_NEIGHBORS_5_HORIZON_PRIORS[horizon] == pytest.approx(expected_rate)


def test_dynamic_multiplier_stays_neutral_without_recent_history() -> None:
    result = compute_wheel_neighbors_5_dynamic_multiplier(
        recent_total=0,
        recent_hits=0,
        recent_hit_count=0,
        recent_early_sum=0.0,
        expected_hit_rate=0.9440,
    )

    assert result["dynamic_multiplier"] == pytest.approx(1.0)


def test_dynamic_multiplier_rises_with_good_recent_history() -> None:
    result = compute_wheel_neighbors_5_dynamic_multiplier(
        recent_total=100,
        recent_hits=99,
        recent_hit_count=99,
        recent_early_sum=99 * 0.68,
        expected_hit_rate=0.9440,
    )

    assert result["dynamic_multiplier"] > 1.0


def test_dynamic_multiplier_drops_with_poor_recent_history() -> None:
    result = compute_wheel_neighbors_5_dynamic_multiplier(
        recent_total=100,
        recent_hits=72,
        recent_hit_count=72,
        recent_early_sum=72 * 0.32,
        expected_hit_rate=0.9440,
    )

    assert result["dynamic_multiplier"] < 1.0
    assert result["dynamic_multiplier"] >= 0.85


def test_dynamic_multiplier_is_smoothed_for_small_sample() -> None:
    strong = compute_wheel_neighbors_5_dynamic_multiplier(
        recent_total=100,
        recent_hits=99,
        recent_hit_count=99,
        recent_early_sum=99 * 0.68,
        expected_hit_rate=0.9440,
    )
    small = compute_wheel_neighbors_5_dynamic_multiplier(
        recent_total=3,
        recent_hits=3,
        recent_hit_count=3,
        recent_early_sum=3 * 1.0,
        expected_hit_rate=0.9440,
    )

    assert 1.0 < small["dynamic_multiplier"] < strong["dynamic_multiplier"]


def test_feedback_store_persists_and_resolves_hit_and_miss(tmp_path) -> None:
    storage_path = tmp_path / "wheel_neighbors_5_feedback.json"
    store = get_wheel_neighbors_5_feedback_store(storage_path)
    store.clear()

    candidate_map = build_wheel_neighbors_5_candidate_map(9)
    snapshot = store.recent_performance_snapshot(horizon_used=8)

    store.register_activation(
        base_number=9,
        ordered_candidates=candidate_map["ordered_candidates"],
        candidate_positions=candidate_map["candidate_positions"],
        horizon_used=8,
        expected_hit_rate=0.9440,
        history_anchor=[9, 22, 18, 29, 7, 28],
        recent_snapshot=snapshot,
    )

    resolved_hit = store.resolve_from_history(
        history=[17, 1, 9, 22, 18, 29, 7, 28],
    )
    assert len(resolved_hit) == 1
    assert resolved_hit[0]["status"] == "hit"
    assert resolved_hit[0]["hit_round"] == 1
    assert resolved_hit[0]["hit_number"] == 1
    assert resolved_hit[0]["hit_position"] == "left_4"

    candidate_map_33 = build_wheel_neighbors_5_candidate_map(33)
    store.register_activation(
        base_number=33,
        ordered_candidates=candidate_map_33["ordered_candidates"],
        candidate_positions=candidate_map_33["candidate_positions"],
        horizon_used=8,
        expected_hit_rate=0.9440,
        history_anchor=[33, 1, 20, 14, 31, 9],
        recent_snapshot=store.recent_performance_snapshot(horizon_used=8),
    )

    resolved_miss = store.resolve_from_history(
        history=[27, 25, 21, 19, 17, 15, 13, 11, 2, 33, 1, 20, 14, 31, 9],
    )
    assert len(resolved_miss) == 1
    assert resolved_miss[0]["status"] == "miss"
    assert resolved_miss[0]["hit_round"] is None
    assert resolved_miss[0]["hit_position"] is None

    recent = store.recent_performance_snapshot(horizon_used=8)
    assert recent["recent_sample_size"] == 2
    assert recent["recent_hits"] == 1
    assert recent["recent_hit_rate"] == pytest.approx(0.5)


def test_pattern_integrates_into_engine_and_exposes_metadata(tmp_path) -> None:
    definition = {
        "id": "wheel_neighbors_5",
        "name": "Wheel Neighbors 5",
        "kind": "positive",
        "version": "1.0.0",
        "active": True,
        "priority": 74,
        "weight": 8.0,
        "evaluator": "wheel_neighbors_5",
        "max_numbers": 11,
        "params": {
            "wheel_window": 5,
            "default_horizon_spins": 8,
            "horizon_spins": 8,
            "recent_window_size": 100,
            "feedback_anchor_size": 12,
            "feedback_storage_path": str(tmp_path / "wheel_neighbors_5_feedback.json"),
        },
    }
    (tmp_path / "wheel_neighbors_5.json").write_text(json.dumps(definition), encoding="utf-8")

    engine = PatternEngine(patterns_dir=tmp_path)
    history = [9, 22, 18, 29, 7, 28, 12, 35, 3, 26]
    result = engine.evaluate(
        history,
        use_adaptive_weights=False,
        use_fallback=False,
    )

    assert result["available"] is False
    assert result["filter_reason"] == "Padroes insuficientes: 1/3"
    assert len(result["contributions"]) == 1
    contribution = result["contributions"][0]
    assert contribution["pattern_id"] == "wheel_neighbors_5"
    assert contribution["dynamic_multiplier"] == pytest.approx(1.0)
    assert contribution["meta"]["base_number"] == 9
    assert contribution["meta"]["ordered_candidates"] == [33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28]
    assert contribution["meta"]["recent_performance_snapshot"]["recent_sample_size"] == 0

    selected_details = [item for item in result["number_details"] if item["selected"]]
    assert len(selected_details) == 11
    assert len({round(float(item["net_score"]), 4) for item in selected_details}) > 1
