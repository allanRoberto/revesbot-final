from __future__ import annotations

from datetime import datetime, timezone

from api.routes import suggestion_monitor


def test_format_latest_event_exposes_human_readable_summary() -> None:
    item = suggestion_monitor._format_latest_event(
        {
            "_id": "evt-1",
            "anchor_history_id": "h1",
            "anchor_number": 27,
            "anchor_timestamp_br": datetime(2026, 4, 14, 4, 43, tzinfo=timezone.utc),
            "status": "resolved",
            "suggestion": list(range(24)),
            "suggestion_size": 24,
            "attempts_elapsed": 1,
            "resolved_attempt": 1,
            "resolved_number": 23,
            "resolved_rank_position": 22,
            "resolved_timestamp_br": datetime(2026, 4, 14, 4, 44, tzinfo=timezone.utc),
            "pattern_count": 18,
            "top_support_count": 6,
            "entry_shadow": {
                "entry_confidence": {"score": 79, "base_score_before_rank_feedback": 87},
                "probabilities": {"hit_1": 0.74},
                "late_hit_risk": 0.19,
                "rank_context_confidence": {"confidence_delta": -8, "latest_rank_band": "top"},
                "expected_value": {"net_units": 4.5},
                "recommendation": {
                    "action": "enter",
                    "label": "Entrar",
                    "reason": "Contexto forte.",
                },
            },
        }
    )

    assert item["outcome_label"] == "Hit em 1 tiro(s)"
    assert "Ancora 27 acertou" in item["summary"]
    assert item["shadow_action"] == "enter"
    assert item["shadow_confidence_base_score"] == 87
    assert item["shadow_confidence_score"] == 79
    assert item["shadow_confidence_delta"] == -8
    assert item["shadow_rank_context_band"] == "top"
    assert item["shadow_p_hit_1"] == 0.74


def test_compute_first_hit_streaks_tracks_current_and_max_runs() -> None:
    streaks = suggestion_monitor._compute_first_hit_streaks(
        [
            {"resolved_attempt": 1},
            {"resolved_attempt": 1},
            {"resolved_attempt": 2},
            {"resolved_attempt": 3},
            {"resolved_attempt": 4},
            {"resolved_attempt": 1},
            {"resolved_attempt": 2},
            {"resolved_attempt": 2},
            {"resolved_attempt": 1},
        ]
    )

    assert streaks["current_first_hit_streak"] == 1
    assert streaks["max_first_hit_streak"] == 2
    assert streaks["max_first_hit_streak_occurrences"] == 1
    assert streaks["first_hit_streak_occurrences"] == 3
    assert streaks["first_hit_streak_distribution"] == [
        {"length": 1, "occurrences": 2},
        {"length": 2, "occurrences": 1},
    ]
    assert streaks["current_unpaid_streak"] == 0
    assert streaks["max_unpaid_streak"] == 3
    assert streaks["max_unpaid_streak_occurrences"] == 1
    assert streaks["unpaid_streak_occurrences"] == 2
    assert streaks["unpaid_streak_distribution"] == [
        {"length": 2, "occurrences": 1},
        {"length": 3, "occurrences": 1},
    ]
    assert streaks["current_resolved_streak"] == 9
    assert streaks["recent_sequence"][-4:] == [1, 0, 0, 1]


def test_build_event_filter_supports_attempt_and_time_windows() -> None:
    filter_query = suggestion_monitor._build_event_filter(
        roulette_id="pragmatic-auto-roulette",
        config_key="cfg-1",
        attempt_filter="2",
        shadow_action="enter",
        start_date="2026-04-10",
        end_date="2026-04-14",
        start_hour=8,
        end_hour=12,
    )

    assert "$and" in filter_query
    conditions = filter_query["$and"]
    assert {"roulette_id": "pragmatic-auto-roulette", "config_key": "cfg-1"} in conditions
    assert {"status": "resolved", "resolved_attempt": 2} in conditions
    assert {"entry_shadow.recommendation.action": "enter"} in conditions
    assert {"anchor_date_br": {"$gte": "2026-04-10", "$lte": "2026-04-14"}} in conditions
    assert {"anchor_hour_br": {"$gte": 8, "$lte": 12}} in conditions


def test_build_event_filter_supports_optimized_variant_fields() -> None:
    filter_query = suggestion_monitor._build_event_filter(
        roulette_id="pragmatic-auto-roulette",
        ranking_variant="oscillation_v1",
        attempt_filter="3",
    )

    assert "$and" in filter_query
    conditions = filter_query["$and"]
    assert {"roulette_id": "pragmatic-auto-roulette"} in conditions
    assert {"ranking_variant": "oscillation_v1"} in conditions
    assert {"status": "resolved", "resolved_attempt": 3} in conditions


def test_build_event_filter_supports_aggressive_variant_fields() -> None:
    filter_query = suggestion_monitor._build_event_filter(
        roulette_id="pragmatic-auto-roulette",
        ranking_variant="oscillation_v2_aggressive",
        attempt_filter="2",
    )

    assert "$and" in filter_query
    conditions = filter_query["$and"]
    assert {"roulette_id": "pragmatic-auto-roulette"} in conditions
    assert {"ranking_variant": "oscillation_v2_aggressive"} in conditions
    assert {"status": "resolved", "resolved_attempt": 2} in conditions


def test_build_event_filter_supports_selective_variant_fields() -> None:
    filter_query = suggestion_monitor._build_event_filter(
        roulette_id="pragmatic-auto-roulette",
        ranking_variant="oscillation_v3_selective",
        attempt_filter="1",
    )

    assert "$and" in filter_query
    conditions = filter_query["$and"]
    assert {"roulette_id": "pragmatic-auto-roulette"} in conditions
    assert {"ranking_variant": "oscillation_v3_selective"} in conditions
    assert {"status": "resolved", "resolved_attempt": 1} in conditions


def test_build_event_filter_supports_selective_protected_variant_fields() -> None:
    filter_query = suggestion_monitor._build_event_filter(
        roulette_id="pragmatic-auto-roulette",
        ranking_variant="oscillation_v3_selective_protected",
        attempt_filter="1",
    )

    assert "$and" in filter_query
    conditions = filter_query["$and"]
    assert {"roulette_id": "pragmatic-auto-roulette"} in conditions
    assert {"ranking_variant": "oscillation_v3_selective_protected"} in conditions
    assert {"status": "resolved", "resolved_attempt": 1} in conditions


def test_build_event_filter_supports_temporal_blend_variant_fields() -> None:
    filter_query = suggestion_monitor._build_event_filter(
        roulette_id="pragmatic-auto-roulette",
        ranking_variant="temporal_blend_v1",
        attempt_filter="1",
    )

    assert "$and" in filter_query
    conditions = filter_query["$and"]
    assert {"roulette_id": "pragmatic-auto-roulette"} in conditions
    assert {"ranking_variant": "temporal_blend_v1"} in conditions
    assert {"status": "resolved", "resolved_attempt": 1} in conditions


def test_build_event_filter_supports_time_window_prior_variant_fields() -> None:
    filter_query = suggestion_monitor._build_event_filter(
        roulette_id="pragmatic-auto-roulette",
        ranking_variant="time_window_prior_v1",
        attempt_filter="1",
    )

    assert "$and" in filter_query
    conditions = filter_query["$and"]
    assert {"roulette_id": "pragmatic-auto-roulette"} in conditions
    assert {"ranking_variant": "time_window_prior_v1"} in conditions
    assert {"status": "resolved", "resolved_attempt": 1} in conditions


def test_build_event_filter_supports_top26_variant_fields() -> None:
    filter_query = suggestion_monitor._build_event_filter(
        roulette_id="pragmatic-auto-roulette",
        ranking_variant="ranking_v2_top26",
        attempt_filter="1",
    )

    assert "$and" in filter_query
    conditions = filter_query["$and"]
    assert {"roulette_id": "pragmatic-auto-roulette"} in conditions
    assert {"ranking_variant": "ranking_v2_top26"} in conditions
    assert {"status": "resolved", "resolved_attempt": 1} in conditions


def test_build_event_filter_supports_ml_meta_rank_variant_fields() -> None:
    filter_query = suggestion_monitor._build_event_filter(
        roulette_id="pragmatic-auto-roulette",
        ranking_variant="ml_meta_rank_v1",
        attempt_filter="1",
    )

    assert "$and" in filter_query
    conditions = filter_query["$and"]
    assert {"roulette_id": "pragmatic-auto-roulette"} in conditions
    assert {"ranking_variant": "ml_meta_rank_v1"} in conditions
    assert {"status": "resolved", "resolved_attempt": 1} in conditions


def test_build_event_filter_supports_ml_top12_reference_variant_fields() -> None:
    filter_query = suggestion_monitor._build_event_filter(
        roulette_id="pragmatic-auto-roulette",
        ranking_variant="ml_top12_reference_12x4_v1",
        attempt_filter="pending",
    )

    assert "$and" in filter_query
    conditions = filter_query["$and"]
    assert {"roulette_id": "pragmatic-auto-roulette"} in conditions
    assert {"ranking_variant": "ml_top12_reference_12x4_v1"} in conditions
    assert {"status": "pending"} in conditions


def test_build_event_filter_supports_ml_entry_gate_variant_fields() -> None:
    filter_query = suggestion_monitor._build_event_filter(
        roulette_id="pragmatic-auto-roulette",
        ranking_variant="ml_entry_gate_12x4_v1",
        attempt_filter="unavailable",
    )

    assert "$and" in filter_query
    conditions = filter_query["$and"]
    assert {"roulette_id": "pragmatic-auto-roulette"} in conditions
    assert {"ranking_variant": "ml_entry_gate_12x4_v1"} in conditions
    assert {"status": "unavailable"} in conditions


def test_build_event_filter_supports_top26_selective_variant_fields() -> None:
    filter_query = suggestion_monitor._build_event_filter(
        roulette_id="pragmatic-auto-roulette",
        ranking_variant="top26_selective_16x4_v1",
        attempt_filter="pending",
    )

    assert "$and" in filter_query
    conditions = filter_query["$and"]
    assert {"roulette_id": "pragmatic-auto-roulette"} in conditions
    assert {"ranking_variant": "top26_selective_16x4_v1"} in conditions
    assert {"status": "pending"} in conditions


def test_build_event_filter_supports_top26_selective_dynamic_variant_fields() -> None:
    filter_query = suggestion_monitor._build_event_filter(
        roulette_id="pragmatic-auto-roulette",
        ranking_variant="top26_selective_16x4_dynamic_v1",
        attempt_filter="pending",
    )

    assert "$and" in filter_query
    conditions = filter_query["$and"]
    assert {"roulette_id": "pragmatic-auto-roulette"} in conditions
    assert {"ranking_variant": "top26_selective_16x4_dynamic_v1"} in conditions
    assert {"status": "pending"} in conditions


def test_build_event_filter_defaults_to_base_variant_without_circular_reference() -> None:
    filter_query = suggestion_monitor._build_event_filter(
        roulette_id="pragmatic-auto-roulette",
        attempt_filter="1",
    )

    assert "$and" in filter_query
    conditions = filter_query["$and"]
    assert {"roulette_id": "pragmatic-auto-roulette"} in conditions
    assert {
        "$or": [
            {"ranking_variant": "base_v1"},
            {"ranking_variant": {"$exists": False}},
        ]
    } in conditions
    assert {"status": "resolved", "resolved_attempt": 1} in conditions


def test_build_attempt_options_orders_pending_then_attempts() -> None:
    options = suggestion_monitor._build_attempt_options_from_rows(
        [
            {"_id": {"status": "pending", "resolved_attempt": None}, "count": 4},
            {"_id": {"status": "resolved", "resolved_attempt": 3}, "count": 2},
            {"_id": {"status": "resolved", "resolved_attempt": 1}, "count": 7},
        ],
        total_events=13,
    )

    assert options[0]["value"] == ""
    assert options[0]["count"] == 13
    assert options[1]["value"] == "pending"
    assert options[2]["value"] == "1"
    assert options[3]["value"] == "3"


def test_build_rank_position_items_keeps_24_slots_and_hit_rates() -> None:
    items = suggestion_monitor._build_rank_position_items(
        [
            {"_id": 1, "count": 5},
            {"_id": 12, "count": 3},
            {"_id": 24, "count": 2},
        ],
        total_resolved=10,
    )

    assert len(items) == 24
    assert items[0] == {"position": 1, "hits": 5, "hit_rate": 0.5}
    assert items[11] == {"position": 12, "hits": 3, "hit_rate": 0.3}
    assert items[23] == {"position": 24, "hits": 2, "hit_rate": 0.2}


def test_build_window_outcome_items_exposes_strategy_suggestions() -> None:
    items = suggestion_monitor._build_window_outcome_items(
        [
            {
                "anchor_number": 21,
                "anchor_timestamp_br": datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc),
                "window_result_status": "hit",
                "window_result_attempt": 3,
                "resolved_attempt": 3,
                "resolved_number": 8,
                "resolved_rank_position": 11,
                "window_result_hit": True,
                "suggestion": [8, 12, 17, 23],
                "suggestion_size": 4,
            }
        ]
    )

    assert len(items) == 1
    assert items[0]["outcome"] == "hit"
    assert items[0]["window_attempt"] == 3
    assert items[0]["resolved_rank_position"] == 11
    assert items[0]["suggestion"] == [8, 12, 17, 23]
    assert items[0]["suggestion_size"] == 4


def test_build_window_outcome_items_exposes_ml_gate_context() -> None:
    items = suggestion_monitor._build_window_outcome_items(
        [
            {
                "anchor_number": 21,
                "anchor_timestamp_br": datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc),
                "window_result_status": "miss",
                "window_result_attempt": 4,
                "resolved_attempt": 4,
                "resolved_number": 8,
                "resolved_rank_position": 11,
                "window_result_hit": False,
                "suggestion": [8, 12, 17, 23],
                "suggestion_size": 4,
                "entry_shadow": {
                    "recommendation": {
                        "action": "wait",
                        "label": "Aguardar",
                        "reason": "Gate ML 0.511 < 0.520; entrada bloqueada.",
                    }
                },
                "oscillation": {
                    "ml_entry_gate": {
                        "probability": 0.511,
                        "threshold": 0.52,
                        "should_enter": False,
                        "trained_events": 9,
                        "warmup_events": 12,
                        "warmup_required": 6,
                        "warmup_ready": True,
                    }
                },
            }
        ]
    )

    assert len(items) == 1
    assert items[0]["gate_action"] == "wait"
    assert items[0]["gate_probability"] == 0.511
    assert items[0]["gate_threshold"] == 0.52
    assert items[0]["gate_warmup_required"] == 6
    assert items[0]["gate_warmup_ready"] is True


def test_build_window_monitor_aux_items_exposes_unavailable_gate_context() -> None:
    items = suggestion_monitor._build_window_monitor_aux_items(
        [
            {
                "anchor_number": 9,
                "anchor_timestamp_br": datetime(2026, 4, 20, 10, 1, tzinfo=timezone.utc),
                "attempts_elapsed": 0,
                "suggestion": [1, 2, 3],
                "suggestion_size": 3,
                "entry_shadow": {
                    "recommendation": {
                        "action": "wait",
                        "label": "Aguardar",
                        "reason": "Gate ML em aquecimento: 4/6 eventos treinados (threshold 0.520).",
                    }
                },
                "oscillation": {
                    "ml_entry_gate": {
                        "probability": 0.503,
                        "threshold": 0.52,
                        "trained_events": 4,
                        "warmup_events": 12,
                        "warmup_required": 6,
                        "warmup_ready": False,
                    }
                },
            }
        ]
    )

    assert len(items) == 1
    assert items[0]["suggestion"] == [1, 2, 3]
    assert items[0]["gate_label"] == "Aguardar"
    assert items[0]["gate_trained_events"] == 4
    assert items[0]["gate_warmup_ready"] is False


def test_build_rolling_metric_snapshots_computes_recent_windows() -> None:
    docs = [
        {"resolved_attempt": 1, "resolved_rank_position": 4},
        {"resolved_attempt": 2, "resolved_rank_position": 9},
        {"resolved_attempt": 1, "resolved_rank_position": 14},
        {"resolved_attempt": 3, "resolved_rank_position": 21},
        {"resolved_attempt": 4, "resolved_rank_position": 27},
    ]

    snapshots = suggestion_monitor._build_rolling_metric_snapshots(docs, windows=[3, 5])

    assert [item["window"] for item in snapshots] == [3, 5]
    assert snapshots[0]["sample_size"] == 3
    assert snapshots[0]["mean_rank"] == 9.0
    assert snapshots[0]["hit_at_12"] == 0.6667
    assert snapshots[0]["first_hit_rate"] == 0.6667
    assert snapshots[1]["sample_size"] == 5
    assert snapshots[1]["hit_at_26"] == 0.8


def test_build_gate_reference_pairs_matches_gate_context_by_anchor() -> None:
    pairs = suggestion_monitor._build_gate_reference_pairs(
        [
            {
                "anchor_history_id": "h-1",
                "anchor_number": 12,
                "window_result_hit": True,
                "window_result_attempt": 2,
            }
        ],
        [
            {
                "anchor_history_id": "h-1",
                "available": False,
                "entry_shadow": {
                    "recommendation": {
                        "action": "wait",
                        "label": "Aguardar",
                        "reason": "Gate ML 0.510 < 0.520; entrada bloqueada.",
                    }
                },
                "oscillation": {
                    "ml_entry_gate": {
                        "probability": 0.51,
                        "threshold": 0.52,
                        "should_enter": False,
                        "trained_events": 14,
                        "warmup_ready": True,
                    }
                },
            }
        ],
    )

    assert len(pairs) == 1
    assert pairs[0]["matched"] is True
    assert pairs[0]["reference_hit"] is True
    assert pairs[0]["gate_probability"] == 0.51
    assert pairs[0]["gate_should_enter"] is False


def test_build_gate_uplift_windows_computes_filtering_gain() -> None:
    rows = suggestion_monitor._build_gate_uplift_windows(
        [
            {"matched": True, "reference_hit": True, "gate_should_enter": True},
            {"matched": True, "reference_hit": False, "gate_should_enter": True},
            {"matched": True, "reference_hit": False, "gate_should_enter": False},
            {"matched": True, "reference_hit": False, "gate_should_enter": False},
        ],
        windows=[4],
    )

    assert len(rows) == 1
    assert rows[0]["matched_candidates"] == 4
    assert rows[0]["entries"] == 2
    assert rows[0]["activation_rate"] == 0.5
    assert rows[0]["reference_hit_rate"] == 0.25
    assert rows[0]["gate_hit_rate"] == 0.5
    assert rows[0]["uplift_vs_reference"] == 0.25
    assert rows[0]["avoided_miss_rate"] == 1.0


def test_build_gate_calibration_buckets_groups_probabilities() -> None:
    calibration = suggestion_monitor._build_gate_calibration_buckets(
        [
            {"matched": True, "reference_hit": True, "gate_should_enter": True, "gate_probability": 0.57, "gate_threshold": 0.52},
            {"matched": True, "reference_hit": False, "gate_should_enter": True, "gate_probability": 0.58, "gate_threshold": 0.52},
            {"matched": True, "reference_hit": False, "gate_should_enter": False, "gate_probability": 0.49, "gate_threshold": 0.52},
        ],
        limit=10,
    )

    assert calibration["sample_size"] == 3
    assert calibration["items"][0]["bucket"] == "0.45 - 0.50"
    assert calibration["items"][0]["count"] == 1
    assert calibration["items"][1]["bucket"] == "0.55 - 0.60"
    assert calibration["items"][1]["count"] == 2


def test_build_ml_variant_pair_rows_aligns_ml_top26_and_base_by_anchor() -> None:
    rows = suggestion_monitor._build_ml_variant_pair_rows(
        [
            {
                "anchor_history_id": "h-1",
                "anchor_number": 5,
                "anchor_timestamp_br": "2026-04-22 10:00:00",
                "anchor_timestamp_utc": "2026-04-22T13:00:00+00:00",
                "resolved_rank_position": 4,
                "resolved_attempt": 1,
            }
        ],
        [
            {
                "anchor_history_id": "h-1",
                "resolved_rank_position": 9,
                "resolved_attempt": 2,
            }
        ],
        [
            {
                "anchor_history_id": "h-1",
                "resolved_rank_position": 13,
                "resolved_attempt": 3,
            }
        ],
    )

    assert len(rows) == 1
    assert rows[0]["ml_rank"] == 4
    assert rows[0]["top26_rank"] == 9
    assert rows[0]["base_rank"] == 13
    assert rows[0]["ml_attempt"] == 1
    assert rows[0]["top26_attempt"] == 2
    assert rows[0]["base_attempt"] == 3


def test_build_ml_trend_points_computes_rolling_rank_gains() -> None:
    rows = [
        {
            "anchor_history_id": f"h-{index}",
            "anchor_timestamp_br": f"2026-04-22 10:{index:02d}:00",
            "anchor_timestamp_utc": f"2026-04-22T13:{index:02d}:00+00:00",
            "ml_rank": 3,
            "ml_attempt": 1,
            "top26_rank": 8,
            "top26_attempt": 2,
            "base_rank": 12,
            "base_attempt": 3,
        }
        for index in range(10)
    ]

    trend = suggestion_monitor._build_ml_trend_points(rows, rolling_window=10)

    assert len(trend["items"]) == 1
    latest = trend["latest"]
    assert latest["sample_size"] == 10
    assert latest["ml_mean_rank"] == 3.0
    assert latest["top26_mean_rank"] == 8.0
    assert latest["base_mean_rank"] == 12.0
    assert latest["mean_rank_gain_vs_top26"] == 5.0
    assert latest["mean_rank_gain_vs_base"] == 9.0
    assert latest["mrr_uplift_vs_top26"] > 0


def test_build_gate_uplift_trend_points_computes_rolling_uplift() -> None:
    pairs = [
        {
            "matched": True,
            "anchor_number": index,
            "reference_hit": index in {1, 2, 7},
            "gate_should_enter": index <= 4,
        }
        for index in range(1, 11)
    ]

    trend = suggestion_monitor._build_gate_uplift_trend_points(pairs, rolling_window=10)

    assert len(trend["items"]) == 1
    latest = trend["latest"]
    assert latest["sample_size"] == 10
    assert latest["activation_rate"] == 0.4
    assert latest["reference_hit_rate"] == 0.3
    assert latest["gate_hit_rate"] == 0.5
    assert latest["uplift_vs_reference"] == 0.2


def test_build_window_hit_breakdown_counts_hits_by_attempt() -> None:
    breakdown = suggestion_monitor._build_window_hit_breakdown(
        [
            {"window_result_status": "hit", "window_result_attempt": 1},
            {"window_result_status": "hit", "window_result_attempt": 2},
            {"window_result_status": "hit", "window_result_attempt": 2},
            {"window_result_status": "miss", "window_result_attempt": 4},
            {"window_result_status": "hit", "window_result_attempt": 4},
        ],
        max_attempts=4,
    )

    assert breakdown == {"1": 1, "2": 2, "3": 0, "4": 1}


def test_build_rank_timeline_items_buckets_attempts_for_timeline() -> None:
    items = suggestion_monitor._build_rank_timeline_items(
        [
            {
                "anchor_number": 4,
                "anchor_timestamp_br": datetime(2026, 4, 14, 10, 0, tzinfo=timezone.utc),
                "resolved_number": 22,
                "resolved_attempt": 1,
                "resolved_rank_position": 24,
            },
            {
                "anchor_number": 8,
                "anchor_timestamp_br": datetime(2026, 4, 14, 10, 1, tzinfo=timezone.utc),
                "resolved_number": 19,
                "resolved_attempt": 2,
                "resolved_rank_position": 12,
            },
            {
                "anchor_number": 11,
                "anchor_timestamp_br": datetime(2026, 4, 14, 10, 2, tzinfo=timezone.utc),
                "resolved_number": 3,
                "resolved_attempt": 4,
                "resolved_rank_position": 7,
            },
        ]
    )

    assert [item["attempt_bucket"] for item in items] == ["first", "second", "late"]
    assert [item["rank_position"] for item in items] == [24, 12, 7]
    assert [item["sequence_index"] for item in items] == [1, 2, 3]


def test_build_top_k_metrics_computes_hit_buckets_and_mrr() -> None:
    metrics = suggestion_monitor._build_top_k_metrics(
        [
            {"resolved_attempt": 1, "resolved_rank_position": 4},
            {"resolved_attempt": 2, "resolved_rank_position": 11},
            {"resolved_attempt": 3, "resolved_rank_position": 19},
            {"resolved_attempt": 4, "resolved_rank_position": 29},
        ],
        total_events=5,
    )

    assert metrics["total_events"] == 5
    assert metrics["total_resolved"] == 4
    assert metrics["hit_at_6"] == 0.25
    assert metrics["hit_at_12"] == 0.5
    assert metrics["hit_at_18"] == 0.5
    assert metrics["hit_at_26"] == 0.75
    assert metrics["top26_rate"] == 0.6
    assert metrics["mean_rank"] == 15.75
    assert metrics["mrr"] > 0.0


def test_apply_dynamic_pattern_weights_merges_current_runtime_weight() -> None:
    items = suggestion_monitor._apply_dynamic_pattern_weights(
        [
            {
                "pattern_id": "pattern_hot",
                "pattern_name": "Pattern Hot",
                "signals": 12,
                "covered_hits": 5,
                "covered_hit_rate": 0.4167,
                "first_hits": 4,
                "first_hit_rate": 0.3333,
                "avg_resolved_attempt": 1.75,
            },
            {
                "pattern_id": "pattern_cold",
                "pattern_name": "Pattern Cold",
                "signals": 12,
                "covered_hits": 5,
                "covered_hit_rate": 0.4167,
                "first_hits": 1,
                "first_hit_rate": 0.0833,
                "avg_resolved_attempt": 2.75,
            },
        ],
        weights={"pattern_hot": 1.42, "pattern_cold": 0.81},
        details={
            "pattern_hot": {"top_rank_hit_rate": 0.42, "deep_rank_hit_rate": 0.0, "sample": 6},
            "pattern_cold": {"top_rank_hit_rate": 0.0, "deep_rank_hit_rate": 0.38, "sample": 6},
        },
    )

    assert items[0]["pattern_id"] == "pattern_hot"
    assert items[0]["current_weight"] == 1.42
    assert items[0]["weight_delta"] == 0.42
    assert items[0]["top_rank_hit_rate"] == 0.42
    assert items[1]["pattern_id"] == "pattern_cold"
    assert items[1]["current_weight"] == 0.81
    assert items[1]["deep_rank_hit_rate"] == 0.38
