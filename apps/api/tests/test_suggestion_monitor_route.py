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
                "entry_confidence": {"score": 79},
                "probabilities": {"hit_1": 0.74},
                "late_hit_risk": 0.19,
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
    assert item["shadow_confidence_score"] == 79
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


def test_build_event_filter_supports_compact_variant_fields() -> None:
    filter_query = suggestion_monitor._build_event_filter(
        roulette_id="pragmatic-auto-roulette",
        ranking_variant="oscillation_v4_selective_compact",
        attempt_filter="pending",
    )

    assert "$and" in filter_query
    conditions = filter_query["$and"]
    assert {"roulette_id": "pragmatic-auto-roulette"} in conditions
    assert {"ranking_variant": "oscillation_v4_selective_compact"} in conditions
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
