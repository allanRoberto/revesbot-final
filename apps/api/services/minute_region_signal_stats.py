from __future__ import annotations

from typing import Any, Dict, Mapping


VALID_COVERAGE_MODES = {"up_to", "exact"}


def normalize_coverage_mode(value: str) -> str:
    mode = str(value or "up_to").strip().lower()
    return mode if mode in VALID_COVERAGE_MODES else "up_to"


def effective_coverage(
    signal: Mapping[str, Any],
    *,
    include_alternative: bool,
) -> int:
    official_values = {
        int(item)
        for item in signal.get("bet_values", [])
        if item is not None
    }
    considered_values = set(official_values)
    if include_alternative:
        alternative_analysis = signal.get("alternative_analysis") or {}
        considered_values.update(
            int(item)
            for item in alternative_analysis.get(
                "alternative_bet_values", []
            )
            if item is not None
        )
    if considered_values:
        return len(considered_values)
    return max(0, int(signal.get("coverage", 0) or 0))


def effective_coverage_expression(*, include_alternative: bool) -> Dict[str, Any]:
    value_sets: list[Any] = [
        {"$ifNull": ["$bet_values", []]},
        [],
    ]
    if include_alternative:
        value_sets.append(
            {
                "$ifNull": [
                    "$alternative_analysis.alternative_bet_values",
                    [],
                ]
            }
        )
    return {
        "$max": [
            {"$size": {"$setUnion": value_sets}},
            {"$ifNull": ["$coverage", 0]},
        ]
    }


def build_coverage_stages(
    *,
    include_alternative: bool,
    coverage: int | None,
    coverage_mode: str,
) -> list[Dict[str, Any]]:
    stages: list[Dict[str, Any]] = [
        {
            "$addFields": {
                "effective_coverage": effective_coverage_expression(
                    include_alternative=include_alternative
                )
            }
        }
    ]
    if coverage is not None:
        mode = normalize_coverage_mode(coverage_mode)
        coverage_match: Any = (
            int(coverage) if mode == "exact" else {"$lte": int(coverage)}
        )
        stages.append({"$match": {"effective_coverage": coverage_match}})
    return stages


def build_available_coverages_pipeline(
    match_query: Mapping[str, Any],
    *,
    include_alternative: bool,
) -> list[Dict[str, Any]]:
    return [
        {"$match": dict(match_query)},
        *build_coverage_stages(
            include_alternative=include_alternative,
            coverage=None,
            coverage_mode="exact",
        ),
        {"$group": {"_id": "$effective_coverage"}},
        {"$sort": {"_id": 1}},
    ]


def considered_hit_condition(*, include_alternative: bool) -> Dict[str, Any]:
    official_hit: Dict[str, Any] = {"$eq": ["$$attempt.is_payment", True]}
    if not include_alternative:
        return official_hit
    return {
        "$or": [
            official_hit,
            {"$eq": ["$$attempt.is_alternative_payment", True]},
        ]
    }


def hit_count_expression(
    *,
    attempt_horizon: int,
    include_alternative: bool,
) -> Dict[str, Any]:
    horizon = max(1, min(10, int(attempt_horizon)))
    return {
        "$size": {
            "$filter": {
                "input": {
                    "$slice": [
                        {"$ifNull": ["$attempts", []]},
                        horizon,
                    ]
                },
                "as": "attempt",
                "cond": considered_hit_condition(
                    include_alternative=include_alternative
                ),
            }
        }
    }


def build_signal_list_pipeline(
    match_query: Mapping[str, Any],
    *,
    include_alternative: bool,
    coverage: int | None,
    coverage_mode: str,
    attempt_horizon: int,
    hit_count: int | None,
    limit: int,
) -> list[Dict[str, Any]]:
    horizon = max(1, min(10, int(attempt_horizon)))
    pipeline: list[Dict[str, Any]] = [
        {"$match": dict(match_query)},
        *build_coverage_stages(
            include_alternative=include_alternative,
            coverage=coverage,
            coverage_mode=coverage_mode,
        ),
        {
            "$addFields": {
                "evaluated_hit_count": hit_count_expression(
                    attempt_horizon=horizon,
                    include_alternative=include_alternative,
                )
            }
        },
    ]
    if hit_count is not None:
        pipeline.append(
            {
                "$match": {
                    "attempt_count": {"$gte": horizon},
                    "evaluated_hit_count": int(hit_count),
                }
            }
        )
    pipeline.append(
        {
            "$facet": {
                "items": [
                    {"$sort": {"signal_minute_utc": -1}},
                    {"$limit": int(limit)},
                ],
                "total": [{"$count": "value"}],
            }
        }
    )
    return pipeline


def evaluate_signal(
    signal: Mapping[str, Any],
    *,
    attempt_horizon: int,
    include_alternative: bool,
) -> Dict[str, Any]:
    horizon = max(1, min(10, int(attempt_horizon)))
    attempt_count = int(signal.get("attempt_count", 0) or 0)
    eligible = attempt_count >= horizon
    attempts = list(signal.get("attempts", []))[:horizon]

    official_hit_attempt = next(
        (int(item.get("attempt_number", index)) for index, item in enumerate(attempts, 1) if item.get("is_payment")),
        None,
    )
    alternative_hit_attempt = next(
        (
            int(item.get("attempt_number", index))
            for index, item in enumerate(attempts, 1)
            if item.get("is_alternative_payment")
        ),
        None,
    )
    considered_attempts = [official_hit_attempt]
    if include_alternative:
        considered_attempts.append(alternative_hit_attempt)
    valid_hits = [item for item in considered_attempts if item is not None]
    hit = bool(valid_hits) if eligible else None
    hit_count = sum(
        1
        for item in attempts
        if item.get("is_payment")
        or (include_alternative and item.get("is_alternative_payment"))
    )

    return {
        "eligible": eligible,
        "attempt_horizon": horizon,
        "include_alternative": bool(include_alternative),
        "outcome": "hit" if hit is True else "miss" if hit is False else "pending",
        "hit": hit,
        "first_hit_attempt": min(valid_hits) if eligible and valid_hits else None,
        "hit_count": hit_count if eligible else None,
        "official_hit": official_hit_attempt is not None if eligible else None,
        "official_first_hit_attempt": official_hit_attempt if eligible else None,
        "alternative_hit": alternative_hit_attempt is not None if eligible else None,
        "alternative_first_hit_attempt": alternative_hit_attempt if eligible else None,
        "effective_coverage": effective_coverage(
            signal,
            include_alternative=include_alternative,
        ),
    }


def build_attempt_accuracy_rows(
    accuracy_doc: Mapping[str, Any],
    *,
    attempt_horizon: int,
) -> list[Dict[str, Any]]:
    horizon = max(1, min(10, int(attempt_horizon)))
    evaluated = max(0, int(accuracy_doc.get("evaluated", 0) or 0))
    cumulative_hits = 0
    rows: list[Dict[str, Any]] = []
    for attempt in range(1, horizon + 1):
        hits = max(0, int(accuracy_doc.get(f"attempt_{attempt}_hits", 0) or 0))
        cumulative_hits += hits
        rows.append(
            {
                "attempt": attempt,
                "hits": hits,
                "accuracy": round((hits / evaluated) * 100, 2) if evaluated else 0.0,
                "cumulative_hits": cumulative_hits,
                "cumulative_accuracy": round(
                    (cumulative_hits / evaluated) * 100,
                    2,
                )
                if evaluated
                else 0.0,
            }
        )
    return rows


def build_hit_count_rows(
    accuracy_doc: Mapping[str, Any],
    *,
    attempt_horizon: int,
) -> list[Dict[str, Any]]:
    horizon = max(1, min(10, int(attempt_horizon)))
    evaluated = max(0, int(accuracy_doc.get("evaluated", 0) or 0))
    exact_counts = [
        max(0, int(accuracy_doc.get(f"hit_count_{count}_signals", 0) or 0))
        for count in range(0, horizon + 1)
    ]
    rows: list[Dict[str, Any]] = []
    for hit_count, signals in enumerate(exact_counts):
        at_least_signals = sum(exact_counts[hit_count:])
        rows.append(
            {
                "hit_count": hit_count,
                "signals": signals,
                "percentage": round((signals / evaluated) * 100, 2)
                if evaluated
                else 0.0,
                "at_least_signals": at_least_signals,
                "at_least_percentage": round(
                    (at_least_signals / evaluated) * 100,
                    2,
                )
                if evaluated
                else 0.0,
            }
        )
    return rows


def build_accuracy_pipeline(
    match_query: Mapping[str, Any],
    *,
    attempt_horizon: int,
    include_alternative: bool,
    coverage: int | None = None,
    coverage_mode: str = "up_to",
    group_by_coverage: bool = False,
) -> list[Dict[str, Any]]:
    horizon = max(1, min(10, int(attempt_horizon)))
    query = dict(match_query)
    query["attempt_count"] = {"$gte": horizon}

    considered_hit = considered_hit_condition(
        include_alternative=include_alternative
    )

    considered_attempts_expression = {
        "$filter": {
            "input": {
                "$slice": [
                    {"$ifNull": ["$attempts", []]},
                    horizon,
                ]
            },
            "as": "attempt",
            "cond": considered_hit,
        }
    }
    hit_expression = {
        "$gt": [
            {"$size": considered_attempts_expression},
            0,
        ]
    }
    first_hit_attempt_expression = {
        "$let": {
            "vars": {"hit_attempts": considered_attempts_expression},
            "in": {
                "$ifNull": [
                    {
                        "$arrayElemAt": [
                            {
                                "$map": {
                                    "input": "$$hit_attempts",
                                    "as": "hit_attempt",
                                    "in": "$$hit_attempt.attempt_number",
                                }
                            },
                            0,
                        ]
                    },
                    None,
                ]
            },
        }
    }
    group_id: Any = "$effective_coverage" if group_by_coverage else None
    group_fields: Dict[str, Any] = {
        "_id": group_id,
        "evaluated": {"$sum": 1},
        "hits": {"$sum": {"$cond": ["$hit", 1, 0]}},
    }
    if not group_by_coverage:
        for attempt in range(1, horizon + 1):
            group_fields[f"attempt_{attempt}_hits"] = {
                "$sum": {
                    "$cond": [
                        {"$eq": ["$first_hit_attempt", attempt]},
                        1,
                        0,
                    ]
                }
            }
        for hit_count in range(0, horizon + 1):
            group_fields[f"hit_count_{hit_count}_signals"] = {
                "$sum": {
                    "$cond": [
                        {"$eq": ["$evaluated_hit_count", hit_count]},
                        1,
                        0,
                    ]
                }
            }
    pipeline: list[Dict[str, Any]] = [
        {"$match": query},
        *build_coverage_stages(
            include_alternative=include_alternative,
            coverage=coverage,
            coverage_mode=coverage_mode,
        ),
        {
            "$project": {
                "effective_coverage": 1,
                "hit": hit_expression,
                "first_hit_attempt": first_hit_attempt_expression,
                "evaluated_hit_count": hit_count_expression(
                    attempt_horizon=horizon,
                    include_alternative=include_alternative,
                ),
            }
        },
        {"$group": group_fields},
    ]
    if group_by_coverage:
        pipeline.append({"$sort": {"_id": 1}})
    return pipeline
