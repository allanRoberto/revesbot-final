from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Sequence


G5_SHADOW_SCENARIO_KEY = "g5_n4_v1"
G5_SHADOW_ATTEMPT_HORIZON = 5
G5_SHADOW_MINIMUM_SAMPLE = 1000
G5_SHADOW_ACCURACY_TARGET = 95.0
G5_SHADOW_RETENTION_TARGET = 50.0


def _as_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(
            timezone.utc
        )
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(
            timezone.utc
        )
    return None


def _signal_time(signal: Mapping[str, Any]) -> datetime | None:
    return _as_utc(signal.get("signal_minute_utc")) or _as_utc(
        signal.get("generated_at_utc")
    )


def _scenario(signal: Mapping[str, Any], scenario_key: str) -> Mapping[str, Any] | None:
    scenarios = signal.get("shadow_scenarios") or {}
    scenario = scenarios.get(scenario_key) if isinstance(scenarios, Mapping) else None
    return scenario if isinstance(scenario, Mapping) else None


def _baseline_values(signal: Mapping[str, Any]) -> set[int]:
    values = {
        int(value)
        for value in signal.get("bet_values", []) or []
        if value is not None
    }
    values.update(
        int(value)
        for value in (signal.get("alternative_analysis") or {}).get(
            "alternative_bet_values", []
        )
        or []
        if value is not None
    )
    return values


def _scenario_values(scenario: Mapping[str, Any]) -> set[int]:
    return {
        int(value)
        for value in scenario.get("effective_bet_values", []) or []
        if value is not None
    }


def _evaluate(
    signal: Mapping[str, Any],
    *,
    target_values: set[int],
    attempt_horizon: int,
) -> Dict[str, Any]:
    attempts = list(signal.get("attempts", []) or [])[:attempt_horizon]
    first_hit_attempt: int | None = None
    hit_count = 0
    serialized_attempts = []
    for index, attempt in enumerate(attempts, 1):
        try:
            value = int(attempt.get("value"))
        except (TypeError, ValueError):
            continue
        attempt_number = int(attempt.get("attempt_number", index) or index)
        is_hit = value in target_values
        if is_hit:
            hit_count += 1
            if first_hit_attempt is None:
                first_hit_attempt = attempt_number
        serialized_attempts.append(
            {
                "attempt": attempt_number,
                "value": value,
                "formatted": attempt.get("formatted"),
                "timestamp_utc": attempt.get("timestamp_utc"),
                "is_hit": is_hit,
            }
        )

    eligible = len(attempts) >= attempt_horizon
    hit = first_hit_attempt is not None if eligible else None
    return {
        "eligible": eligible,
        "outcome": "hit" if hit is True else "miss" if hit is False else "pending",
        "hit": hit,
        "first_hit_attempt": first_hit_attempt if eligible else None,
        "observed_first_hit_attempt": first_hit_attempt,
        "hit_count": hit_count if eligible else None,
        "attempt_count": len(attempts),
        "attempts": serialized_attempts,
        "coverage": len(target_values),
    }


def _summarize(
    evaluations: Sequence[Mapping[str, Any]],
    *,
    attempt_horizon: int,
) -> Dict[str, Any]:
    evaluated = [item for item in evaluations if item.get("eligible")]
    hits = [item for item in evaluated if item.get("hit") is True]
    pending = len(evaluations) - len(evaluated)
    attempt_rows = []
    cumulative_hits = 0
    for attempt in range(1, attempt_horizon + 1):
        exact_hits = sum(
            1
            for item in hits
            if int(item.get("first_hit_attempt") or 0) == attempt
        )
        cumulative_hits += exact_hits
        attempt_rows.append(
            {
                "attempt": attempt,
                "hits": exact_hits,
                "accuracy": round(exact_hits / len(evaluated) * 100, 2)
                if evaluated
                else 0.0,
                "cumulative_hits": cumulative_hits,
                "cumulative_accuracy": round(
                    cumulative_hits / len(evaluated) * 100,
                    2,
                )
                if evaluated
                else 0.0,
            }
        )
    coverage_values = [int(item.get("coverage", 0) or 0) for item in evaluations]
    return {
        "signals": len(evaluations),
        "evaluated": len(evaluated),
        "pending": pending,
        "hits": len(hits),
        "misses": len(evaluated) - len(hits),
        "accuracy": round(len(hits) / len(evaluated) * 100, 2)
        if evaluated
        else 0.0,
        "average_coverage": round(
            sum(coverage_values) / len(coverage_values), 2
        )
        if coverage_values
        else 0.0,
        "minimum_coverage": min(coverage_values) if coverage_values else 0,
        "maximum_coverage": max(coverage_values) if coverage_values else 0,
        "attempt_accuracy": attempt_rows,
    }


def analyze_g5_shadow_signals(
    signals: Sequence[Mapping[str, Any]],
    *,
    scenario_key: str = G5_SHADOW_SCENARIO_KEY,
    recent_limit: int = 80,
) -> Dict[str, Any]:
    ordered = sorted(
        (signal for signal in signals if _signal_time(signal) is not None),
        key=lambda signal: _signal_time(signal)
        or datetime.min.replace(tzinfo=timezone.utc),
    )
    scenario_times = [
        _signal_time(signal)
        for signal in ordered
        if _scenario(signal, scenario_key) is not None
    ]
    scenario_times = [value for value in scenario_times if value is not None]
    started_at = min(scenario_times) if scenario_times else None
    cohort = [
        signal
        for signal in ordered
        if started_at is not None
        and (_signal_time(signal) or started_at) >= started_at
    ]
    scenario_signals = [
        signal for signal in cohort if _scenario(signal, scenario_key) is not None
    ]
    retention = (
        round(len(scenario_signals) / len(cohort) * 100, 2) if cohort else 0.0
    )

    candidate_evaluations = []
    baseline_evaluations = []
    recent_rows = []
    for signal in scenario_signals:
        scenario = _scenario(signal, scenario_key) or {}
        horizon = max(
            1,
            min(
                10,
                int(
                    scenario.get(
                        "attempt_horizon", G5_SHADOW_ATTEMPT_HORIZON
                    )
                    or G5_SHADOW_ATTEMPT_HORIZON
                ),
            ),
        )
        candidate = _evaluate(
            signal,
            target_values=_scenario_values(scenario),
            attempt_horizon=horizon,
        )
        baseline = _evaluate(
            signal,
            target_values=_baseline_values(signal),
            attempt_horizon=horizon,
        )
        candidate_evaluations.append(candidate)
        baseline_evaluations.append(baseline)
        recent_rows.append(
            {
                "signal_id": str(signal.get("_id") or signal.get("signal_key") or ""),
                "signal_minute_utc": signal.get("signal_minute_utc"),
                "signal_minute_br": signal.get("signal_minute_br"),
                "selected_centers": list(scenario.get("selected_centers", []) or []),
                "alternative_center": (
                    scenario.get("alternative_analysis") or {}
                ).get("alternative_center"),
                "coverage": int(scenario.get("coverage", 0) or 0),
                "effective_coverage": int(
                    scenario.get("effective_coverage", candidate["coverage"]) or 0
                ),
                "effective_bet_values": list(
                    scenario.get("effective_bet_values", []) or []
                ),
                "candidate": candidate,
                "baseline": baseline,
            }
        )

    candidate_summary = _summarize(
        candidate_evaluations,
        attempt_horizon=G5_SHADOW_ATTEMPT_HORIZON,
    )
    baseline_summary = _summarize(
        baseline_evaluations,
        attempt_horizon=G5_SHADOW_ATTEMPT_HORIZON,
    )
    evaluated = int(candidate_summary["evaluated"])
    sample_ready = evaluated >= G5_SHADOW_MINIMUM_SAMPLE
    accuracy_ready = (
        float(candidate_summary["accuracy"]) > G5_SHADOW_ACCURACY_TARGET
    )
    retention_ready = retention >= G5_SHADOW_RETENTION_TARGET
    if not sample_ready:
        gate_status = "collecting"
    elif accuracy_ready and retention_ready:
        gate_status = "criteria_met"
    else:
        gate_status = "below_target"

    recent_rows.sort(
        key=lambda item: _as_utc(item.get("signal_minute_utc"))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return {
        "scenario_key": scenario_key,
        "mode": "shadow",
        "started_at_utc": started_at,
        "cohort_signals": len(cohort),
        "scenario_signals": len(scenario_signals),
        "retention": retention,
        "baseline": baseline_summary,
        "candidate": candidate_summary,
        "comparison": {
            "accuracy_delta": round(
                float(candidate_summary["accuracy"])
                - float(baseline_summary["accuracy"]),
                2,
            ),
            "coverage_delta": round(
                float(candidate_summary["average_coverage"])
                - float(baseline_summary["average_coverage"]),
                2,
            ),
        },
        "gate": {
            "status": gate_status,
            "minimum_sample": G5_SHADOW_MINIMUM_SAMPLE,
            "accuracy_target": G5_SHADOW_ACCURACY_TARGET,
            "accuracy_operator": ">",
            "retention_target": G5_SHADOW_RETENTION_TARGET,
            "sample_ready": sample_ready,
            "accuracy_ready": accuracy_ready,
            "retention_ready": retention_ready,
        },
        "historical_backtest": {
            "signals": 43200,
            "accuracy": 97.22,
            "wilson_low_95": 97.07,
            "retention": 100.0,
            "average_coverage": 19.32,
            "period_days": 30,
        },
        "recent_signals": recent_rows[: max(1, int(recent_limit))],
    }
