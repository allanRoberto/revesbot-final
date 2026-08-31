from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math
from statistics import mean, median
import time
from typing import Any, Literal

from starlette.concurrency import run_in_threadpool

from api.core.runtime_db import history_coll
from api.services.roulette_analyzer_service import (
    RouletteHistoryNotFoundError,
    RouletteHistoryUnavailableError,
)
from gatilhos.roulette_analyzer import analyze


RenewalMode = Literal["spins", "minutes"]
MAX_BACKTEST_WORK = 10_000_000


class RouletteBacktestValidationError(ValueError):
    """A combinação de parâmetros excede os limites seguros da API."""


@dataclass(frozen=True)
class _HitEvent:
    attempt: int | None
    completed: bool
    renewed: bool
    elapsed_seconds: float | None


def _next_renewal(
    timestamps: list[datetime],
    cutoff: int,
    mode: RenewalMode,
    value: int,
    analysis_time: datetime,
) -> tuple[int, bool, datetime | None]:
    if mode == "spins":
        target = cutoff + value
        actual = target <= len(timestamps)
        next_cutoff = min(target, len(timestamps))
        next_time = timestamps[next_cutoff - 1] if actual else None
        return next_cutoff, actual, next_time

    threshold = analysis_time + timedelta(minutes=value)
    for index in range(cutoff + 1, len(timestamps)):
        if timestamps[index] >= threshold:
            return index, True, threshold
    return len(timestamps), False, None


def _first_hit(
    values: list[int],
    timestamps: list[datetime],
    cutoff: int,
    outcome_end: int,
    selected: set[int],
    completed_without_hit: bool,
    renewed: bool,
    analysis_time: datetime,
) -> _HitEvent:
    for index in range(cutoff, outcome_end):
        if values[index] in selected:
            elapsed = max(
                0.0,
                (timestamps[index] - analysis_time).total_seconds(),
            )
            return _HitEvent(
                attempt=index - cutoff + 1,
                completed=True,
                renewed=renewed,
                elapsed_seconds=elapsed,
            )
    return _HitEvent(
        attempt=None,
        completed=completed_without_hit,
        renewed=renewed,
        elapsed_seconds=None,
    )


def _percentile_nearest_rank(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _event_metrics(
    events: list[_HitEvent],
    *,
    max_attempts: int,
    target_hit_rate: float,
    number_count: int,
) -> dict[str, Any]:
    hits = [event for event in events if event.attempt is not None]
    completed_misses = [
        event for event in events if event.attempt is None and event.completed
    ]
    censored = [
        event for event in events if event.attempt is None and not event.completed
    ]
    evaluated_cycles = len(hits) + len(completed_misses)
    exact_counts = {attempt: 0 for attempt in range(1, max_attempts + 1)}
    for event in hits:
        exact_counts[int(event.attempt)] += 1

    cumulative_hits = 0
    cumulative: list[dict[str, Any]] = []
    recommended_attempt: int | None = None
    for attempt in range(1, max_attempts + 1):
        cumulative_hits += exact_counts[attempt]
        rate = cumulative_hits / evaluated_cycles if evaluated_cycles else 0.0
        if recommended_attempt is None and rate >= target_hit_rate:
            recommended_attempt = attempt
        cumulative.append(
            {
                "attempt": attempt,
                "hits_at_attempt": exact_counts[attempt],
                "cumulative_hits": cumulative_hits,
                "cumulative_hit_rate": rate,
            }
        )

    attempts = [int(event.attempt) for event in hits]
    elapsed = [
        float(event.elapsed_seconds)
        for event in hits
        if event.elapsed_seconds is not None
    ]
    longest_miss_streak = 0
    current_miss_streak = 0
    for event in events:
        if event.attempt is not None:
            current_miss_streak = 0
        elif event.completed:
            current_miss_streak += 1
            longest_miss_streak = max(longest_miss_streak, current_miss_streak)

    return {
        "number_count": number_count,
        "random_single_spin_rate": number_count / 37.0,
        "cycles_total": len(events),
        "evaluated_cycles": evaluated_cycles,
        "hit_cycles": len(hits),
        "no_hit_cycles": len(completed_misses),
        "censored_cycles": len(censored),
        "hit_rate": len(hits) / evaluated_cycles if evaluated_cycles else 0.0,
        "renewed_without_hit": sum(
            event.attempt is None and event.completed and event.renewed
            for event in events
        ),
        "longest_no_hit_streak": longest_miss_streak,
        "average_first_hit_attempt": mean(attempts) if attempts else None,
        "median_first_hit_attempt": median(attempts) if attempts else None,
        "p80_first_hit_attempt": _percentile_nearest_rank(attempts, 0.80),
        "p90_first_hit_attempt": _percentile_nearest_rank(attempts, 0.90),
        "average_time_to_hit_seconds": mean(elapsed) if elapsed else None,
        "recommended_attempt_for_target": recommended_attempt,
        "target_hit_rate": target_hit_rate,
        "attempts": cumulative,
    }


def backtest_rows(
    rows_newest_first: list[dict[str, Any]],
    *,
    roulette_id: str,
    analysis_window: int,
    backtest_limit: int,
    max_attempts: int,
    renewal_mode: RenewalMode,
    renewal_value: int,
    target_hit_rate: float,
) -> dict[str, Any]:
    valid_rows: list[dict[str, Any]] = []
    for row in reversed(rows_newest_first):
        value = row.get("value")
        timestamp = row.get("timestamp")
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and 0 <= value <= 36
            and isinstance(timestamp, datetime)
        ):
            valid_rows.append(row)

    invalid_records = len(rows_newest_first) - len(valid_rows)
    if len(valid_rows) <= analysis_window:
        raise RouletteHistoryNotFoundError(roulette_id)

    values = [int(row["value"]) for row in valid_rows]
    timestamps = [row["timestamp"] for row in valid_rows]
    available_backtest = min(backtest_limit, len(values) - analysis_window)
    start = len(values) - available_backtest - analysis_window
    if start > 0:
        values = values[start:]
        timestamps = timestamps[start:]

    trigger_events: list[_HitEvent] = []
    pulling_events: list[_HitEvent] = []
    renewal_intervals: list[float] = []
    cutoff = analysis_window
    analysis_count = 0
    analysis_time = timestamps[cutoff - 1]

    while cutoff < len(values):
        if renewal_mode == "minutes":
            interval = timedelta(minutes=renewal_value)
            while timestamps[cutoff] >= analysis_time + interval:
                analysis_time += interval

        history = list(reversed(values[cutoff - analysis_window:cutoff]))
        result = analyze(history, regression_compatibility=False)
        next_cutoff, actual_renewal, next_analysis_time = _next_renewal(
            timestamps,
            cutoff,
            renewal_mode,
            renewal_value,
            analysis_time,
        )
        outcome_end = min(len(values), cutoff + max_attempts, next_cutoff)
        completed_without_hit = (
            outcome_end >= cutoff + max_attempts or actual_renewal
        )

        trigger_events.append(
            _first_hit(
                values,
                timestamps,
                cutoff,
                outcome_end,
                set(result["gatilhos"]),
                completed_without_hit,
                actual_renewal,
                analysis_time,
            )
        )
        pulling_events.append(
            _first_hit(
                values,
                timestamps,
                cutoff,
                outcome_end,
                set(result["numeros_fortes"]),
                completed_without_hit,
                actual_renewal,
                analysis_time,
            )
        )
        analysis_count += 1

        if next_cutoff >= len(values):
            break
        if next_analysis_time is None:
            break
        renewal_intervals.append(
            max(0.0, (next_analysis_time - analysis_time).total_seconds())
        )
        analysis_time = next_analysis_time
        cutoff = next_cutoff

    roulette_name = next(
        (
            str(row.get("roulette_name"))
            for row in reversed(rows_newest_first)
            if row.get("roulette_name")
        ),
        roulette_id,
    )
    return {
        "roulette_id": roulette_id,
        "roulette_name": roulette_name,
        "records_loaded": len(rows_newest_first),
        "invalid_records_ignored": invalid_records,
        "analysis_count": analysis_count,
        "backtest_results_used": available_backtest,
        "average_actual_renewal_seconds": (
            mean(renewal_intervals) if renewal_intervals else None
        ),
        "gatilhos": _event_metrics(
            trigger_events,
            max_attempts=max_attempts,
            target_hit_rate=target_hit_rate,
            number_count=6,
        ),
        "numeros_puxando": _event_metrics(
            pulling_events,
            max_attempts=max_attempts,
            target_hit_rate=target_hit_rate,
            number_count=13,
        ),
    }


async def run_roulette_analyzer_backtest(
    *,
    roulette_ids: list[str],
    analysis_window: int,
    backtest_limit: int,
    max_attempts: int,
    renewal_mode: RenewalMode,
    renewal_value: int,
    target_hit_rate: float,
) -> dict[str, Any]:
    normalized_ids = list(dict.fromkeys(value.strip() for value in roulette_ids))
    normalized_ids = [value for value in normalized_ids if value]
    if not normalized_ids:
        raise RouletteBacktestValidationError("Informe ao menos uma roleta")

    worst_cycles_per_table = (
        math.ceil(backtest_limit / renewal_value)
        if renewal_mode == "spins"
        else backtest_limit
    )
    estimated_work = (
        len(normalized_ids) * worst_cycles_per_table * analysis_window
    )
    if estimated_work > MAX_BACKTEST_WORK:
        raise RouletteBacktestValidationError(
            "Combinação muito pesada; reduza mesas, janela, profundidade ou aumente o intervalo de renovação"
        )

    started = time.perf_counter()
    tables: list[dict[str, Any]] = []
    fetch_limit = analysis_window + backtest_limit
    for roulette_id in normalized_ids:
        try:
            rows = await (
                history_coll.find(
                    {"roulette_id": roulette_id},
                    {
                        "_id": 0,
                        "value": 1,
                        "timestamp": 1,
                        "roulette_name": 1,
                    },
                )
                .sort("timestamp", -1)
                .limit(fetch_limit)
                .to_list(length=fetch_limit)
            )
        except Exception as exc:
            raise RouletteHistoryUnavailableError from exc
        if not rows:
            raise RouletteHistoryNotFoundError(roulette_id)

        table_result = await run_in_threadpool(
            backtest_rows,
            rows,
            roulette_id=roulette_id,
            analysis_window=analysis_window,
            backtest_limit=backtest_limit,
            max_attempts=max_attempts,
            renewal_mode=renewal_mode,
            renewal_value=renewal_value,
            target_hit_rate=target_hit_rate,
        )
        tables.append(table_result)

    return {
        "config": {
            "roulette_ids": normalized_ids,
            "analysis_window": analysis_window,
            "backtest_limit": backtest_limit,
            "max_attempts": max_attempts,
            "renewal_mode": renewal_mode,
            "renewal_value": renewal_value,
            "target_hit_rate": target_hit_rate,
            "regression_compatibility": False,
        },
        "tables": tables,
        "duration_ms": round((time.perf_counter() - started) * 1000.0, 2),
    }
