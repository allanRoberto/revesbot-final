from __future__ import annotations

from typing import Any, Dict, Mapping


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

    return {
        "eligible": eligible,
        "attempt_horizon": horizon,
        "include_alternative": bool(include_alternative),
        "outcome": "hit" if hit is True else "miss" if hit is False else "pending",
        "hit": hit,
        "first_hit_attempt": min(valid_hits) if eligible and valid_hits else None,
        "official_hit": official_hit_attempt is not None if eligible else None,
        "official_first_hit_attempt": official_hit_attempt if eligible else None,
        "alternative_hit": alternative_hit_attempt is not None if eligible else None,
        "alternative_first_hit_attempt": alternative_hit_attempt if eligible else None,
    }


def build_accuracy_pipeline(
    match_query: Mapping[str, Any],
    *,
    attempt_horizon: int,
    include_alternative: bool,
    group_by_coverage: bool = False,
) -> list[Dict[str, Any]]:
    horizon = max(1, min(10, int(attempt_horizon)))
    query = dict(match_query)
    query["attempt_count"] = {"$gte": horizon}

    official_hit = {"$eq": ["$$attempt.is_payment", True]}
    if include_alternative:
        considered_hit: Dict[str, Any] = {
            "$or": [
                official_hit,
                {"$eq": ["$$attempt.is_alternative_payment", True]},
            ]
        }
    else:
        considered_hit = official_hit

    hit_expression = {
        "$gt": [
            {
                "$size": {
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
            },
            0,
        ]
    }
    group_id: Any = "$coverage" if group_by_coverage else None
    pipeline: list[Dict[str, Any]] = [
        {"$match": query},
        {"$project": {"coverage": 1, "hit": hit_expression}},
        {
            "$group": {
                "_id": group_id,
                "evaluated": {"$sum": 1},
                "hits": {"$sum": {"$cond": ["$hit", 1, 0]}},
            }
        },
    ]
    if group_by_coverage:
        pipeline.append({"$sort": {"_id": 1}})
    return pipeline
