from __future__ import annotations

from datetime import datetime, timezone

from src.suggestion_monitor_runtime import (
    build_attempt_document,
    build_config_key,
    build_event_resolution_fields,
    build_monitor_event_document,
    build_oscillation_payload_from_base,
    build_selective_compact_payload_from_base,
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
        compact_size=18,
        hold_rounds=3,
    )

    assert payload is not None
    assert payload["available"] is True
    assert len(payload["suggestion"]) == 18
    assert payload["evaluation_window_attempts"] == 3
    assert payload["oscillation"]["profile"] == "oscillation_v4_selective_compact"
    assert payload["oscillation"]["compact_hold"]["rounds_total"] == 3


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
        compact_size=18,
        hold_rounds=3,
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
