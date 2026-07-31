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


def build_live_signal(
    training_days_source: List[Dict[str, Any]],
    recent_items: List[Dict[str, Any]],
    *,
    training_days: int,
    analysis_neighbors: int,
    bet_neighbors: int,
    centers_count: int,
    blocking_minutes: int,
    stale_after_minutes: int,
) -> Dict[str, Any]:
    rankings = []
    for center in range(37):
        region = set(_region_numbers(center, analysis_neighbors))
        hit_days = 0
        total_matches = 0

        for day in training_days_source:
            matches = [
                item for item in day["items"] if int(item["value"]) in region
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
        bet_number_set.update(
            _region_numbers(int(selected_center["center"]), bet_neighbors)
        )
    bet_numbers = [
        int(value) for value in WHEEL_ORDER if int(value) in bet_number_set
    ]

    ordered_recent_items = sorted(
        recent_items,
        key=lambda item: int(item.get("diff_seconds", 0)),
        reverse=True,
    )
    latest_result = ordered_recent_items[0] if ordered_recent_items else None
    latest_age_seconds = (
        abs(int(latest_result.get("diff_seconds", 0)))
        if latest_result is not None
        else None
    )
    feed_is_stale = (
        latest_result is None
        or latest_age_seconds is None
        or latest_age_seconds > stale_after_minutes * 60
    )

    blocking_seconds = blocking_minutes * 60
    blocking_items = [
        item
        for item in ordered_recent_items
        if -blocking_seconds <= int(item.get("diff_seconds", 0)) <= 0
    ]
    paid_matches = [
        item for item in blocking_items if int(item["value"]) in bet_number_set
    ]

    if feed_is_stale:
        status = "wait"
        reason = "Não há resultado recente suficiente para conferir o bloqueio com segurança."
    elif paid_matches:
        status = "cancel"
        most_recent_paid = paid_matches[0]
        reason = (
            f"O número {most_recent_paid['value']} da região prevista saiu "
            f"às {most_recent_paid['time']}."
        )
    else:
        status = "enter"
        reason = (
            f"Nenhum número da região prevista saiu nos últimos "
            f"{blocking_minutes} minuto(s)."
        )

    return {
        "status": status,
        "reason": reason,
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
        "coverage": len(bet_numbers),
        "paid_matches": paid_matches,
        "recent_items": ordered_recent_items,
        "latest_result": latest_result,
        "latest_age_seconds": latest_age_seconds,
        "feed_is_stale": feed_is_stale,
    }
