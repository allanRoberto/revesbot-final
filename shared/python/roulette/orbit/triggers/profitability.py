"""Simulacao financeira prospectiva para entradas de gatilho orbital."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, getcontext
from typing import Any, Iterable, Mapping, Sequence


getcontext().prec = 28

MONEY = Decimal("0.01")
PAYOUT_MULTIPLIER = Decimal("36")


def _decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _money(value: Decimal) -> float:
    return float(value.quantize(MONEY, rounding=ROUND_HALF_UP))


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _downsample(points: Sequence[dict[str, Any]], maximum: int) -> list[dict[str, Any]]:
    safe_maximum = max(2, int(maximum))
    if len(points) <= safe_maximum:
        return list(points)
    last_index = len(points) - 1
    indexes = {
        round(position * last_index / (safe_maximum - 1))
        for position in range(safe_maximum)
    }
    indexes.add(0)
    indexes.add(last_index)
    return [points[index] for index in sorted(indexes)]


def simulate_trigger_profitability(
    trials: Iterable[Mapping[str, Any]],
    *,
    initial_bank: Decimal | float | int | str,
    attempt_stakes: Sequence[Decimal | float | int | str],
    max_attempts: int = 5,
    payout_multiplier: Decimal | float | int | str = PAYOUT_MULTIPLIER,
    maximum_chart_points: int = 400,
) -> dict[str, Any]:
    """Simula uma entrada por sinal, parando no primeiro acerto.

    Cada valor de ``attempt_stakes`` representa o total investido naquela
    tentativa. O total e dividido igualmente entre os numeros protegidos.
    """

    safe_attempts = max(1, min(20, int(max_attempts)))
    if len(attempt_stakes) != safe_attempts:
        raise ValueError(f"informe exatamente {safe_attempts} valores de entrada")

    bank = _decimal(initial_bank)
    if bank <= 0:
        raise ValueError("a banca inicial precisa ser positiva")
    starting_bank = bank
    stakes = tuple(_decimal(value) for value in attempt_stakes)
    if any(value < 0 for value in stakes):
        raise ValueError("os valores por tentativa nao podem ser negativos")
    multiplier = _decimal(payout_multiplier)
    if multiplier <= 0:
        raise ValueError("o multiplicador de pagamento precisa ser positivo")

    rows = list(trials)
    rows.sort(
        key=lambda trial: _utc(trial.get("activation_timestamp_utc"))
        or datetime.min.replace(tzinfo=timezone.utc)
    )

    total_staked = Decimal("0")
    total_returned = Decimal("0")
    peak_bank = bank
    max_drawdown = Decimal("0")
    max_drawdown_rate = Decimal("0")
    wins = 0
    losses = 0
    signals_started = 0
    signals_completed = 0
    exact_hits = [0] * safe_attempts
    bankrupt = False
    bankroll_stop: dict[str, int] | None = None
    points: list[dict[str, Any]] = [
        {
            "signal": 0,
            "bank": _money(bank),
            "net_profit": 0.0,
            "timestamp_utc": None,
        }
    ]

    def update_drawdown() -> None:
        nonlocal peak_bank, max_drawdown, max_drawdown_rate
        peak_bank = max(peak_bank, bank)
        current_drawdown = peak_bank - bank
        max_drawdown = max(max_drawdown, current_drawdown)
        if peak_bank:
            max_drawdown_rate = max(max_drawdown_rate, current_drawdown / peak_bank)

    for signal_index, trial in enumerate(rows, start=1):
        target_size = int(trial.get("target_size") or 0)
        if not 1 <= target_size <= 37:
            raise ValueError(f"quantidade de alvos invalida no sinal {signal_index}: {target_size}")
        raw_first_hit = trial.get("first_hit_attempt")
        first_hit = int(raw_first_hit) if raw_first_hit is not None else None
        if first_hit is not None and not 1 <= first_hit <= safe_attempts:
            raise ValueError(f"tentativa de acerto invalida no sinal {signal_index}: {first_hit}")

        signals_started += 1
        completed = True
        for attempt in range(1, (first_hit or safe_attempts) + 1):
            stake = stakes[attempt - 1]
            if bank < stake:
                bankrupt = True
                completed = False
                bankroll_stop = {"signal": signal_index, "attempt": attempt}
                break
            bank -= stake
            total_staked += stake
            update_drawdown()
            if first_hit == attempt:
                gross_return = (stake / Decimal(target_size)) * multiplier
                bank += gross_return
                total_returned += gross_return
                exact_hits[attempt - 1] += 1
                wins += 1
                update_drawdown()
                break

        timestamp = _utc(trial.get("activation_timestamp_utc"))
        if completed:
            signals_completed += 1
            if first_hit is None:
                losses += 1
        points.append(
            {
                "signal": signal_index,
                "bank": _money(bank),
                "net_profit": _money(bank - starting_bank),
                "timestamp_utc": timestamp.isoformat() if timestamp else None,
            }
        )
        if bankrupt:
            break

    net_profit = bank - starting_bank
    roi_on_staked = net_profit / total_staked if total_staked else Decimal("0")
    bank_growth = net_profit / starting_bank
    chart_points = _downsample(points, maximum_chart_points)

    return {
        "initial_bank": _money(starting_bank),
        "final_bank": _money(bank),
        "net_profit": _money(net_profit),
        "roi_on_staked": round(float(roi_on_staked), 6),
        "bank_growth": round(float(bank_growth), 6),
        "total_staked": _money(total_staked),
        "total_returned": _money(total_returned),
        "signals_available": len(rows),
        "signals_started": signals_started,
        "signals_completed": signals_completed,
        "winning_signals": wins,
        "losing_signals": losses,
        "unplayed_signals": max(0, len(rows) - signals_started),
        "exact_hits_by_attempt": [
            {"attempt": index + 1, "hits": hits}
            for index, hits in enumerate(exact_hits)
        ],
        "max_drawdown": _money(max_drawdown),
        "max_drawdown_rate": round(float(max_drawdown_rate), 6),
        "bankroll_insufficient": bankrupt,
        "bankroll_stop": bankroll_stop,
        "chart": {
            "points": chart_points,
            "points_total": len(points),
            "points_capped": len(chart_points) < len(points),
        },
        "assumptions": {
            "stake_mode": "total_per_attempt_evenly_split_by_target",
            "stop_after_first_hit": True,
            "payout_multiplier_gross": float(multiplier),
            "currency": "BRL",
        },
    }
