from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from math import exp
from typing import Any, Dict, Iterable, List, Mapping
from zoneinfo import ZoneInfo

from api.services.base_suggestion import WHEEL_ORDER


BR_TZ = ZoneInfo("America/Sao_Paulo")
UTC = timezone.utc
WHEEL_INDEX = {number: index for index, number in enumerate(WHEEL_ORDER)}


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def to_br(value: datetime) -> datetime:
    return ensure_utc(value).astimezone(BR_TZ)


def build_reference_time(reference_time: str | None = None) -> datetime:
    now_br = datetime.now(BR_TZ).replace(second=0, microsecond=0)
    if not reference_time:
        return now_br
    hour_text, minute_text = reference_time.strip().split(":", 1)
    return now_br.replace(hour=int(hour_text), minute=int(minute_text), second=0, microsecond=0)


def build_daily_window_bounds(reference_dt_br: datetime, *, minute_span: int = 2) -> tuple[datetime, datetime]:
    safe_span = max(0, int(minute_span))
    center = reference_dt_br.replace(second=0, microsecond=0)
    start_br = center - timedelta(minutes=safe_span)
    end_br = center + timedelta(minutes=safe_span + 1)
    return start_br, end_br


def get_region_numbers(number: int, span: int = 2) -> List[int]:
    if number not in WHEEL_INDEX:
        return [number]
    index = WHEEL_INDEX[number]
    safe_span = max(0, int(span))
    return [
        WHEEL_ORDER[(index + offset) % len(WHEEL_ORDER)]
        for offset in range(-safe_span, safe_span + 1)
    ]


def recency_weight(days_ago: int, lookback_days: int) -> float:
    safe_lookback = max(1, int(lookback_days))
    half_life = max(7.0, safe_lookback / 3.0)
    return exp(-(max(0, int(days_ago)) / half_life))


def normalize_score_map(raw_scores: Mapping[int, float]) -> Dict[int, float]:
    cleaned = {int(number): float(score) for number, score in dict(raw_scores).items() if float(score) > 0.0}
    if not cleaned:
        return {}
    max_score = max(cleaned.values())
    if max_score <= 0.0:
        return {}
    return {number: round(score / max_score, 6) for number, score in cleaned.items()}


def compute_time_window_priors(
    docs_by_day: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    lookback_days: int,
    region_span: int = 2,
) -> Dict[str, Any]:
    exact_raw: Dict[int, float] = defaultdict(float)
    region_raw: Dict[int, float] = defaultdict(float)
    day_presence_raw: Dict[int, float] = defaultdict(float)
    daily_spin_count = Counter()
    total_spins = 0

    ordered_days = sorted(docs_by_day.keys(), reverse=True)
    for days_ago, day_key in enumerate(ordered_days, start=1):
        docs = [
            dict(item)
            for item in docs_by_day.get(day_key, [])
            if isinstance(item, Mapping) and item.get("value") is not None
        ]
        if not docs:
            continue
        weight = recency_weight(days_ago, lookback_days)
        seen_today = set()
        for doc in docs:
            try:
                number = int(doc.get("value"))
            except (TypeError, ValueError):
                continue
            if not (0 <= number <= 36):
                continue
            total_spins += 1
            daily_spin_count[day_key] += 1
            exact_raw[number] += weight
            seen_today.add(number)
            for region_number in get_region_numbers(number, span=region_span):
                region_raw[int(region_number)] += weight
        for number in seen_today:
            day_presence_raw[int(number)] += weight

    exact_prior = normalize_score_map(exact_raw)
    region_prior = normalize_score_map(region_raw)
    day_presence_prior = normalize_score_map(day_presence_raw)

    top_exact = [
        {"number": number, "score": score}
        for number, score in sorted(exact_prior.items(), key=lambda item: (-item[1], item[0]))[:12]
    ]
    top_region = [
        {"number": number, "score": score}
        for number, score in sorted(region_prior.items(), key=lambda item: (-item[1], item[0]))[:12]
    ]
    return {
        "lookback_days": int(lookback_days),
        "days_with_data": int(sum(1 for docs in docs_by_day.values() if list(docs))),
        "total_spins": int(total_spins),
        "avg_spins_per_day": round(total_spins / max(1, sum(1 for docs in docs_by_day.values() if list(docs))), 4),
        "exact_prior": exact_prior,
        "region_prior": region_prior,
        "day_presence_prior": day_presence_prior,
        "top_exact": top_exact,
        "top_region": top_region,
    }


def _extract_selected_number_details(simple_payload: Mapping[str, Any]) -> List[Dict[str, Any]]:
    raw_details = simple_payload.get("selected_number_details")
    if isinstance(raw_details, list) and raw_details:
        return [dict(item) for item in raw_details if isinstance(item, Mapping)]
    raw_number_details = simple_payload.get("number_details")
    if isinstance(raw_number_details, list):
        return [dict(item) for item in raw_number_details if isinstance(item, Mapping)]
    return []


def rerank_with_time_window_prior(
    simple_payload: Mapping[str, Any],
    *,
    exact_prior: Mapping[int, float],
    region_prior: Mapping[int, float],
    current_weight: float = 0.75,
    exact_weight: float = 0.10,
    region_weight: float = 0.15,
) -> Dict[str, Any]:
    ordered_suggestion = [
        int(value)
        for value in (
            simple_payload.get("ordered_suggestion")
            or simple_payload.get("suggestion")
            or simple_payload.get("list")
            or []
        )
        if isinstance(value, (int, float, str))
    ]
    if not ordered_suggestion:
        return {
            "available": False,
            "ordered_suggestion": [],
            "components": [],
            "weights": {
                "current_weight": float(current_weight),
                "exact_weight": float(exact_weight),
                "region_weight": float(region_weight),
            },
        }

    details = _extract_selected_number_details(simple_payload)
    detail_map = {
        int(item.get("number")): dict(item)
        for item in details
        if str(item.get("number", "")).strip()
    }

    current_raw: Dict[int, float] = {}
    suggestion_size = len(ordered_suggestion)
    for index, number in enumerate(ordered_suggestion):
        detail = detail_map.get(number, {})
        score = float(detail.get("weighted_support_score") or detail.get("support_score") or 0.0)
        if score <= 0.0:
            score = max(0.0, 1.0 - (index / max(1, suggestion_size - 1)))
        current_raw[number] = score

    current_prior = normalize_score_map(current_raw)
    normalized_exact = {int(number): float(score) for number, score in dict(exact_prior).items()}
    normalized_region = {int(number): float(score) for number, score in dict(region_prior).items()}
    original_positions = {number: index for index, number in enumerate(ordered_suggestion)}

    components: List[Dict[str, Any]] = []
    for number in ordered_suggestion:
        current_score = float(current_prior.get(number, 0.0))
        exact_score = float(normalized_exact.get(number, 0.0))
        region_score = float(normalized_region.get(number, 0.0))
        final_score = (
            (float(current_weight) * current_score)
            + (float(exact_weight) * exact_score)
            + (float(region_weight) * region_score)
        )
        components.append(
            {
                "number": int(number),
                "current_score": round(current_score, 6),
                "exact_prior": round(exact_score, 6),
                "region_prior": round(region_score, 6),
                "final_score": round(final_score, 6),
                "original_position": int(original_positions[number] + 1),
            }
        )

    components.sort(
        key=lambda item: (
            -float(item["final_score"]),
            -float(item["current_score"]),
            -float(item["region_prior"]),
            int(item["original_position"]),
        )
    )
    reordered = [int(item["number"]) for item in components]
    return {
        "available": True,
        "ordered_suggestion": reordered,
        "components": components,
        "weights": {
            "current_weight": float(current_weight),
            "exact_weight": float(exact_weight),
            "region_weight": float(region_weight),
        },
    }
