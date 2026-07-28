"""Métricas estatísticas e financeiras dos sinais de terminais."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable, Mapping, Sequence


MONEY = Decimal("0.01")
MEGA_ROULETTES = {
    "pragmatic-mega-roulette",
    "pragmatic-mega-roulette-brazilian",
    "pragmatic-auto-mega-roulette",
    "pragmatic-turkish-mega-roulette",
    "pragmatic-italian-mega-roulette",
}


def _utc(value: Any) -> datetime:
    if not isinstance(value, datetime):
        return datetime.min.replace(tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _money(value: Decimal) -> float:
    return float(value.quantize(MONEY, rounding=ROUND_HALF_UP))


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 0.0
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt((proportion * (1 - proportion) + z * z / (4 * total)) / total)
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def random_hit_baseline(target_size: int, attempts: int) -> float:
    size = max(0, min(37, int(target_size)))
    return 1.0 - ((37 - size) / 37) ** max(1, int(attempts))


def _observed_attempts(row: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return sorted(
        (
            attempt
            for attempt in row.get("attempts") or []
            if int(attempt.get("attempt") or 0) >= 1
        ),
        key=lambda attempt: int(attempt.get("attempt") or 0),
    )


def _is_mature(row: Mapping[str, Any], horizon: int) -> bool:
    observed = int(row.get("attempts_observed") or len(_observed_attempts(row)))
    return observed >= int(horizon)


def _first_hit_attempt(row: Mapping[str, Any], horizon: int) -> int | None:
    for attempt in _observed_attempts(row):
        number = int(attempt.get("attempt") or 0)
        if number > horizon:
            break
        if bool(attempt.get("hit")):
            return number
    return None


def summarize_trials(
    trials: Iterable[Mapping[str, Any]],
    *,
    max_attempts: int = 2,
    cohort_horizon: int | None = None,
) -> dict[str, Any]:
    if not 1 <= int(max_attempts) <= 10:
        raise ValueError("o horizonte precisa estar entre 1 e 10 tentativas")
    required_horizon = int(cohort_horizon or max_attempts)
    if required_horizon < int(max_attempts):
        raise ValueError("a coorte não pode terminar antes do horizonte simulado")
    rows = list(trials)
    resolved = [row for row in rows if _is_mature(row, required_horizon)]
    first_hits = {
        str(row.get("event_id") or index): _first_hit_attempt(row, int(max_attempts))
        for index, row in enumerate(resolved)
    }
    wins = [
        row
        for index, row in enumerate(resolved)
        if first_hits[str(row.get("event_id") or index)] is not None
    ]
    losses = len(resolved) - len(wins)
    exact_hits = {
        str(attempt): sum(
            first_hits[str(row.get("event_id") or index)] == attempt
            for index, row in enumerate(resolved)
        )
        for attempt in range(1, max_attempts + 1)
    }
    cumulative = []
    for attempt in range(1, max_attempts + 1):
        hits = sum(
            1
            for index, row in enumerate(resolved)
            if first_hits[str(row.get("event_id") or index)] is not None
            and int(first_hits[str(row.get("event_id") or index)] or 0) <= attempt
        )
        lower, upper = wilson_interval(hits, len(resolved))
        baseline = (
            sum(random_hit_baseline(int(row.get("target_size") or 0), attempt) for row in resolved)
            / len(resolved)
            if resolved
            else 0.0
        )
        rate = hits / len(resolved) if resolved else 0.0
        cumulative.append(
            {
                "attempt": attempt,
                "hits": hits,
                "hit_rate": round(rate, 6),
                "confidence_lower": round(lower, 6),
                "confidence_upper": round(upper, 6),
                "random_baseline": round(baseline, 6),
                "delta_percentage_points": round((rate - baseline) * 100, 3),
            }
        )
    average_target_size = (
        sum(int(row.get("target_size") or 0) for row in resolved) / len(resolved)
        if resolved
        else 0.0
    )
    return {
        "total": len(rows),
        "pending": len(rows) - len(resolved),
        "resolved": len(resolved),
        "won": len(wins),
        "lost": losses,
        "assertiveness": round(len(wins) / len(resolved), 6) if resolved else 0.0,
        "average_target_size": round(average_target_size, 3),
        "simulation_attempts": int(max_attempts),
        "cohort_horizon": required_horizon,
        "exact_hits_by_attempt": exact_hits,
        "attempts": cumulative,
    }


def payout_multiplier(roulette_id: str, mode: str) -> Decimal:
    if mode == "table_base" and str(roulette_id) in MEGA_ROULETTES:
        return Decimal("30")
    return Decimal("36")


def simulate_profitability(
    trials: Iterable[Mapping[str, Any]],
    *,
    initial_bank: Decimal,
    attempt_stakes: Sequence[Decimal],
    max_attempts: int | None = None,
    cohort_horizon: int | None = None,
    payout_mode: str = "source_html",
    maximum_chart_points: int = 500,
) -> dict[str, Any]:
    if initial_bank <= 0:
        raise ValueError("a banca inicial precisa ser positiva")
    if not attempt_stakes or any(stake < 0 for stake in attempt_stakes):
        raise ValueError("as fichas das tentativas precisam ser não negativas")
    simulation_horizon = int(max_attempts or len(attempt_stakes))
    if not 1 <= simulation_horizon <= 10:
        raise ValueError("o horizonte precisa estar entre 1 e 10 tentativas")
    if len(attempt_stakes) < simulation_horizon:
        raise ValueError("faltam fichas para o horizonte solicitado")
    required_horizon = int(cohort_horizon or simulation_horizon)
    if required_horizon < simulation_horizon:
        raise ValueError("a coorte não pode terminar antes do horizonte simulado")
    rows = [row for row in trials if _is_mature(row, required_horizon)]
    cashflows: list[dict[str, Any]] = []
    for row in rows:
        target_size = int(row.get("target_size") or 0)
        if not 1 <= target_size <= 37:
            continue
        roulette_id = str(row.get("roulette_id") or "")
        event_id = str(row.get("event_id") or "")
        for attempt in _observed_attempts(row):
            attempt_number = int(attempt.get("attempt") or 0)
            if not 1 <= attempt_number <= simulation_horizon:
                continue
            stake = Decimal(attempt_stakes[attempt_number - 1])
            cost = stake * Decimal(target_size)
            returned = (
                stake * payout_multiplier(roulette_id, payout_mode)
                if bool(attempt.get("hit"))
                else Decimal("0")
            )
            cashflows.append(
                {
                    "timestamp": _utc(attempt.get("timestamp_utc")),
                    "event_id": event_id,
                    "attempt": attempt_number,
                    "roulette_id": roulette_id,
                    "cost": cost,
                    "returned": returned,
                }
            )
            if bool(attempt.get("hit")):
                break
    cashflows.sort(key=lambda row: (row["timestamp"], row["event_id"], row["attempt"]))

    bank = Decimal(initial_bank)
    starting_bank = bank
    peak = bank
    max_drawdown = Decimal("0")
    total_staked = Decimal("0")
    total_returned = Decimal("0")
    points = [{"event": 0, "bank": _money(bank), "net_profit": 0.0, "timestamp_utc": None}]
    for index, flow in enumerate(cashflows, start=1):
        bank -= flow["cost"]
        bank += flow["returned"]
        total_staked += flow["cost"]
        total_returned += flow["returned"]
        peak = max(peak, bank)
        max_drawdown = max(max_drawdown, peak - bank)
        points.append(
            {
                "event": index,
                "bank": _money(bank),
                "net_profit": _money(bank - starting_bank),
                "timestamp_utc": (
                    flow["timestamp"].isoformat()
                    if flow["timestamp"] != datetime.min.replace(tzinfo=timezone.utc)
                    else None
                ),
                "roulette_id": flow["roulette_id"],
                "attempt": flow["attempt"],
            }
        )

    safe_max = max(2, int(maximum_chart_points))
    if len(points) > safe_max:
        last = len(points) - 1
        indexes = sorted({round(position * last / (safe_max - 1)) for position in range(safe_max)})
        chart_points = [points[index] for index in indexes]
    else:
        chart_points = points
    net = bank - starting_bank
    return {
        "initial_bank": _money(starting_bank),
        "final_bank": _money(bank),
        "net_profit": _money(net),
        "total_staked": _money(total_staked),
        "total_returned": _money(total_returned),
        "roi_on_staked": round(float(net / total_staked), 6) if total_staked else 0.0,
        "max_drawdown": _money(max_drawdown),
        "resolved_signals": len(rows),
        "cashflow_events": len(cashflows),
        "payout_mode": payout_mode,
        "simulation_attempts": simulation_horizon,
        "cohort_horizon": required_horizon,
        "attempt_stakes": [
            float(value) for value in attempt_stakes[:simulation_horizon]
        ],
        "chart": {
            "points": chart_points,
            "points_total": len(points),
            "points_capped": len(chart_points) < len(points),
        },
    }


def compare_attempt_horizons(
    trials: Iterable[Mapping[str, Any]],
    *,
    minimum_attempts: int,
    maximum_attempts: int,
    common_cohort_horizon: int,
    initial_bank: Decimal,
    attempt_stakes: Sequence[Decimal],
    payout_mode: str = "source_html",
    maximum_chart_points: int = 500,
) -> list[dict[str, Any]]:
    rows = list(trials)
    if not 1 <= minimum_attempts <= maximum_attempts <= 10:
        raise ValueError("a comparação precisa estar entre 1 e 10 tentativas")
    return [
        {
            "attempts": horizon,
            "summary": summarize_trials(
                rows,
                max_attempts=horizon,
                cohort_horizon=common_cohort_horizon,
            ),
            "profitability": simulate_profitability(
                rows,
                initial_bank=initial_bank,
                attempt_stakes=attempt_stakes,
                max_attempts=horizon,
                cohort_horizon=common_cohort_horizon,
                payout_mode=payout_mode,
                maximum_chart_points=maximum_chart_points,
            ),
        }
        for horizon in range(minimum_attempts, maximum_attempts + 1)
    ]
