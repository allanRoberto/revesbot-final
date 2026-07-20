"""Metricas prospectivas para entradas de gatilho com cobertura variavel."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

from ..performance import PERFORMANCE_WINDOWS, SAO_PAULO, wilson_interval


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _first_hit(trial: Mapping[str, Any]) -> int | None:
    value = trial.get("first_hit_attempt")
    if value is None:
        return None
    parsed = int(value)
    return parsed if parsed > 0 else None


def _baseline(target_size: int, attempt: int) -> float:
    safe_size = max(0, min(37, int(target_size)))
    if safe_size == 0:
        return 0.0
    return 1.0 - ((37 - safe_size) / 37) ** max(1, int(attempt))


def _curve(trials: Sequence[Mapping[str, Any]], *, max_attempts: int) -> dict[str, Any]:
    total = len(trials)
    attempts: list[dict[str, Any]] = []
    for attempt in range(1, max_attempts + 1):
        hits = sum(
            1
            for trial in trials
            if (first_hit := _first_hit(trial)) is not None and first_hit <= attempt
        )
        rate = hits / total if total else 0.0
        lower, upper = wilson_interval(hits, total)
        baseline = (
            sum(_baseline(int(trial.get("target_size") or 0), attempt) for trial in trials) / total
            if total
            else 0.0
        )
        attempts.append(
            {
                "attempt": attempt,
                "hits": hits,
                "hit_rate": round(rate, 6),
                "confidence_lower": round(lower, 6),
                "confidence_upper": round(upper, 6),
                "random_baseline": round(baseline, 6),
                "delta_percentage_points": round((rate - baseline) * 100.0, 3),
            }
        )
    average_size = (
        sum(int(trial.get("target_size") or 0) for trial in trials) / total if total else 0.0
    )
    return {
        "sample_size": total,
        "average_target_size": round(average_size, 3),
        "attempts": attempts,
    }


def _hour_summary(
    trials: Sequence[Mapping[str, Any]],
    *,
    target_attempt: int = 3,
) -> dict[str, Any] | None:
    groups: dict[int, list[Mapping[str, Any]]] = {hour: [] for hour in range(24)}
    for trial in trials:
        timestamp = _utc(trial.get("activation_timestamp_utc"))
        if timestamp is not None:
            groups[timestamp.astimezone(SAO_PAULO).hour].append(trial)

    candidates: list[dict[str, Any]] = []
    for hour, rows in groups.items():
        if not rows:
            continue
        hits = sum(
            1
            for row in rows
            if (first_hit := _first_hit(row)) is not None and first_hit <= target_attempt
        )
        rate = hits / len(rows)
        lower, upper = wilson_interval(hits, len(rows))
        baseline = sum(
            _baseline(int(row.get("target_size") or 0), target_attempt) for row in rows
        ) / len(rows)
        candidates.append(
            {
                "hour": hour,
                "label": f"{hour:02d}:00–{hour:02d}:59",
                "timezone": "America/Sao_Paulo",
                "target_attempt": target_attempt,
                "sample_size": len(rows),
                "hits": hits,
                "hit_rate": round(rate, 6),
                "confidence_lower": round(lower, 6),
                "confidence_upper": round(upper, 6),
                "random_baseline": round(baseline, 6),
                "delta_percentage_points": round((rate - baseline) * 100.0, 3),
                "provisional": len(rows) < 30,
            }
        )
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda row: (
            row["confidence_lower"],
            row["hit_rate"],
            row["sample_size"],
            -row["hour"],
        ),
    )


def build_trigger_performance_summary(
    trials: Iterable[Mapping[str, Any]],
    *,
    now: datetime | None = None,
    max_attempts: int = 5,
) -> dict[str, Any]:
    safe_attempts = max(1, min(20, int(max_attempts)))
    reference = _utc(now or datetime.now(timezone.utc)) or datetime.now(timezone.utc)
    completed = [
        trial
        for trial in trials
        if str(trial.get("status")) == "resolved"
        and int(trial.get("attempts_observed") or 0) >= safe_attempts
        and _utc(trial.get("activation_timestamp_utc")) is not None
    ]
    completed.sort(
        key=lambda trial: _utc(trial.get("activation_timestamp_utc"))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    windows: dict[str, Any] = {}
    for key, hours in PERFORMANCE_WINDOWS:
        rows = completed
        if hours is not None:
            cutoff = reference - timedelta(hours=hours)
            rows = [
                trial
                for trial in completed
                if (_utc(trial.get("activation_timestamp_utc")) or reference) >= cutoff
            ]
        windows[key] = {
            "sample_size": len(rows),
            "entry": _curve(rows, max_attempts=safe_attempts),
        }

    return {
        "max_attempts": safe_attempts,
        "resolved_trials": len(completed),
        "windows": windows,
        "best_hour": _hour_summary(completed),
        "methodology": {
            "rate_type": "cumulative_first_hit",
            "cohort": "completed_windows_only",
            "baseline": "mean_independent_spin_target_coverage",
            "timezone": "America/Sao_Paulo",
            "best_hour_metric": "hit_by_attempt_3_wilson_lower_bound",
        },
    }
