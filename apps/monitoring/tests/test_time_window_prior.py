from __future__ import annotations

from datetime import datetime, timezone

from apps.monitoring.src.time_window_prior import (
    build_daily_window_bounds,
    compute_time_window_priors,
    get_region_numbers,
    rerank_with_time_window_prior,
)


def test_build_daily_window_bounds_with_two_minute_span() -> None:
    reference = datetime(2026, 4, 22, 3, 14, 0, tzinfo=timezone.utc)
    start, end = build_daily_window_bounds(reference, minute_span=2)
    assert start.minute == 12
    assert end.minute == 17


def test_compute_time_window_priors_rewards_exact_and_region_history() -> None:
    docs_by_day = {
        "2026-04-20": [{"value": 10}, {"value": 23}],
        "2026-04-21": [{"value": 10}, {"value": 24}],
    }
    summary = compute_time_window_priors(docs_by_day, lookback_days=45, region_span=2)
    assert summary["exact_prior"][10] > summary["exact_prior"][23]
    assert summary["region_prior"][10] > 0.0
    assert summary["region_prior"][23] > 0.0


def test_rerank_with_time_window_prior_promotes_temporal_hits() -> None:
    simple_payload = {
        "ordered_suggestion": [7, 10, 23, 30],
        "selected_number_details": [
            {"number": 7, "weighted_support_score": 4.0},
            {"number": 10, "weighted_support_score": 3.8},
            {"number": 23, "weighted_support_score": 3.5},
            {"number": 30, "weighted_support_score": 3.0},
        ],
    }
    reranked = rerank_with_time_window_prior(
        simple_payload,
        exact_prior={23: 1.0, 10: 0.2},
        region_prior={23: 0.9, 10: 0.1},
    )
    assert reranked["ordered_suggestion"][0] == 23
    assert reranked["components"][0]["number"] == 23
