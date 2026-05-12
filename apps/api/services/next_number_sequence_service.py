from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from api.core.db import (
    ensure_next_number_sequence_indexes,
    history_coll,
    next_number_sequences_coll,
)
from api.services.next_number_ranking_service import (
    DEFAULT_ROULETTE_ID,
    NUMBER_MAX,
    NUMBER_MIN,
)


SEQUENCE_DEPTH = 5
DEFAULT_POSITIONS_LIMIT = 5
DEFAULT_HOUR_START = 0
DEFAULT_HOUR_END = 23
DEFAULT_MODE = "both"
DEFAULT_TIME_WINDOW_ENABLED = False
DEFAULT_TIME_WINDOW_VALUE = 7
DEFAULT_TIME_WINDOW_UNIT = "days"
MAX_TIME_WINDOW_VALUE = 10000
MODE_SEPARATED = "separated"
MODE_SUMMED = "summed"
MODE_BOTH = "both"
MODES = {MODE_SEPARATED, MODE_SUMMED, MODE_BOTH}
TIME_WINDOW_UNIT_HOURS = "hours"
TIME_WINDOW_UNIT_DAYS = "days"
TIME_WINDOW_UNITS = {TIME_WINDOW_UNIT_HOURS, TIME_WINDOW_UNIT_DAYS}
SERVICE_VERSION = "next_number_sequences_v1"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_roulette_id(roulette_id: str | None) -> str:
    safe_roulette_id = str(roulette_id or "").strip()
    if not safe_roulette_id:
        raise ValueError("roulette_id e obrigatorio.")
    return safe_roulette_id


def _coerce_number(raw: Any) -> int:
    try:
        number = int(raw)
    except (TypeError, ValueError):
        raise ValueError("base_number deve ser um numero entre 0 e 36.") from None
    if number < NUMBER_MIN or number > NUMBER_MAX:
        raise ValueError("base_number deve ser um numero entre 0 e 36.")
    return number


def _clamp_int(raw: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _coerce_bool(raw: Any, default: bool = False) -> bool:
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "sim", "on"}:
        return True
    if value in {"0", "false", "no", "nao", "não", "off"}:
        return False
    return default


def _normalize_mode(mode: str | None) -> str:
    safe_mode = str(mode or DEFAULT_MODE).strip().lower()
    if safe_mode not in MODES:
        valid_modes = ", ".join(sorted(MODES))
        raise ValueError(f"Modo invalido: {safe_mode}. Use um destes: {valid_modes}.")
    return safe_mode


def _normalize_time_window_unit(unit: str | None) -> str:
    safe_unit = str(unit or DEFAULT_TIME_WINDOW_UNIT).strip().lower()
    if safe_unit not in TIME_WINDOW_UNITS:
        valid_units = ", ".join(sorted(TIME_WINDOW_UNITS))
        raise ValueError(f"Unidade de periodo invalida: {safe_unit}. Use uma destas: {valid_units}.")
    return safe_unit


def _percentage(count: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round((int(count) / int(denominator)) * 100.0, 4)


def _hour_match(hour_start: int, hour_end: int) -> Dict[str, Any]:
    if hour_start <= hour_end:
        return {"base_hour_br": {"$gte": hour_start, "$lte": hour_end}}
    return {
        "$or": [
            {"base_hour_br": {"$gte": hour_start}},
            {"base_hour_br": {"$lte": hour_end}},
        ]
    }


def _time_window_start(
    *,
    enabled: bool,
    value: int,
    unit: str,
    now_utc: datetime | None = None,
) -> datetime | None:
    if not enabled:
        return None
    reference = now_utc or _utc_now()
    if unit == TIME_WINDOW_UNIT_HOURS:
        return reference - timedelta(hours=value)
    return reference - timedelta(days=value)


def _base_match_filter(
    *,
    roulette_id: str,
    base_number: int,
    hour_start: int,
    hour_end: int,
    time_window_start_utc: datetime | None = None,
) -> Dict[str, Any]:
    match_filter: Dict[str, Any] = {
        "roulette_id": roulette_id,
        "base_number": base_number,
    }
    match_filter.update(_hour_match(hour_start, hour_end))
    if time_window_start_utc is not None:
        match_filter["base_timestamp_utc"] = {"$gte": time_window_start_utc}
    return match_filter


def _build_sequence_catalog_pipeline(
    *,
    roulette_id: str,
    updated_at_utc: datetime,
    source: str,
) -> List[Dict[str, Any]]:
    window_output: Dict[str, Any] = {}
    next_number_match: Dict[str, Any] = {}
    next_numbers: List[Dict[str, Any]] = []
    next_values: List[str] = []

    for position in range(1, SEQUENCE_DEPTH + 1):
        field = f"next_{position}"
        window_output[field] = {"$shift": {"output": "$value", "by": position}}
        next_number_match[field] = {"$gte": NUMBER_MIN, "$lte": NUMBER_MAX}
        next_numbers.append({"position": position, "number": f"${field}"})
        next_values.append(f"${field}")

    return [
        {
            "$match": {
                "roulette_id": roulette_id,
                "value": {"$gte": NUMBER_MIN, "$lte": NUMBER_MAX},
            }
        },
        {
            "$setWindowFields": {
                "sortBy": {"timestamp": 1, "_id": 1},
                "output": window_output,
            }
        },
        {"$match": next_number_match},
        {
            "$set": {
                "base_timestamp_date": {"$toDate": "$timestamp"},
            }
        },
        {
            "$project": {
                "_id": 0,
                "roulette_id": "$roulette_id",
                "base_history_id": {"$toString": "$_id"},
                "base_number": "$value",
                "base_timestamp_utc": "$base_timestamp_date",
                "base_hour_utc": {"$hour": {"date": "$base_timestamp_date", "timezone": "UTC"}},
                "base_hour_br": {
                    "$hour": {
                        "date": "$base_timestamp_date",
                        "timezone": "America/Sao_Paulo",
                    }
                },
                "base_minute_br": {
                    "$minute": {
                        "date": "$base_timestamp_date",
                        "timezone": "America/Sao_Paulo",
                    }
                },
                "base_second_br": {
                    "$second": {
                        "date": "$base_timestamp_date",
                        "timezone": "America/Sao_Paulo",
                    }
                },
                "base_date_br": {
                    "$dateToString": {
                        "format": "%Y-%m-%d",
                        "date": "$base_timestamp_date",
                        "timezone": "America/Sao_Paulo",
                    }
                },
                "base_time_br": {
                    "$dateToString": {
                        "format": "%H:%M:%S",
                        "date": "$base_timestamp_date",
                        "timezone": "America/Sao_Paulo",
                    }
                },
                "next_numbers": next_numbers,
                "next_values": next_values,
                "sequence_depth": {"$literal": SEQUENCE_DEPTH},
                "source": {"$literal": source},
                "version": {"$literal": SERVICE_VERSION},
                "updated_at_utc": {"$literal": updated_at_utc},
            }
        },
        {
            "$merge": {
                "into": "next_number_sequences",
                "on": ["roulette_id", "base_history_id"],
                "whenMatched": "replace",
                "whenNotMatched": "insert",
            }
        },
    ]


async def refresh_next_number_sequences(
    roulette_id: str = DEFAULT_ROULETTE_ID,
    *,
    source: str = "worker",
) -> Dict[str, Any]:
    safe_roulette_id = _coerce_roulette_id(roulette_id)
    updated_at_utc = _utc_now()
    await ensure_next_number_sequence_indexes()

    cursor = history_coll.aggregate(
        _build_sequence_catalog_pipeline(
            roulette_id=safe_roulette_id,
            updated_at_utc=updated_at_utc,
            source=source,
        ),
        allowDiskUse=True,
    )
    await cursor.to_list(length=None)

    catalog_count = await next_number_sequences_coll.count_documents(
        {"roulette_id": safe_roulette_id}
    )
    return {
        "roulette_id": safe_roulette_id,
        "source": source,
        "version": SERVICE_VERSION,
        "sequence_depth": SEQUENCE_DEPTH,
        "catalog_count": int(catalog_count),
        "updated_at_utc": updated_at_utc,
    }


async def get_next_number_sequence_rankings(
    roulette_id: str = DEFAULT_ROULETTE_ID,
    *,
    base_number: Any,
    positions_limit: int = DEFAULT_POSITIONS_LIMIT,
    hour_start: int = DEFAULT_HOUR_START,
    hour_end: int = DEFAULT_HOUR_END,
    mode: str = DEFAULT_MODE,
    preview_limit: int = 50,
    time_window_enabled: Any = DEFAULT_TIME_WINDOW_ENABLED,
    time_window_value: int = DEFAULT_TIME_WINDOW_VALUE,
    time_window_unit: str = DEFAULT_TIME_WINDOW_UNIT,
) -> Dict[str, Any]:
    safe_roulette_id = _coerce_roulette_id(roulette_id)
    safe_base_number = _coerce_number(base_number)
    safe_positions_limit = _clamp_int(positions_limit, DEFAULT_POSITIONS_LIMIT, 1, SEQUENCE_DEPTH)
    safe_hour_start = _clamp_int(hour_start, DEFAULT_HOUR_START, 0, 23)
    safe_hour_end = _clamp_int(hour_end, DEFAULT_HOUR_END, 0, 23)
    safe_preview_limit = _clamp_int(preview_limit, 50, 0, 200)
    safe_mode = _normalize_mode(mode)
    safe_time_window_enabled = _coerce_bool(time_window_enabled, DEFAULT_TIME_WINDOW_ENABLED)
    safe_time_window_value = _clamp_int(
        time_window_value,
        DEFAULT_TIME_WINDOW_VALUE,
        1,
        MAX_TIME_WINDOW_VALUE,
    )
    safe_time_window_unit = _normalize_time_window_unit(time_window_unit)
    time_window_start_utc = _time_window_start(
        enabled=safe_time_window_enabled,
        value=safe_time_window_value,
        unit=safe_time_window_unit,
    )

    await ensure_next_number_sequence_indexes()
    match_filter = _base_match_filter(
        roulette_id=safe_roulette_id,
        base_number=safe_base_number,
        hour_start=safe_hour_start,
        hour_end=safe_hour_end,
        time_window_start_utc=time_window_start_utc,
    )
    occurrences_total = await next_number_sequences_coll.count_documents(match_filter)

    separated_rankings: Dict[str, Any] = {}
    if safe_mode in {MODE_SEPARATED, MODE_BOTH}:
        for position in range(1, safe_positions_limit + 1):
            separated_rankings[str(position)] = {
                "position": position,
                "occurrences_total": int(occurrences_total),
                "ranking": [],
            }

        separated_pipeline = [
            {"$match": match_filter},
            {"$unwind": "$next_numbers"},
            {"$match": {"next_numbers.position": {"$lte": safe_positions_limit}}},
            {
                "$group": {
                    "_id": {
                        "position": "$next_numbers.position",
                        "number": "$next_numbers.number",
                    },
                    "count": {"$sum": 1},
                }
            },
            {"$sort": {"_id.position": 1, "count": -1, "_id.number": 1}},
        ]
        rows = await next_number_sequences_coll.aggregate(
            separated_pipeline,
            allowDiskUse=True,
        ).to_list(length=None)

        position_counters: Dict[int, int] = {}
        for row in rows:
            position = int((row.get("_id") or {}).get("position") or 0)
            number = int((row.get("_id") or {}).get("number") or 0)
            count = int(row.get("count") or 0)
            position_counters[position] = position_counters.get(position, 0) + 1
            separated_rankings[str(position)]["ranking"].append(
                {
                    "position": position_counters[position],
                    "number": number,
                    "count": count,
                    "percentage": _percentage(count, int(occurrences_total)),
                }
            )

    summed_ranking: Dict[str, Any] | None = None
    if safe_mode in {MODE_SUMMED, MODE_BOTH}:
        summed_pipeline = [
            {"$match": match_filter},
            {"$unwind": "$next_numbers"},
            {"$match": {"next_numbers.position": {"$lte": safe_positions_limit}}},
            {
                "$group": {
                    "_id": "$next_numbers.number",
                    "count": {"$sum": 1},
                }
            },
            {"$sort": {"count": -1, "_id": 1}},
        ]
        rows = await next_number_sequences_coll.aggregate(
            summed_pipeline,
            allowDiskUse=True,
        ).to_list(length=None)
        denominator = int(occurrences_total) * safe_positions_limit
        ranking = []
        for index, row in enumerate(rows, start=1):
            number = int(row.get("_id") or 0)
            count = int(row.get("count") or 0)
            ranking.append(
                {
                    "position": index,
                    "number": number,
                    "count": count,
                    "percentage": _percentage(count, denominator),
                }
            )
        summed_ranking = {
            "positions_used": list(range(1, safe_positions_limit + 1)),
            "total_slots": denominator,
            "ranking": ranking,
        }

    preview = []
    if safe_preview_limit > 0:
        preview_cursor = (
            next_number_sequences_coll
            .find(
                match_filter,
                {
                    "_id": 0,
                    "base_history_id": 1,
                    "base_number": 1,
                    "base_timestamp_utc": 1,
                    "base_date_br": 1,
                    "base_time_br": 1,
                    "base_hour_br": 1,
                    "next_numbers": 1,
                    "next_values": 1,
                },
            )
            .sort([("base_timestamp_utc", -1)])
            .limit(safe_preview_limit)
        )
        preview = await preview_cursor.to_list(length=safe_preview_limit)

    return {
        "roulette_id": safe_roulette_id,
        "version": SERVICE_VERSION,
        "filters": {
            "base_number": safe_base_number,
            "positions_limit": safe_positions_limit,
            "hour_start": safe_hour_start,
            "hour_end": safe_hour_end,
            "timezone": "America/Sao_Paulo",
            "mode": safe_mode,
            "time_window_enabled": safe_time_window_enabled,
            "time_window_value": safe_time_window_value,
            "time_window_unit": safe_time_window_unit,
            "time_window_start_utc": time_window_start_utc,
        },
        "occurrences_total": int(occurrences_total),
        "separated_rankings": separated_rankings,
        "summed_ranking": summed_ranking,
        "preview": preview,
        "preview_count": len(preview),
    }
