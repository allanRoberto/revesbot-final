"""Agregacao honesta das tentativas prospectivas do motor orbital."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from .metrics import random_hit_probability


PERFORMANCE_WINDOWS: tuple[tuple[str, int | None], ...] = (
    ("1h", 1),
    ("3h", 3),
    ("6h", 6),
    ("12h", 12),
    ("24h", 24),
    ("all", None),
)
SAO_PAULO = ZoneInfo("America/Sao_Paulo")


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _first_hit(trial: Mapping[str, Any], ranking_size: int) -> int | None:
    value = trial.get(f"top{ranking_size}_first_hit_attempt")
    if value is None:
        return None
    parsed = int(value)
    return parsed if parsed > 0 else None


def wilson_interval(successes: int, total: int, z_score: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 0.0
    proportion = successes / total
    z2 = z_score * z_score
    denominator = 1.0 + z2 / total
    center = (proportion + z2 / (2.0 * total)) / denominator
    margin = (
        z_score
        * math.sqrt((proportion * (1.0 - proportion) / total) + z2 / (4.0 * total * total))
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def _ranking_curve(
    trials: Sequence[Mapping[str, Any]],
    *,
    ranking_size: int,
    max_attempts: int,
) -> dict[str, Any]:
    total = len(trials)
    attempts: list[dict[str, Any]] = []
    for attempt in range(1, max_attempts + 1):
        hits = sum(
            1
            for trial in trials
            if (first_hit := _first_hit(trial, ranking_size)) is not None
            and first_hit <= attempt
        )
        hit_rate = hits / total if total else 0.0
        lower, upper = wilson_interval(hits, total)
        baseline = random_hit_probability(ranking_size, attempt)
        attempts.append(
            {
                "attempt": attempt,
                "hits": hits,
                "hit_rate": round(hit_rate, 6),
                "confidence_lower": round(lower, 6),
                "confidence_upper": round(upper, 6),
                "random_baseline": round(baseline, 6),
                "delta_percentage_points": round((hit_rate - baseline) * 100.0, 3),
            }
        )
    return {
        "ranking_size": ranking_size,
        "sample_size": total,
        "attempts": attempts,
    }


def _window_payload(
    trials: Sequence[Mapping[str, Any]],
    *,
    max_attempts: int,
) -> dict[str, Any]:
    return {
        "sample_size": len(trials),
        "top9": _ranking_curve(trials, ranking_size=9, max_attempts=max_attempts),
        "top12": _ranking_curve(trials, ranking_size=12, max_attempts=max_attempts),
    }


def _hour_summary(
    trials: Sequence[Mapping[str, Any]],
    *,
    ranking_size: int = 9,
    target_attempt: int = 3,
) -> dict[str, Any] | None:
    groups: dict[int, list[Mapping[str, Any]]] = {hour: [] for hour in range(24)}
    for trial in trials:
        timestamp = _utc(trial.get("anchor_timestamp_utc"))
        if timestamp is None:
            continue
        groups[timestamp.astimezone(SAO_PAULO).hour].append(trial)

    candidates: list[dict[str, Any]] = []
    baseline = random_hit_probability(ranking_size, target_attempt)
    for hour, rows in groups.items():
        if not rows:
            continue
        hits = sum(
            1
            for row in rows
            if (first_hit := _first_hit(row, ranking_size)) is not None
            and first_hit <= target_attempt
        )
        rate = hits / len(rows)
        lower, upper = wilson_interval(hits, len(rows))
        candidates.append(
            {
                "hour": hour,
                "label": f"{hour:02d}:00–{hour:02d}:59",
                "timezone": "America/Sao_Paulo",
                "ranking_size": ranking_size,
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


def build_performance_summary(
    trials: Iterable[Mapping[str, Any]],
    *,
    now: datetime | None = None,
    max_attempts: int = 10,
) -> dict[str, Any]:
    """Calcula curvas cumulativas usando apenas janelas completas."""

    safe_attempts = max(1, min(20, int(max_attempts)))
    reference = _utc(now or datetime.now(timezone.utc)) or datetime.now(timezone.utc)
    completed = [
        trial
        for trial in trials
        if str(trial.get("status")) == "resolved"
        and int(trial.get("attempts_observed") or 0) >= safe_attempts
        and _utc(trial.get("anchor_timestamp_utc")) is not None
    ]
    completed.sort(
        key=lambda trial: _utc(trial.get("anchor_timestamp_utc")) or datetime.min.replace(tzinfo=timezone.utc),
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
                if (_utc(trial.get("anchor_timestamp_utc")) or reference) >= cutoff
            ]
        windows[key] = _window_payload(rows, max_attempts=safe_attempts)

    return {
        "max_attempts": safe_attempts,
        "resolved_trials": len(completed),
        "windows": windows,
        "best_hour": _hour_summary(completed),
        "methodology": {
            "rate_type": "cumulative_first_hit",
            "cohort": "completed_windows_only",
            "timezone": "America/Sao_Paulo",
            "best_hour_metric": "top9_hit_by_attempt_3_wilson_lower_bound",
        },
    }
