from __future__ import annotations

from datetime import datetime, timezone

from src.suggestion_monitor_runtime import (
    apply_rank_confidence_feedback,
    build_attempt_document,
    build_config_key,
    build_event_resolution_fields,
    build_monitor_event_document,
    build_time_window_prior_payload_from_base,
    build_top26_dynamic_follow_fields,
    build_oscillation_payload_from_base,
    build_ranking_v2_top26_payload_from_base,
    build_realtime_pattern_weights,
    build_selective_compact_payload_from_base,
    build_top26_selective_16x4_payload_from_top26,
    build_temporal_blend_payload_from_base,
    build_pattern_outcome_documents,
    build_pattern_resolution_documents,
    build_shadow_variant_resolution_fields,
)


def _anchor_doc() -> dict:
    return {
        "history_id": "anchor-1",
        "roulette_id": "pragmatic-auto-roulette",
        "roulette_name": "Pragmatic Auto Roulette",
        "value": 4,
        "history_timestamp_utc": datetime(2026, 4, 14, 12, 0, tzinfo=timezone.utc),
        "history_timestamp_br": datetime(2026, 4, 14, 9, 0, tzinfo=timezone.utc),
    }


def _simple_payload() -> dict:
    return {
        "available": True,
        "list": [13, 4, 22, 17],
        "number_details": [
            {
                "number": 13,
                "support_score": 5,
                "weighted_support_score": 5.5,
                "supporting_patterns": [],
            },
            {
                "number": 4,
                "support_score": 4,
                "weighted_support_score": 4.2,
                "supporting_patterns": [],
            },
            {
                "number": 22,
                "support_score": 3,
                "weighted_support_score": 3.2,
                "supporting_patterns": [],
            },
            {
                "number": 17,
                "support_score": 3,
                "weighted_support_score": 3.0,
                "supporting_patterns": [],
            },
            {
                "number": 29,
                "support_score": 2,
                "weighted_support_score": 2.4,
                "supporting_patterns": [],
            },
            {
                "number": 31,
                "support_score": 2,
                "weighted_support_score": 2.1,
                "supporting_patterns": [],
            },
        ],
        "pattern_count": 3,
        "unique_numbers": 4,
        "top_support_count": 5,
        "avg_support_count": 3.5,
        "min_support_count": 2,
        "selected_number_details": [
            {
                "number": 13,
                "support_score": 5,
                "weighted_support_score": 5.5,
                "supporting_patterns": [
                    {
                        "pattern_id": "p1",
                        "base_pattern_id": "p1",
                        "pattern_name": "Pattern One",
                        "applied_weight": 1.5,
                    }
                ],
            },
            {
                "number": 4,
                "support_score": 4,
                "weighted_support_score": 4.2,
                "supporting_patterns": [
                    {
                        "pattern_id": "p1",
                        "base_pattern_id": "p1",
                        "pattern_name": "Pattern One",
                        "applied_weight": 1.5,
                    },
                    {
                        "pattern_id": "p2",
                        "base_pattern_id": "p2",
                        "pattern_name": "Pattern Two",
                        "applied_weight": 1.0,
                    },
                ],
            },
        ],
        "entry_shadow": {"recommendation": {"action": "enter"}},
    }


def test_monitor_event_builds_pending_document_with_patterns() -> None:
    config_key = build_config_key(
        roulette_id="pragmatic-auto-roulette",
        suggestion_type="simple_http",
        max_numbers=24,
        history_window_size=500,
    )
    event_doc = build_monitor_event_document(
        anchor_doc=_anchor_doc(),
        simple_payload=_simple_payload(),
        history_values=[4, 9, 12, 18],
        config_key=config_key,
        shadow_compare_max_numbers=6,
    )

    assert event_doc["status"] == "pending"
    assert event_doc["suggestion"] == [13, 4, 22, 17]
    assert event_doc["shadow_variants"]["max_32"]["suggestion"] == [13, 4, 22, 17, 29, 31]
    assert event_doc["shadow_variants"]["max_32"]["suggestion_size"] == 6
    assert event_doc["pattern_count"] == 3
    assert len(event_doc["pattern_candidates"]) == 2

    pattern_docs = build_pattern_outcome_documents(event_doc)
    assert len(pattern_docs) == 2
    assert pattern_docs[0]["suggestion_event_id"] == event_doc["_id"]


def test_attempt_and_resolution_capture_rank_and_covering_patterns() -> None:
    config_key = build_config_key(
        roulette_id="pragmatic-auto-roulette",
        suggestion_type="simple_http",
        max_numbers=24,
        history_window_size=500,
    )
    event_doc = build_monitor_event_document(
        anchor_doc=_anchor_doc(),
        simple_payload=_simple_payload(),
        history_values=[4, 9, 12, 18],
        config_key=config_key,
        shadow_compare_max_numbers=6,
    )
    result_doc = {
        "history_id": "result-2",
        "value": 4,
        "history_timestamp_utc": datetime(2026, 4, 14, 12, 1, tzinfo=timezone.utc),
    }

    attempt_doc = build_attempt_document(event_doc, result_doc)
    resolution_fields = build_event_resolution_fields(event_doc, attempt_doc)
    pattern_docs = build_pattern_resolution_documents(event_doc, attempt_doc)

    assert attempt_doc["is_hit"] is True
    assert attempt_doc["hit_rank_position"] == 2
    assert len(attempt_doc["patterns_covering_result"]) == 2
    assert resolution_fields["status"] == "resolved"
    assert resolution_fields["resolved_attempt"] == 1
    assert resolution_fields["resolved_number"] == 4
    assert resolution_fields["resolved_rank_position"] == 2
    assert resolution_fields["hit_within_4"] is True
    assert any(doc["covered_hit"] is True for doc in pattern_docs)


def test_shadow_variant_can_resolve_before_base_list_extension() -> None:
    config_key = build_config_key(
        roulette_id="pragmatic-auto-roulette",
        suggestion_type="simple_http",
        max_numbers=24,
        history_window_size=500,
    )
    event_doc = build_monitor_event_document(
        anchor_doc=_anchor_doc(),
        simple_payload=_simple_payload(),
        history_values=[4, 9, 12, 18],
        config_key=config_key,
        shadow_compare_max_numbers=6,
    )
    result_doc = {
        "history_id": "result-3",
        "value": 29,
        "history_timestamp_utc": datetime(2026, 4, 14, 12, 1, tzinfo=timezone.utc),
    }

    attempt_doc = build_attempt_document(event_doc, result_doc)
    shadow_variants = build_shadow_variant_resolution_fields(
        event_doc,
        result_doc,
        attempt_number=int(attempt_doc["attempt_number"]),
    )

    assert attempt_doc["is_hit"] is False
    assert shadow_variants["max_32"]["status"] == "resolved"
    assert shadow_variants["max_32"]["resolved_attempt"] == 1
    assert shadow_variants["max_32"]["resolved_rank_position"] == 5


def test_oscillation_payload_reverses_after_top_extreme_base_hit() -> None:
    payload = build_oscillation_payload_from_base(
        base_payload=_simple_payload(),
        recent_resolved_base_events=[
            {"_id": "base-1", "resolved_rank_position": 1},
            {"_id": "base-0", "resolved_rank_position": 35},
        ],
    )

    assert payload is not None
    assert payload["oscillation"]["mode"] in {"rebound_from_top", "persistent_top_soft", "upper_bias_soft"}
    assert payload["oscillation"]["should_reverse"] is False
    assert payload["oscillation"]["source_base_event_id"] == "base-1"
    assert payload["oscillation"]["target_rank"] >= 3
    assert payload["oscillation"]["strength"] > 0
    assert payload["oscillation"]["recent_base_ranks"] == [1, 35]
    assert sorted(payload["suggestion"]) == [4, 13]


def test_monitor_event_document_tracks_variant_source_metadata() -> None:
    config_key = build_config_key(
        roulette_id="pragmatic-auto-roulette",
        suggestion_type="simple_http",
        max_numbers=37,
        history_window_size=200,
    )
    event_doc = build_monitor_event_document(
        anchor_doc=_anchor_doc(),
        simple_payload=_simple_payload(),
        history_values=[4, 9, 12, 18],
        config_key=f"{config_key}|variant=oscillation_v1",
        ranking_variant="oscillation_v1",
        source_base_event_id="smonitor:anchor-1:base",
        source_base_config_key=f"{config_key}|variant=base_v1",
    )

    assert event_doc["ranking_variant"] == "oscillation_v1"
    assert event_doc["ranking_source_variant"] == "base_v1"
    assert event_doc["source_base_event_id"] == "smonitor:anchor-1:base"


def test_oscillation_payload_supports_aggressive_profile() -> None:
    payload = build_oscillation_payload_from_base(
        base_payload=_simple_payload(),
        recent_resolved_base_events=[
            {"_id": "base-3", "resolved_rank_position": 2},
            {"_id": "base-2", "resolved_rank_position": 34},
            {"_id": "base-1", "resolved_rank_position": 4},
        ],
        profile="oscillation_v2_aggressive",
    )

    assert payload is not None
    assert payload["oscillation"]["profile"] == "oscillation_v2_aggressive"
    assert payload["oscillation"]["max_shift"] >= 4
    assert "aggressive" in payload["oscillation"]["mode"]


def test_oscillation_payload_selective_profile_can_refuse_entry() -> None:
    selected_details = [
        {
            "number": index,
            "support_score": max(1, 24 - index),
            "weighted_support_score": round(8.0 - (index * 0.2), 4),
            "supporting_patterns": [],
        }
        for index in range(24)
    ]
    payload_base = {
        **_simple_payload(),
        "list": [item["number"] for item in selected_details],
        "selected_number_details": selected_details,
    }
    payload = build_oscillation_payload_from_base(
        base_payload=payload_base,
        recent_resolved_base_events=[
            {"_id": "base-6", "resolved_rank_position": 12},
            {"_id": "base-5", "resolved_rank_position": 14},
            {"_id": "base-4", "resolved_rank_position": 13},
        ],
        profile="oscillation_v3_selective",
    )

    assert payload is not None
    assert payload["available"] is False
    assert payload["suggestion"] == []
    assert payload["oscillation"]["profile"] == "oscillation_v3_selective"
    assert payload["oscillation"]["selective_gate"]["active"] is False


def test_oscillation_payload_selective_protected_keeps_top_protection_candidates() -> None:
    selected_details = [
        {
            "number": index,
            "support_score": max(1, 40 - index),
            "weighted_support_score": round(10.0 - (index * 0.18), 4),
            "supporting_patterns": [],
        }
        for index in range(37)
    ]
    payload_base = {
        **_simple_payload(),
        "list": [item["number"] for item in selected_details],
        "selected_number_details": selected_details,
    }
    payload = build_oscillation_payload_from_base(
        base_payload=payload_base,
        recent_resolved_base_events=[
            {"_id": "base-8", "resolved_rank_position": 2},
            {"_id": "base-7", "resolved_rank_position": 1},
            {"_id": "base-6", "resolved_rank_position": 4},
        ],
        profile="oscillation_v3_selective_protected",
    )

    assert payload is not None
    assert payload["available"] is True
    assert payload["oscillation"]["profile"] == "oscillation_v3_selective_protected"
    assert payload["oscillation"]["protection"]["protection_side"] == "top"
    assert len(payload["suggestion"]) == 37
    top_slice = payload["suggestion"][:8]
    assert any(number <= 4 for number in top_slice)
    assert any(number >= 30 for number in top_slice)


def test_temporal_blend_payload_combines_recent_suggestions_and_results() -> None:
    selected_details = [
        {
            "number": index,
            "support_score": max(1, 40 - index),
            "weighted_support_score": round(10.0 - (index * 0.18), 4),
            "supporting_patterns": [],
        }
        for index in range(37)
    ]
    payload = build_temporal_blend_payload_from_base(
        base_payload={
            **_simple_payload(),
            "list": [item["number"] for item in selected_details],
            "selected_number_details": selected_details,
        },
        recent_resolved_base_events=[
            {
                "_id": "base-20",
                "suggestion": list(range(37)),
                "resolved_attempt": 1,
                "resolved_number": 32,
                "resolved_rank_position": 3,
            },
            {
                "_id": "base-19",
                "suggestion": list(reversed(range(37))),
                "resolved_attempt": 2,
                "resolved_number": 29,
                "resolved_rank_position": 34,
            },
        ],
        history_values=[32, 15, 19, 4, 21, 2],
    )

    assert payload is not None
    assert payload["available"] is True
    assert payload["oscillation"]["profile"] == "temporal_blend_v1"
    assert payload["oscillation"]["recent_history_numbers"][:3] == [32, 15, 19]
    assert payload["oscillation"]["memory_components"]["current_score_weight"] == 0.55
    assert len(payload["suggestion"]) == 37


def test_ranking_v2_top26_payload_preserves_37_numbers_and_reranks_top26() -> None:
    selected_details = [
        {
            "number": index,
            "support_score": max(1, 40 - index),
            "weighted_support_score": round(10.0 - (index * 0.18), 4),
            "supporting_patterns": [],
        }
        for index in range(37)
    ]
    payload = build_ranking_v2_top26_payload_from_base(
        base_payload={
            **_simple_payload(),
            "list": [item["number"] for item in selected_details],
            "selected_number_details": selected_details,
        },
        recent_resolved_base_events=[
            {
                "_id": "base-40",
                "suggestion": list(range(37)),
                "resolved_attempt": 1,
                "resolved_number": 4,
                "resolved_rank_position": 5,
            },
            {
                "_id": "base-39",
                "suggestion": list(range(36, -1, -1)),
                "resolved_attempt": 2,
                "resolved_number": 30,
                "resolved_rank_position": 30,
            },
        ],
        history_values=[4, 5, 8, 30, 32, 1, 19, 7],
    )

    assert payload is not None
    assert payload["available"] is True
    assert payload["oscillation"]["profile"] == "ranking_v2_top26"
    assert len(payload["suggestion"]) == 37
    assert len(payload["oscillation"]["candidate_set_26"]) == 26
    assert payload["oscillation"]["memory_components"]["pattern_score_weight"] == 0.45
    top26_flags = [bool(item.get("top26_candidate")) for item in payload["selected_number_details"]]
    assert top26_flags.count(True) == 26
    assert top26_flags.count(False) == 11


def test_time_window_prior_payload_reranks_using_same_time_historical_window() -> None:
    selected_details = [
        {
            "number": index,
            "support_score": max(1, 40 - index),
            "weighted_support_score": round(10.0 - (index * 0.18), 4),
            "supporting_patterns": [],
        }
        for index in range(37)
    ]
    payload = build_time_window_prior_payload_from_base(
        base_payload={
            **_simple_payload(),
            "list": [item["number"] for item in selected_details],
            "selected_number_details": selected_details,
        },
        docs_by_day={
            "2026-04-20": [{"value": 23}, {"value": 8}, {"value": 23}],
            "2026-04-21": [{"value": 23}, {"value": 31}, {"value": 8}],
        },
        lookback_days=45,
        minute_span=2,
        region_span=2,
        current_weight=0.75,
        exact_weight=0.10,
        region_weight=0.15,
    )

    assert payload is not None
    assert payload["available"] is True
    assert payload["oscillation"]["profile"] == "time_window_prior_v1"
    assert payload["oscillation"]["time_window_prior"]["lookback_days"] == 45
    assert payload["oscillation"]["time_window_prior"]["minute_span"] == 2
    assert payload["oscillation"]["time_window_prior"]["days_with_data"] == 2
    assert len(payload["suggestion"]) == 37
    detail_23 = next(item for item in payload["selected_number_details"] if item["number"] == 23)
    assert detail_23["time_window_reranked_position"] < detail_23["original_rank_position"]


def test_apply_rank_confidence_feedback_reduces_confidence_after_low_rank_streak() -> None:
    adjusted = apply_rank_confidence_feedback(
        {
            **_simple_payload(),
            "entry_shadow": {
                "entry_confidence": {"score": 82, "label": "Alta"},
                "late_hit_risk": 0.18,
                "reasons": [],
            },
        },
        [
            {"resolved_rank_position": 35, "suggestion_size": 37},
            {"resolved_rank_position": 31, "suggestion_size": 37},
            {"resolved_rank_position": 27, "suggestion_size": 37},
        ],
    )

    rank_context = adjusted["entry_shadow"]["rank_context_confidence"]
    assert adjusted["entry_shadow"]["entry_confidence"]["score"] > 82
    assert rank_context["confidence_delta"] > 0
    assert rank_context["lower_band_share"] > 0
    assert rank_context["latest_first_hit_penalty"] == 0
    assert rank_context["latest_bottom_rebound_bonus"] == 10


def test_apply_rank_confidence_feedback_reduces_confidence_after_top_rank_context() -> None:
    adjusted = apply_rank_confidence_feedback(
        {
            **_simple_payload(),
            "entry_shadow": {
                "entry_confidence": {"score": 68, "label": "Media"},
                "late_hit_risk": 0.24,
                "reasons": [],
            },
        },
        [
            {"resolved_rank_position": 4, "suggestion_size": 37},
            {"resolved_rank_position": 6, "suggestion_size": 37},
            {"resolved_rank_position": 8, "suggestion_size": 37},
        ],
    )

    rank_context = adjusted["entry_shadow"]["rank_context_confidence"]
    assert adjusted["entry_shadow"]["entry_confidence"]["score"] < 68
    assert rank_context["latest_rank_band"] == "top"
    assert rank_context["latest_top_exhaustion_penalty"] == 4


def test_apply_rank_confidence_feedback_penalizes_after_last_first_hit() -> None:
    adjusted = apply_rank_confidence_feedback(
        {
            **_simple_payload(),
            "entry_shadow": {
                "entry_confidence": {"score": 84, "label": "Alta"},
                "late_hit_risk": 0.18,
                "reasons": [],
            },
        },
        [
            {"resolved_rank_position": 5, "resolved_attempt": 1, "suggestion_size": 37},
            {"resolved_rank_position": 10, "resolved_attempt": 2, "suggestion_size": 37},
            {"resolved_rank_position": 16, "resolved_attempt": 2, "suggestion_size": 37},
        ],
    )

    rank_context = adjusted["entry_shadow"]["rank_context_confidence"]
    assert rank_context["latest_resolved_attempt"] == 1
    assert rank_context["latest_first_hit_penalty"] == 5
    assert rank_context["latest_rank_band"] == "top"
    assert adjusted["entry_shadow"]["entry_confidence"]["score"] < 84


def test_top26_selective_16x4_payload_opens_after_confirmed_descending_move() -> None:
    selected_details = [
        {
            "number": index,
            "support_score": max(1, 50 - index),
            "weighted_support_score": round(12.0 - (index * 0.22), 4),
            "supporting_patterns": [],
        }
        for index in range(37)
    ]
    top26_payload = build_ranking_v2_top26_payload_from_base(
        base_payload={
            **_simple_payload(),
            "list": [item["number"] for item in selected_details],
            "selected_number_details": selected_details,
        },
        recent_resolved_base_events=[
            {"_id": "base-60", "suggestion": list(range(37)), "resolved_attempt": 1, "resolved_number": 5, "resolved_rank_position": 4},
            {"_id": "base-59", "suggestion": list(range(37)), "resolved_attempt": 1, "resolved_number": 18, "resolved_rank_position": 18},
        ],
        history_values=[3, 19, 32, 17, 5, 11, 23, 30],
    )

    payload = build_top26_selective_16x4_payload_from_top26(
        top26_payload=top26_payload,
        recent_resolved_top26_events=[
            {"_id": "top26-3", "resolved_rank_position": 35},
            {"_id": "top26-2", "resolved_rank_position": 27},
            {"_id": "top26-1", "resolved_rank_position": 12},
        ],
        compact_size=14,
        evaluation_window_attempts=4,
    )

    assert payload is not None
    assert payload["available"] is True
    assert len(payload["suggestion"]) == 14
    assert payload["evaluation_window_attempts"] == 4
    assert payload["oscillation"]["profile"] == "top26_selective_16x4_v1"
    assert payload["oscillation"]["top26_gate"]["active"] is True
    assert payload["oscillation"]["top26_gate"]["trend"] == "descending_rebound_ready"


def test_top26_selective_16x4_payload_waits_when_recent_rank_is_in_middle_band() -> None:
    selected_details = [
        {
            "number": index,
            "support_score": max(1, 50 - index),
            "weighted_support_score": round(12.0 - (index * 0.22), 4),
            "supporting_patterns": [],
        }
        for index in range(37)
    ]
    top26_payload = build_ranking_v2_top26_payload_from_base(
        base_payload={
            **_simple_payload(),
            "list": [item["number"] for item in selected_details],
            "selected_number_details": selected_details,
        },
        recent_resolved_base_events=[
            {"_id": "base-62", "suggestion": list(range(37)), "resolved_attempt": 1, "resolved_number": 9, "resolved_rank_position": 7},
        ],
        history_values=[3, 19, 32, 17, 5, 11, 23, 30],
    )

    payload = build_top26_selective_16x4_payload_from_top26(
        top26_payload=top26_payload,
        recent_resolved_top26_events=[
            {"_id": "top26-6", "resolved_rank_position": 20},
            {"_id": "top26-5", "resolved_rank_position": 17},
            {"_id": "top26-4", "resolved_rank_position": 14},
        ],
        compact_size=14,
        evaluation_window_attempts=4,
    )

    assert payload is not None
    assert payload["available"] is False
    assert payload["suggestion"] == []
    assert payload["evaluation_window_attempts"] == 4
    assert payload["oscillation"]["profile"] == "top26_selective_16x4_v1"
    assert payload["oscillation"]["top26_gate"]["active"] is False


def test_top26_dynamic_follow_fields_replaces_suggestion_with_latest_top26_snapshot() -> None:
    dynamic_event = build_monitor_event_document(
        anchor_doc=_anchor_doc(),
        simple_payload={
            **_simple_payload(),
            "list": [13, 4, 22, 17],
            "selected_number_details": [
                {"number": 13, "support_score": 5, "weighted_support_score": 5.5, "supporting_patterns": []},
                {"number": 4, "support_score": 4, "weighted_support_score": 4.2, "supporting_patterns": []},
                {"number": 22, "support_score": 3, "weighted_support_score": 3.2, "supporting_patterns": []},
                {"number": 17, "support_score": 3, "weighted_support_score": 3.0, "supporting_patterns": []},
            ],
            "evaluation_window_attempts": 4,
            "oscillation": {
                "profile": "top26_selective_16x4_dynamic_v1",
                "compact_size": 4,
                "active_top26_event_id": "top26-old",
                "follow_updates": 0,
            },
        },
        history_values=[4, 9, 12, 18],
        config_key="cfg|variant=top26_selective_16x4_dynamic_v1",
        ranking_variant="top26_selective_16x4_dynamic_v1",
        ranking_source_variant="ranking_v2_top26",
    )
    latest_top26_event = {
        "_id": "top26-new",
        "anchor_history_id": "hist-55",
        "anchor_number": 31,
        "suggestion": [8, 12, 16, 20, 24],
        "selected_number_details": [
            {"number": 8, "support_score": 8, "weighted_support_score": 8.0, "supporting_patterns": []},
            {"number": 12, "support_score": 7, "weighted_support_score": 7.0, "supporting_patterns": []},
            {"number": 16, "support_score": 6, "weighted_support_score": 6.0, "supporting_patterns": []},
            {"number": 20, "support_score": 5, "weighted_support_score": 5.0, "supporting_patterns": []},
            {"number": 24, "support_score": 4, "weighted_support_score": 4.0, "supporting_patterns": []},
        ],
    }

    fields = build_top26_dynamic_follow_fields(dynamic_event, latest_top26_event)

    assert fields["suggestion"] == [8, 12, 16, 20]
    assert fields["suggestion_size"] == 4
    assert fields["oscillation"]["active_top26_event_id"] == "top26-new"
    assert fields["oscillation"]["follow_updates"] == 1


def test_selective_compact_payload_builds_18_numbers_and_window_metadata() -> None:
    selected_details = [
        {
            "number": index,
            "support_score": max(1, 40 - index),
            "weighted_support_score": round(10.0 - (index * 0.18), 4),
            "supporting_patterns": [],
        }
        for index in range(37)
    ]
    payload = build_selective_compact_payload_from_base(
        base_payload={
            **_simple_payload(),
            "list": [item["number"] for item in selected_details],
            "selected_number_details": selected_details,
        },
        recent_resolved_base_events=[
            {"_id": "base-9", "resolved_rank_position": 2},
            {"_id": "base-8", "resolved_rank_position": 1},
            {"_id": "base-7", "resolved_rank_position": 3},
        ],
        compact_size=14,
        hold_rounds=4,
    )

    assert payload is not None
    assert payload["available"] is True
    assert len(payload["suggestion"]) == 14
    assert payload["evaluation_window_attempts"] == 4
    assert payload["oscillation"]["profile"] == "oscillation_v4_selective_compact"
    assert payload["oscillation"]["compact_hold"]["rounds_total"] == 4


def test_selective_compact_payload_can_open_with_short_edge_sample() -> None:
    selected_details = [
        {
            "number": index,
            "support_score": max(1, 40 - index),
            "weighted_support_score": round(10.0 - (index * 0.18), 4),
            "supporting_patterns": [],
        }
        for index in range(37)
    ]
    payload = build_selective_compact_payload_from_base(
        base_payload={
            **_simple_payload(),
            "list": [item["number"] for item in selected_details],
            "selected_number_details": selected_details,
        },
        recent_resolved_base_events=[
            {"_id": "base-11", "resolved_rank_position": 4},
            {"_id": "base-10", "resolved_rank_position": 18},
        ],
        compact_size=14,
        hold_rounds=4,
    )

    assert payload is not None
    assert payload["available"] is True
    assert payload["oscillation"]["compact_hold"]["origin"] == "new_gate"
    assert payload["oscillation"]["selective_gate"]["active"] is True


def test_event_resolution_fields_track_window_miss_after_third_attempt() -> None:
    config_key = build_config_key(
        roulette_id="pragmatic-auto-roulette",
        suggestion_type="simple_http",
        max_numbers=18,
        history_window_size=200,
    )
    event_doc = build_monitor_event_document(
        anchor_doc=_anchor_doc(),
        simple_payload={
            **_simple_payload(),
            "list": [13, 4, 22],
            "selected_number_details": [
                {"number": 13, "support_score": 5, "weighted_support_score": 5.5, "supporting_patterns": []},
                {"number": 4, "support_score": 4, "weighted_support_score": 4.2, "supporting_patterns": []},
                {"number": 22, "support_score": 3, "weighted_support_score": 3.2, "supporting_patterns": []},
            ],
            "evaluation_window_attempts": 3,
        },
        history_values=[4, 9, 12, 18],
        config_key=f"{config_key}|variant=oscillation_v4_selective_compact",
        ranking_variant="oscillation_v4_selective_compact",
    )
    event_doc["attempts_elapsed"] = 2
    attempt_doc = {
        "attempt_number": 3,
        "result_number": 30,
        "result_history_id": "result-3",
        "result_timestamp_utc": datetime(2026, 4, 14, 12, 3, tzinfo=timezone.utc),
        "is_hit": False,
    }

    fields = build_event_resolution_fields(event_doc, attempt_doc)

    assert fields["status"] == "resolved"
    assert fields["window_result_status"] == "miss"
    assert fields["window_result_finalized"] is True
    assert fields["window_result_hit"] is False


def test_realtime_pattern_weights_reward_top_hits_and_penalize_misses() -> None:
    summary = build_realtime_pattern_weights(
        [
            {
                "_id": "evt-2",
                "status": "resolved",
                "resolved_attempt": 1,
                "resolved_rank_position": 2,
                "suggestion_size": 37,
                "hit_pattern_ids": ["pattern_hot"],
                "pattern_candidates": [
                    {
                        "pattern_id": "pattern_hot",
                        "base_pattern_id": "pattern_hot",
                        "supported_rank_positions": [1, 2, 3],
                    },
                    {
                        "pattern_id": "pattern_cold",
                        "base_pattern_id": "pattern_cold",
                        "supported_rank_positions": [1, 4, 5],
                    },
                ],
            },
            {
                "_id": "evt-1",
                "status": "resolved",
                "resolved_attempt": 2,
                "resolved_rank_position": 28,
                "suggestion_size": 37,
                "hit_pattern_ids": ["pattern_hot"],
                "pattern_candidates": [
                    {
                        "pattern_id": "pattern_hot",
                        "base_pattern_id": "pattern_hot",
                        "supported_rank_positions": [2, 6, 7],
                    },
                    {
                        "pattern_id": "pattern_cold",
                        "base_pattern_id": "pattern_cold",
                        "supported_rank_positions": [1, 3, 8],
                    },
                ],
            },
        ],
        previous_weights={"pattern_hot": 1.0, "pattern_cold": 1.0},
        lookback=12,
        weight_floor=0.55,
        weight_ceil=1.85,
        smoothing_alpha=0.35,
        sample_target=4.0,
        top_rank_bonus=0.9,
    )

    assert summary["applied"] is True
    assert summary["weights"]["pattern_hot"] > 1.0
    assert summary["weights"]["pattern_cold"] < 1.0
    assert summary["top_weights"][0]["pattern_id"] == "pattern_hot"


def test_realtime_pattern_weights_penalize_patterns_that_only_hit_late_ranks() -> None:
    summary = build_realtime_pattern_weights(
        [
            {
                "_id": "evt-top",
                "status": "resolved",
                "resolved_attempt": 1,
                "resolved_rank_position": 3,
                "suggestion_size": 37,
                "hit_pattern_ids": ["pattern_top"],
                "pattern_candidates": [
                    {
                        "pattern_id": "pattern_top",
                        "base_pattern_id": "pattern_top",
                        "supported_rank_positions": [1, 2, 3],
                    },
                    {
                        "pattern_id": "pattern_bottom",
                        "base_pattern_id": "pattern_bottom",
                        "supported_rank_positions": [26, 30, 34],
                    },
                ],
            },
            {
                "_id": "evt-bottom-1",
                "status": "resolved",
                "resolved_attempt": 2,
                "resolved_rank_position": 31,
                "suggestion_size": 37,
                "hit_pattern_ids": ["pattern_bottom"],
                "pattern_candidates": [
                    {
                        "pattern_id": "pattern_top",
                        "base_pattern_id": "pattern_top",
                        "supported_rank_positions": [1, 4, 5],
                    },
                    {
                        "pattern_id": "pattern_bottom",
                        "base_pattern_id": "pattern_bottom",
                        "supported_rank_positions": [27, 31, 35],
                    },
                ],
            },
            {
                "_id": "evt-bottom-2",
                "status": "resolved",
                "resolved_attempt": 1,
                "resolved_rank_position": 34,
                "suggestion_size": 37,
                "hit_pattern_ids": ["pattern_bottom"],
                "pattern_candidates": [
                    {
                        "pattern_id": "pattern_top",
                        "base_pattern_id": "pattern_top",
                        "supported_rank_positions": [2, 6, 8],
                    },
                    {
                        "pattern_id": "pattern_bottom",
                        "base_pattern_id": "pattern_bottom",
                        "supported_rank_positions": [29, 33, 36],
                    },
                ],
            },
        ],
        previous_weights={"pattern_top": 1.0, "pattern_bottom": 1.0},
        lookback=12,
        weight_floor=0.55,
        weight_ceil=1.85,
        smoothing_alpha=0.35,
        sample_target=4.0,
        top_rank_bonus=0.9,
    )

    assert summary["weights"]["pattern_top"] > summary["weights"]["pattern_bottom"]
    assert summary["weights"]["pattern_bottom"] < 1.0
    assert summary["details"]["pattern_top"]["top_rank_hit_rate"] > 0.0
    assert summary["details"]["pattern_bottom"]["deep_rank_hit_rate"] > 0.0
