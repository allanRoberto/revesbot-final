from __future__ import annotations

from datetime import datetime, timezone
from statistics import mean, median
from typing import Any, Dict, Mapping, Sequence


def _as_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)
    return None


def _values(items: Sequence[Any] | None) -> set[int]:
    values: set[int] = set()
    for item in items or []:
        try:
            values.add(int(item))
        except (TypeError, ValueError):
            continue
    return {value for value in values if 0 <= value <= 36}


def suggestion_values(
    signal: Mapping[str, Any],
    *,
    include_alternative: bool,
) -> tuple[set[int], set[int], set[int]]:
    official = _values(signal.get("bet_values"))
    alternative: set[int] = set()
    if include_alternative:
        alternative = _values(
            (signal.get("alternative_analysis") or {}).get(
                "alternative_bet_values"
            )
        )
    return official | alternative, official, alternative


def _signal_time(signal: Mapping[str, Any]) -> datetime | None:
    return _as_utc(signal.get("signal_minute_utc"))


def _signal_cutoff(signal: Mapping[str, Any]) -> datetime | None:
    return _as_utc(signal.get("generated_at_utc")) or _signal_time(signal)


def _unique_result_events(signals: Sequence[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    events: Dict[str, Dict[str, Any]] = {}
    for signal in signals:
        for attempt in signal.get("attempts", []) or []:
            timestamp = _as_utc(attempt.get("timestamp_utc"))
            try:
                value = int(attempt.get("value"))
            except (TypeError, ValueError):
                continue
            if timestamp is None or not 0 <= value <= 36:
                continue
            history_id = str(attempt.get("result_history_id") or "")
            key = history_id or f"{timestamp.isoformat()}:{value}"
            events[key] = {
                "value": value,
                "timestamp_utc": timestamp,
            }
    return sorted(events.values(), key=lambda item: item["timestamp_utc"])


def _source_label(number: int, official: set[int], alternative: set[int]) -> str:
    if number in official and number in alternative:
        return "official_and_alternative"
    if number in alternative:
        return "alternative"
    return "official"


def _center_values(signal: Mapping[str, Any]) -> list[int]:
    centers: list[int] = []
    for item in signal.get("selected_centers", []) or []:
        raw_value = item.get("value", item.get("center")) if isinstance(item, Mapping) else item
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            continue
        if 0 <= value <= 36:
            centers.append(value)
    return centers


def _evaluate_number(
    signal: Mapping[str, Any],
    *,
    number: int,
    attempt_horizon: int,
) -> Dict[str, Any]:
    attempts = list(signal.get("attempts", []) or [])[:attempt_horizon]
    first_hit_attempt: int | None = None
    hit_timestamp: datetime | None = None
    serialized_attempts: list[Dict[str, Any]] = []
    for index, attempt in enumerate(attempts, 1):
        try:
            value = int(attempt.get("value"))
        except (TypeError, ValueError):
            continue
        attempt_number = int(attempt.get("attempt_number", index) or index)
        timestamp = _as_utc(attempt.get("timestamp_utc"))
        is_hit = value == number
        if is_hit and first_hit_attempt is None:
            first_hit_attempt = attempt_number
            hit_timestamp = timestamp
        serialized_attempts.append(
            {
                "attempt": attempt_number,
                "value": value,
                "timestamp_utc": timestamp,
                "formatted": attempt.get("formatted"),
                "is_hit": is_hit,
            }
        )

    eligible = first_hit_attempt is not None or len(attempts) >= attempt_horizon
    outcome = "hit" if first_hit_attempt is not None else "miss" if eligible else "pending"
    trigger_time = _signal_cutoff(signal)
    seconds_to_hit = None
    if trigger_time is not None and hit_timestamp is not None:
        seconds_to_hit = max(0, int((hit_timestamp - trigger_time).total_seconds()))
    return {
        "outcome": outcome,
        "eligible": eligible,
        "first_hit_attempt": first_hit_attempt,
        "seconds_to_hit": seconds_to_hit,
        "attempts": serialized_attempts,
    }


def _new_state() -> Dict[str, Any]:
    return {
        "repetitions": 0,
        "first_suggested_at": None,
        "last_suggested_at": None,
        "timeline": [],
    }


def _reset_state(state: Dict[str, Any]) -> None:
    state.update(_new_state())


def _build_threshold_rows(
    triggers: Sequence[Mapping[str, Any]],
    *,
    max_repetitions: int,
    attempt_horizon: int,
) -> list[Dict[str, Any]]:
    rows: list[Dict[str, Any]] = []
    baseline_accuracy = 0.0
    for threshold in range(1, max_repetitions + 1):
        threshold_triggers = [
            item for item in triggers if int(item.get("threshold", 0)) == threshold
        ]
        evaluated = [item for item in threshold_triggers if item.get("eligible")]
        hits = [item for item in evaluated if item.get("outcome") == "hit"]
        accuracy = round((len(hits) / len(evaluated)) * 100, 2) if evaluated else 0.0
        if threshold == 1:
            baseline_accuracy = accuracy
        attempt_rows: list[Dict[str, Any]] = []
        cumulative_hits = 0
        for attempt in range(1, attempt_horizon + 1):
            attempt_hits = sum(
                1 for item in hits if item.get("first_hit_attempt") == attempt
            )
            cumulative_hits += attempt_hits
            attempt_rows.append(
                {
                    "attempt": attempt,
                    "hits": attempt_hits,
                    "accuracy": round((attempt_hits / len(evaluated)) * 100, 2)
                    if evaluated
                    else 0.0,
                    "cumulative_hits": cumulative_hits,
                    "cumulative_accuracy": round(
                        (cumulative_hits / len(evaluated)) * 100,
                        2,
                    )
                    if evaluated
                    else 0.0,
                }
            )
        hit_attempts = [int(item["first_hit_attempt"]) for item in hits]
        hit_seconds = [
            int(item["seconds_to_hit"])
            for item in hits
            if item.get("seconds_to_hit") is not None
        ]
        rows.append(
            {
                "threshold": threshold,
                "triggers": len(threshold_triggers),
                "evaluated": len(evaluated),
                "pending": len(threshold_triggers) - len(evaluated),
                "hits": len(hits),
                "misses": len(evaluated) - len(hits),
                "accuracy": accuracy,
                "lift_vs_first": round(accuracy - baseline_accuracy, 2),
                "average_hit_attempt": round(mean(hit_attempts), 2)
                if hit_attempts
                else None,
                "median_hit_attempt": round(float(median(hit_attempts)), 2)
                if hit_attempts
                else None,
                "average_seconds_to_hit": round(mean(hit_seconds), 1)
                if hit_seconds
                else None,
                "attempt_accuracy": attempt_rows,
            }
        )
    return rows


def analyze_number_persistence(
    signals: Sequence[Mapping[str, Any]],
    *,
    min_repetitions: int = 3,
    max_repetitions: int = 6,
    max_gap_minutes: int = 1,
    attempt_horizon: int = 7,
    include_alternative: bool = False,
    recent_limit: int = 80,
) -> Dict[str, Any]:
    minimum = max(1, min(10, int(min_repetitions)))
    maximum = max(minimum, min(10, int(max_repetitions)))
    gap_minutes = max(1, min(10, int(max_gap_minutes)))
    horizon = max(1, min(10, int(attempt_horizon)))
    ordered_signals = sorted(
        (signal for signal in signals if _signal_time(signal) is not None),
        key=lambda item: _signal_time(item) or datetime.min.replace(tzinfo=timezone.utc),
    )
    result_events = _unique_result_events(ordered_signals)
    states = {number: _new_state() for number in range(37)}
    triggers: list[Dict[str, Any]] = []
    result_index = 0
    latest_values: set[int] = set()

    def process_results_before(cutoff: datetime | None) -> None:
        nonlocal result_index
        if cutoff is None:
            return
        while (
            result_index < len(result_events)
            and result_events[result_index]["timestamp_utc"] < cutoff
        ):
            event = result_events[result_index]
            _reset_state(states[event["value"]])
            result_index += 1

    for signal in ordered_signals:
        signal_time = _signal_time(signal)
        if signal_time is None:
            continue
        process_results_before(_signal_cutoff(signal))
        suggested, official, alternative = suggestion_values(
            signal,
            include_alternative=include_alternative,
        )
        latest_values = suggested
        centers = _center_values(signal)
        for number in suggested:
            state = states[number]
            last_time = state.get("last_suggested_at")
            gap_seconds = (
                (signal_time - last_time).total_seconds()
                if isinstance(last_time, datetime)
                else None
            )
            if gap_seconds is None or gap_seconds > gap_minutes * 60:
                _reset_state(state)
                state["first_suggested_at"] = signal_time
            state["repetitions"] += 1
            state["last_suggested_at"] = signal_time
            timeline_item = {
                "signal_minute_utc": signal_time,
                "source": _source_label(number, official, alternative),
                "centers": centers,
            }
            state["timeline"].append(timeline_item)
            threshold = int(state["repetitions"])
            if threshold > maximum:
                continue
            evaluation = _evaluate_number(
                signal,
                number=number,
                attempt_horizon=horizon,
            )
            triggers.append(
                {
                    "number": number,
                    "threshold": threshold,
                    "sequence_start_utc": state["first_suggested_at"],
                    "trigger_minute_utc": signal_time,
                    "source": timeline_item["source"],
                    "centers": centers,
                    "suggestions": list(state["timeline"]),
                    **evaluation,
                }
            )

    while result_index < len(result_events):
        event = result_events[result_index]
        _reset_state(states[event["value"]])
        result_index += 1

    active_numbers: list[Dict[str, Any]] = []
    for number in latest_values:
        state = states[number]
        repetitions = int(state.get("repetitions", 0) or 0)
        if repetitions < minimum:
            continue
        first_time = state.get("first_suggested_at")
        last_time = state.get("last_suggested_at")
        active_numbers.append(
            {
                "number": number,
                "repetitions": repetitions,
                "first_suggested_at": first_time,
                "last_suggested_at": last_time,
                "span_minutes": int((last_time - first_time).total_seconds() // 60)
                if isinstance(first_time, datetime) and isinstance(last_time, datetime)
                else 0,
                "entry_ready": repetitions >= minimum,
                "timeline": list(state.get("timeline", [])),
            }
        )
    active_numbers.sort(key=lambda item: (-item["repetitions"], item["number"]))

    recent_triggers = [
        item for item in triggers if int(item.get("threshold", 0)) == minimum
    ]
    recent_triggers.sort(
        key=lambda item: item.get("trigger_minute_utc")
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return {
        "config": {
            "min_repetitions": minimum,
            "max_repetitions": maximum,
            "max_gap_minutes": gap_minutes,
            "attempt_horizon": horizon,
            "include_alternative": bool(include_alternative),
            "signals_analyzed": len(ordered_signals),
            "reset_when_paid": True,
            "overlapping_entries": False,
        },
        "thresholds": _build_threshold_rows(
            triggers,
            max_repetitions=maximum,
            attempt_horizon=horizon,
        ),
        "active_numbers": active_numbers,
        "recent_triggers": recent_triggers[: max(1, int(recent_limit))],
    }
