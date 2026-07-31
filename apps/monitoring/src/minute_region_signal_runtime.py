from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Sequence


WHEEL_ORDER = (
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23,
    10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26,
)
WHEEL_INDEX = {value: index for index, value in enumerate(WHEEL_ORDER)}
RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}


def number_color(value: int) -> str:
    if int(value) == 0:
        return "green"
    return "red" if int(value) in RED_NUMBERS else "black"


def serialize_number(value: int) -> Dict[str, Any]:
    safe_value = int(value)
    return {"value": safe_value, "color": number_color(safe_value)}


def region_numbers(center: int, neighbors_side: int) -> List[int]:
    safe_center = int(center)
    safe_span = max(0, min(18, int(neighbors_side)))
    center_index = WHEEL_INDEX[safe_center]
    wheel_size = len(WHEEL_ORDER)
    return [
        int(WHEEL_ORDER[(center_index + offset) % wheel_size])
        for offset in range(-safe_span, safe_span + 1)
    ]


def rank_centers(
    training_days_source: Sequence[Mapping[str, Any]],
    *,
    analysis_neighbors: int,
) -> List[Dict[str, Any]]:
    total_days = len(training_days_source)
    rankings: List[Dict[str, Any]] = []

    for center in range(37):
        region = set(region_numbers(center, analysis_neighbors))
        hit_days = 0
        total_matches = 0
        day_matches = []

        for day in training_days_source:
            matches = [
                item
                for item in day.get("items", [])
                if int(item.get("value", -1)) in region
            ]
            if matches:
                hit_days += 1
                total_matches += len(matches)
                day_matches.append(
                    {
                        "day_offset": int(day.get("day_offset", 0)),
                        "match_count": len(matches),
                    }
                )

        rankings.append(
            {
                "center": center,
                "hit_days": hit_days,
                "total_days": total_days,
                "hit_rate": round(hit_days / max(1, total_days), 4),
                "total_matches": total_matches,
                "day_matches": day_matches,
            }
        )

    rankings.sort(
        key=lambda item: (
            -int(item["hit_days"]),
            -int(item["total_matches"]),
            int(item["center"]),
        )
    )
    return rankings


def _ordered_region_values(centers: Iterable[int], neighbors_side: int) -> List[int]:
    values = set()
    for center in centers:
        values.update(region_numbers(int(center), neighbors_side))
    return [value for value in WHEEL_ORDER if value in values]


def wheel_distance(first: int, second: int) -> int:
    direct = abs(WHEEL_INDEX[int(first)] - WHEEL_INDEX[int(second)])
    return min(direct, len(WHEEL_ORDER) - direct)


def _ranking_payload(item: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        **serialize_number(int(item["center"])),
        "hit_days": int(item["hit_days"]),
        "total_days": int(item["total_days"]),
        "hit_rate": float(item["hit_rate"]),
        "total_matches": int(item["total_matches"]),
    }


def build_alternative_analysis(
    rankings: Sequence[Mapping[str, Any]],
    selected_rankings: Sequence[Mapping[str, Any]],
    *,
    bet_neighbors: int,
) -> Dict[str, Any]:
    if len(selected_rankings) < 2:
        return {"triggered": False, "reason": "O sinal possui menos de dois centros."}

    primary = selected_rankings[0]
    primary_value = int(primary["center"])
    primary_region = set(region_numbers(primary_value, bet_neighbors))
    close_rankings = [
        item
        for item in selected_rankings[1:]
        if primary_region.intersection(region_numbers(int(item["center"]), bet_neighbors))
    ]
    if not close_rankings:
        return {
            "triggered": False,
            "reason": "As regiões dos centros oficiais não se sobrepõem.",
        }

    selected_values = {int(item["center"]) for item in selected_rankings}
    alternative = next(
        (
            item
            for item in rankings
            if int(item["center"]) not in selected_values
            and primary_region.isdisjoint(
                region_numbers(int(item["center"]), bet_neighbors)
            )
        ),
        None,
    )
    close_payload = [
        {
            **_ranking_payload(item),
            "wheel_distance_from_primary": wheel_distance(
                primary_value, int(item["center"])
            ),
        }
        for item in close_rankings
    ]
    if alternative is None:
        return {
            "triggered": True,
            "reason": "Não existe uma região totalmente afastada com a configuração atual.",
            "primary_center": _ranking_payload(primary),
            "close_centers": close_payload,
            "alternative_center": None,
            "alternative_bet_numbers": [],
            "alternative_bet_values": [],
            "alternative_coverage": 0,
        }

    alternative_value = int(alternative["center"])
    alternative_values = region_numbers(alternative_value, bet_neighbors)
    return {
        "triggered": True,
        "reason": "As regiões oficiais se sobrepõem; alternativa apenas informativa.",
        "primary_center": _ranking_payload(primary),
        "close_centers": close_payload,
        "alternative_center": {
            **_ranking_payload(alternative),
            "wheel_distance_from_primary": wheel_distance(
                primary_value, alternative_value
            ),
        },
        "alternative_bet_numbers": [
            serialize_number(value) for value in alternative_values
        ],
        "alternative_bet_values": alternative_values,
        "alternative_coverage": len(alternative_values),
    }


def build_signal_document(
    *,
    roulette_id: str,
    signal_key: str,
    signal_minute_utc: datetime,
    signal_minute_br: datetime,
    generated_at_utc: datetime,
    training_days_source: Sequence[Mapping[str, Any]],
    previous_results: Sequence[Mapping[str, Any]],
    training_days: int,
    window_minutes: int,
    analysis_neighbors: int,
    centers_count: int,
    bet_neighbors: int,
    max_attempts: int,
    previous_results_count: int,
) -> Dict[str, Any]:
    rankings = rank_centers(
        training_days_source,
        analysis_neighbors=analysis_neighbors,
    )
    selected_rankings = rankings[: max(1, min(37, int(centers_count)))]
    selected_center_values = [int(item["center"]) for item in selected_rankings]
    bet_values = _ordered_region_values(selected_center_values, bet_neighbors)
    bet_value_set = set(bet_values)
    alternative_analysis = build_alternative_analysis(
        rankings,
        selected_rankings,
        bet_neighbors=bet_neighbors,
    )

    serialized_previous = [dict(item) for item in previous_results]
    previous_region_matches = [
        item for item in serialized_previous if int(item.get("value", -1)) in bet_value_set
    ]

    return {
        "roulette_id": str(roulette_id),
        "signal_key": str(signal_key),
        "signal_minute_utc": signal_minute_utc,
        "signal_minute_br": signal_minute_br,
        "generated_at_utc": generated_at_utc,
        "config": {
            "training_days": int(training_days),
            "window_minutes": int(window_minutes),
            "analysis_neighbors": int(analysis_neighbors),
            "centers_count": int(centers_count),
            "bet_neighbors": int(bet_neighbors),
            "max_attempts": int(max_attempts),
            "previous_results_count": int(previous_results_count),
        },
        "training_days_found": len(training_days_source),
        "selected_centers": [_ranking_payload(item) for item in selected_rankings],
        "bet_numbers": [serialize_number(value) for value in bet_values],
        "bet_values": bet_values,
        "coverage": len(bet_values),
        "previous_results": serialized_previous,
        "previous_region_matches": previous_region_matches,
        "previous_region_hit": bool(previous_region_matches),
        "previous_region_hit_count": len(previous_region_matches),
        "alternative_analysis": alternative_analysis,
        "alternative_payment_count": 0,
        "alternative_hit": False,
        "status": "active",
        "attempt_count": 0,
        "payment_count": 0,
        "attempts": [],
        "completed_at_utc": None,
        "updated_at_utc": generated_at_utc,
    }


def build_attempt(
    signal: Mapping[str, Any],
    history_result: Mapping[str, Any],
) -> Dict[str, Any]:
    attempt_number = int(signal.get("attempt_count", 0)) + 1
    value = int(history_result["value"])
    alternative_values = {
        int(item)
        for item in signal.get("alternative_analysis", {}).get(
            "alternative_bet_values", []
        )
    }
    return {
        "attempt_number": attempt_number,
        "result_history_id": str(history_result["history_id"]),
        "value": value,
        "color": number_color(value),
        "timestamp_utc": history_result["timestamp_utc"],
        "timestamp_br": history_result["timestamp_br"],
        "formatted": str(history_result["formatted"]),
        "is_payment": value in {int(item) for item in signal.get("bet_values", [])},
        "is_alternative_payment": value in alternative_values,
    }


def apply_result_to_signal(
    signal: Mapping[str, Any],
    history_result: Mapping[str, Any],
    *,
    now_utc: datetime | None = None,
) -> Dict[str, Any]:
    current = dict(signal)
    attempts = [dict(item) for item in current.get("attempts", [])]
    history_id = str(history_result["history_id"])
    if current.get("status") != "active":
        return current
    if any(str(item.get("result_history_id")) == history_id for item in attempts):
        return current

    max_attempts = max(1, int(current.get("config", {}).get("max_attempts", 10)))
    if len(attempts) >= max_attempts:
        current["status"] = "completed"
        return current

    current["attempt_count"] = len(attempts)
    attempt = build_attempt(current, history_result)
    attempts.append(attempt)
    completed = len(attempts) >= max_attempts
    updated_at = now_utc or datetime.now(timezone.utc)

    current["attempts"] = attempts
    current["attempt_count"] = len(attempts)
    current["payment_count"] = sum(1 for item in attempts if item.get("is_payment"))
    current["alternative_payment_count"] = sum(
        1 for item in attempts if item.get("is_alternative_payment")
    )
    current["alternative_hit"] = current["alternative_payment_count"] > 0
    current["status"] = "completed" if completed else "active"
    current["completed_at_utc"] = updated_at if completed else None
    current["updated_at_utc"] = updated_at
    return current
