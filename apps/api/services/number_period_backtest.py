from __future__ import annotations

import math
from datetime import datetime, timedelta
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


def _format_timestamp(timestamp: datetime) -> str:
    return timestamp.strftime("%d/%m/%Y %H:%M")


def _format_timestamp_seconds(timestamp: datetime) -> str:
    return timestamp.strftime("%d/%m/%Y %H:%M:%S")


def _format_minute_diff(delta: timedelta) -> str:
    minutes = int(round(delta.total_seconds() / 60))
    sign = "+" if minutes > 0 else ""
    return f"{sign}{minutes} min"


def _prepare_items(
    days_source: Dict[int, List[Dict[str, Any]]],
) -> Dict[int, List[tuple[datetime, Dict[str, Any]]]]:
    prepared = {}
    for day_offset, items in days_source.items():
        prepared[int(day_offset)] = sorted(
            [
                (datetime.fromisoformat(str(item["timestamp"])), item)
                for item in items
            ],
            key=lambda pair: pair[0],
        )
    return prepared


def _max_loss_streak(entries: List[Dict[str, Any]]) -> int:
    current = 0
    maximum = 0
    for entry in entries:
        if entry["status"] == "miss":
            current += 1
            maximum = max(maximum, current)
        elif entry["status"] == "hit":
            current = 0
    return maximum


def build_intraday_backtest(
    days_source: Dict[int, List[Dict[str, Any]]],
    *,
    start_timestamp: datetime,
    period_minutes: int,
    training_days: int,
    window_minutes: int,
    analysis_neighbors: int,
    bet_neighbors: int,
    centers_count: int,
    attempts_limit: int,
    attempt_seconds: int = 40,
    outcome_horizon_minutes: int = 15,
) -> Dict[str, Any]:
    prepared_days = _prepare_items(days_source)
    analysis_regions = {
        center: set(_region_numbers(center, analysis_neighbors))
        for center in range(37)
    }
    bet_regions = {
        center: set(_region_numbers(center, bet_neighbors))
        for center in range(37)
    }

    timeline = []
    evaluated_entries = []
    blocked_until: datetime | None = None
    blocked_by: datetime | None = None
    total_profit = 0.0
    total_staked = 0.0
    baseline_probabilities = []
    coverage_values = []
    hits_by_attempt = {attempt: 0 for attempt in range(1, attempts_limit + 1)}
    window = timedelta(minutes=window_minutes)
    fixed_reservation = timedelta(seconds=attempts_limit * attempt_seconds)

    for minute_offset in range(period_minutes):
        slot_timestamp = start_timestamp + timedelta(minutes=minute_offset)
        if blocked_until is not None and slot_timestamp < blocked_until:
            timeline.append(
                {
                    "minute_offset": minute_offset,
                    "target": {
                        "timestamp": slot_timestamp.isoformat(),
                        "formatted": _format_timestamp(slot_timestamp),
                        "time": slot_timestamp.strftime("%H:%M"),
                    },
                    "status": "skipped_overlap",
                    "blocked_by": {
                        "timestamp": blocked_by.isoformat() if blocked_by else None,
                        "formatted": _format_timestamp(blocked_by) if blocked_by else None,
                        "time": blocked_by.strftime("%H:%M") if blocked_by else None,
                    },
                    "blocked_until": {
                        "timestamp": blocked_until.isoformat(),
                        "formatted": _format_timestamp_seconds(blocked_until),
                        "time": blocked_until.strftime("%H:%M:%S"),
                    },
                }
            )
            continue

        training_windows = []
        for training_offset in range(1, training_days + 1):
            training_target = slot_timestamp - timedelta(days=training_offset)
            training_windows.append(
                [
                    item
                    for item_timestamp, item in prepared_days[training_offset]
                    if abs(item_timestamp - training_target) <= window
                ]
            )

        rankings = []
        for center in range(37):
            region = analysis_regions[center]
            hit_days = 0
            total_matches = 0

            for training_items in training_windows:
                matches = [
                    item
                    for item in training_items
                    if int(item["value"]) in region
                ]
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

        bet_number_set = set()
        for selected_center in selected:
            bet_number_set.update(bet_regions[int(selected_center["center"])])
        bet_numbers = [
            int(value) for value in WHEEL_ORDER if int(value) in bet_number_set
        ]
        coverage = len(bet_numbers)

        horizon_end = slot_timestamp + timedelta(minutes=outcome_horizon_minutes)
        observed_attempt_pairs = [
            (item_timestamp, item)
            for item_timestamp, item in prepared_days[0]
            if slot_timestamp <= item_timestamp <= horizon_end
        ][:attempts_limit]

        reservation_until = slot_timestamp + fixed_reservation
        if observed_attempt_pairs:
            reservation_until = max(
                reservation_until,
                observed_attempt_pairs[-1][0],
            )
        blocked_until = reservation_until
        blocked_by = slot_timestamp

        hit_attempt = None
        for attempt_index, (_, item) in enumerate(observed_attempt_pairs, start=1):
            if int(item["value"]) in bet_number_set:
                hit_attempt = attempt_index
                break

        used_attempts_count = hit_attempt or len(observed_attempt_pairs)
        attempts = []
        for attempt_index, (item_timestamp, item) in enumerate(
            observed_attempt_pairs[:used_attempts_count],
            start=1,
        ):
            delta = item_timestamp - slot_timestamp
            attempts.append(
                {
                    **item,
                    "attempt": attempt_index,
                    "diff_seconds": int(delta.total_seconds()),
                    "diff_minutes": int(round(delta.total_seconds() / 60)),
                    "diff_label": _format_minute_diff(delta),
                    "status": "hit" if attempt_index == hit_attempt else "miss",
                }
            )

        if not observed_attempt_pairs:
            status = "no_data"
            profit_units = 0.0
            staked_units = 0.0
            baseline_probability = None
        else:
            status = "hit" if hit_attempt else "miss"
            losing_attempts = (
                (hit_attempt - 1) if hit_attempt else len(observed_attempt_pairs)
            )
            profit_units = float(-coverage * losing_attempts)
            if hit_attempt:
                profit_units += float(36 - coverage)
                hits_by_attempt[hit_attempt] += 1

            staked_units = float(coverage * used_attempts_count)
            baseline_probability = 1 - (
                ((37 - coverage) / 37) ** len(observed_attempt_pairs)
            )
            baseline_probabilities.append(baseline_probability)
            coverage_values.append(coverage)
            total_profit += profit_units
            total_staked += staked_units

        oldest_training = slot_timestamp - timedelta(days=training_days)
        nearest_training = slot_timestamp - timedelta(days=1)
        entry = {
            "minute_offset": minute_offset,
            "target": {
                "timestamp": slot_timestamp.isoformat(),
                "formatted": _format_timestamp(slot_timestamp),
                "time": slot_timestamp.strftime("%H:%M"),
            },
            "training_period": {
                "start": {
                    "timestamp": oldest_training.isoformat(),
                    "formatted": _format_timestamp(oldest_training),
                },
                "end": {
                    "timestamp": nearest_training.isoformat(),
                    "formatted": _format_timestamp(nearest_training),
                },
                "days": training_days,
            },
            "selected_centers": [
                {
                    **_serialize_number(int(item["center"])),
                    "hit_days": item["hit_days"],
                    "hit_rate": item["hit_rate"],
                    "total_matches": item["total_matches"],
                }
                for item in selected
            ],
            "bet_numbers": [_serialize_number(value) for value in bet_numbers],
            "coverage": coverage,
            "status": status,
            "hit_attempt": hit_attempt,
            "available_attempts": len(observed_attempt_pairs),
            "attempts_used": used_attempts_count,
            "attempts": attempts,
            "profit_units": round(profit_units, 2),
            "staked_units": round(staked_units, 2),
            "baseline_probability": (
                round(baseline_probability, 4)
                if baseline_probability is not None
                else None
            ),
            "reserved_until": {
                "timestamp": reservation_until.isoformat(),
                "formatted": _format_timestamp_seconds(reservation_until),
                "time": reservation_until.strftime("%H:%M:%S"),
            },
        }
        timeline.append(entry)
        evaluated_entries.append(entry)

    comparable_entries = [
        entry
        for entry in evaluated_entries
        if entry["status"] in {"hit", "miss"}
    ]
    hits = sum(1 for entry in comparable_entries if entry["status"] == "hit")
    misses = sum(1 for entry in comparable_entries if entry["status"] == "miss")
    predictions = len(comparable_entries)
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
            "candidate_minutes": period_minutes,
            "evaluated_entries": len(evaluated_entries),
            "predictions": predictions,
            "skipped_overlap": sum(
                1 for item in timeline if item["status"] == "skipped_overlap"
            ),
            "entries_without_data": sum(
                1 for item in evaluated_entries if item["status"] == "no_data"
            ),
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
            "max_loss_streak": _max_loss_streak(comparable_entries),
            "hits_by_attempt": [
                {"attempt": attempt, "hits": hits_by_attempt[attempt]}
                for attempt in range(1, attempts_limit + 1)
            ],
            "reserved_seconds_per_entry": attempts_limit * attempt_seconds,
            "minimum_spacing_minutes": math.ceil(
                (attempts_limit * attempt_seconds) / 60
            ),
        },
        "timeline": timeline,
    }
