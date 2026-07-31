from __future__ import annotations

from typing import Any, Dict, List

from api.services.base_suggestion import WHEEL_INDEX, WHEEL_ORDER


RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}


def _number_color(value: int) -> str:
    if value == 0:
        return "green"
    return "red" if value in RED_NUMBERS else "black"


def _serialize_number(value: int) -> Dict[str, Any]:
    return {"value": int(value), "color": _number_color(int(value))}


def _region_numbers(center: int, neighbors_side: int) -> List[int]:
    center_index = WHEEL_INDEX[int(center)]
    wheel_size = len(WHEEL_ORDER)
    safe_span = max(0, int(neighbors_side))
    return [
        int(WHEEL_ORDER[(center_index + offset) % wheel_size])
        for offset in range(-safe_span, safe_span + 1)
    ]


def _max_loss_streak(days: List[Dict[str, Any]]) -> int:
    current = 0
    maximum = 0
    for day in days:
        if day["status"] == "miss":
            current += 1
            maximum = max(maximum, current)
        elif day["status"] == "hit":
            current = 0
    return maximum


def build_walk_forward_backtest(
    days_by_offset: Dict[int, Dict[str, Any]],
    *,
    training_days: int,
    test_days: int,
    analysis_neighbors: int,
    bet_neighbors: int,
    centers_count: int,
    attempts_limit: int,
) -> Dict[str, Any]:
    analysis_regions = {
        center: set(_region_numbers(center, analysis_neighbors))
        for center in range(37)
    }
    bet_regions = {
        center: set(_region_numbers(center, bet_neighbors))
        for center in range(37)
    }

    evaluated_days = []
    total_profit = 0.0
    total_staked = 0.0
    baseline_probabilities = []
    coverage_values = []
    hits_by_attempt = {attempt: 0 for attempt in range(1, attempts_limit + 1)}

    # Do mais antigo ao mais recente para preservar a ordem real do walk-forward.
    for test_offset in range(test_days, 0, -1):
        training_offsets = list(
            range(test_offset + 1, test_offset + training_days + 1)
        )
        rankings = []

        for center in range(37):
            region = analysis_regions[center]
            hit_days = 0
            total_matches = 0

            for training_offset in training_offsets:
                items = days_by_offset[training_offset]["training_items"]
                matches = [item for item in items if int(item["value"]) in region]
                if matches:
                    hit_days += 1
                    total_matches += len(matches)

            rankings.append(
                {
                    "center": center,
                    "hit_days": hit_days,
                    "total_matches": total_matches,
                    "hit_rate": round(hit_days / max(1, training_days), 4),
                }
            )

        rankings.sort(
            key=lambda item: (
                -item["hit_days"],
                -item["total_matches"],
                item["center"],
            )
        )
        selected = rankings[:centers_count]
        selected_centers = [int(item["center"]) for item in selected]

        bet_number_set = set()
        for center in selected_centers:
            bet_number_set.update(bet_regions[center])
        bet_numbers = [
            int(value) for value in WHEEL_ORDER if int(value) in bet_number_set
        ]
        coverage = len(bet_numbers)

        test_day = days_by_offset[test_offset]
        observed_attempts = test_day["outcome_items"][:attempts_limit]
        hit_attempt = None
        for attempt_index, item in enumerate(observed_attempts, start=1):
            if int(item["value"]) in bet_number_set:
                hit_attempt = attempt_index
                break

        used_attempts_count = hit_attempt or len(observed_attempts)
        used_attempts = []
        for attempt_index, item in enumerate(
            observed_attempts[:used_attempts_count],
            start=1,
        ):
            used_attempts.append(
                {
                    **item,
                    "attempt": attempt_index,
                    "status": "hit" if attempt_index == hit_attempt else "miss",
                }
            )

        if not observed_attempts:
            status = "no_data"
            profit_units = 0.0
            staked_units = 0.0
            baseline_probability = None
        else:
            status = "hit" if hit_attempt else "miss"
            losing_attempts = (hit_attempt - 1) if hit_attempt else len(observed_attempts)
            profit_units = float(-coverage * losing_attempts)
            if hit_attempt:
                profit_units += float(36 - coverage)
                hits_by_attempt[hit_attempt] += 1

            staked_units = float(coverage * used_attempts_count)
            baseline_probability = 1 - ((37 - coverage) / 37) ** len(observed_attempts)
            baseline_probabilities.append(baseline_probability)
            coverage_values.append(coverage)
            total_profit += profit_units
            total_staked += staked_units

        nearest_training = days_by_offset[training_offsets[0]]["target"]
        oldest_training = days_by_offset[training_offsets[-1]]["target"]
        evaluated_days.append(
            {
                "day_offset": test_offset,
                "target": test_day["target"],
                "training_period": {
                    "start": oldest_training,
                    "end": nearest_training,
                    "days": training_days,
                },
                "selected_centers": [
                    {
                        **_serialize_number(item["center"]),
                        "hit_days": item["hit_days"],
                        "hit_rate": item["hit_rate"],
                        "total_matches": item["total_matches"],
                    }
                    for item in selected
                ],
                "bet_numbers": [
                    _serialize_number(value) for value in bet_numbers
                ],
                "coverage": coverage,
                "status": status,
                "hit_attempt": hit_attempt,
                "available_attempts": len(observed_attempts),
                "attempts_used": used_attempts_count,
                "attempts": used_attempts,
                "profit_units": round(profit_units, 2),
                "staked_units": round(staked_units, 2),
                "baseline_probability": (
                    round(baseline_probability, 4)
                    if baseline_probability is not None
                    else None
                ),
            }
        )

    comparable_days = [
        day for day in evaluated_days if day["status"] in {"hit", "miss"}
    ]
    hits = sum(1 for day in comparable_days if day["status"] == "hit")
    misses = sum(1 for day in comparable_days if day["status"] == "miss")
    predictions = len(comparable_days)
    hit_rate = hits / predictions if predictions else 0.0
    baseline_hit_rate = (
        sum(baseline_probabilities) / len(baseline_probabilities)
        if baseline_probabilities
        else 0.0
    )
    lift = hit_rate / baseline_hit_rate if baseline_hit_rate else 0.0
    roi = total_profit / total_staked if total_staked else 0.0

    return {
        "metrics": {
            "requested_test_days": test_days,
            "predictions": predictions,
            "days_without_data": test_days - predictions,
            "hits": hits,
            "misses": misses,
            "hit_rate": round(hit_rate, 4),
            "baseline_hit_rate": round(baseline_hit_rate, 4),
            "lift": round(lift, 4),
            "average_coverage": round(
                sum(coverage_values) / len(coverage_values), 2
            )
            if coverage_values
            else 0.0,
            "min_coverage": min(coverage_values) if coverage_values else 0,
            "max_coverage": max(coverage_values) if coverage_values else 0,
            "total_profit_units": round(total_profit, 2),
            "total_staked_units": round(total_staked, 2),
            "roi": round(roi, 4),
            "max_loss_streak": _max_loss_streak(comparable_days),
            "hits_by_attempt": [
                {"attempt": attempt, "hits": hits_by_attempt[attempt]}
                for attempt in range(1, attempts_limit + 1)
            ],
        },
        "days": list(reversed(evaluated_days)),
    }
