"""Orquestracao do ranking atual e do backtest causal de probabilidades."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence
from typing import Any

from api.services.assertiveness_replay import fetch_history_desc
from shared.python.roulette.probability_model import calculate_number_probabilities


ROULETTE_SIZE = 37
MINIMUM_BACKTEST_HISTORY = 50
MAX_DETAIL_ROWS = 250


def _validate_history_desc(history_desc: Sequence[int]) -> list[int]:
    normalized: list[int] = []
    for raw in history_desc:
        if isinstance(raw, bool):
            raise ValueError("o historico deve conter inteiros entre 0 e 36")
        try:
            number = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("o historico deve conter inteiros entre 0 e 36") from exc
        if number != raw or not 0 <= number < ROULETTE_SIZE:
            raise ValueError("o historico deve conter inteiros entre 0 e 36")
        normalized.append(number)
    return normalized


def _wilson_interval(hits: int, total: int, z: float = 1.96) -> dict[str, float]:
    if total <= 0:
        return {"lower": 0.0, "upper": 0.0}
    proportion = hits / total
    denominator = 1.0 + (z**2 / total)
    center = (proportion + z**2 / (2.0 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            (proportion * (1.0 - proportion) / total)
            + (z**2 / (4.0 * total**2))
        )
        / denominator
    )
    return {
        "lower": max(0.0, center - margin),
        "upper": min(1.0, center + margin),
    }


def _profit_summary(
    rows: Sequence[dict[str, Any]],
    *,
    initial_bankroll: float,
    maximum_entry_exposure: float,
) -> dict[str, Any]:
    total_profit = sum(float(row["profit"]) for row in rows)
    total_staked = sum(float(row["invested"]) for row in rows)
    cumulative = 0.0
    peak_balance = float(initial_bankroll)
    peak_entry = 0
    minimum_balance = float(initial_bankroll)
    maximum_balance = float(initial_bankroll)
    max_drawdown = 0.0
    max_drawdown_percentage = 0.0
    max_drawdown_peak_entry = 0
    max_drawdown_trough_entry = 0
    required_bankroll = float(maximum_entry_exposure)
    curve = [
        {
            "entry": 0,
            "cumulative_profit": 0.0,
            "balance": round(float(initial_bankroll), 4),
            "drawdown": 0.0,
            "drawdown_percentage": 0.0,
        }
    ]
    for index, row in enumerate(rows, start=1):
        # Antes de cada entrada, a banca precisa suportar todas as tentativas
        # possiveis, pois o desfecho que encerrara a entrada ainda e desconhecido.
        required_bankroll = max(
            required_bankroll,
            float(maximum_entry_exposure) - cumulative,
        )
        cumulative += float(row["profit"])
        balance = float(initial_bankroll) + cumulative
        minimum_balance = min(minimum_balance, balance)
        maximum_balance = max(maximum_balance, balance)
        if balance > peak_balance:
            peak_balance = balance
            peak_entry = index
        drawdown = peak_balance - balance
        drawdown_percentage = drawdown / peak_balance if peak_balance > 0 else 0.0
        if drawdown > max_drawdown:
            max_drawdown = drawdown
            max_drawdown_percentage = drawdown_percentage
            max_drawdown_peak_entry = peak_entry
            max_drawdown_trough_entry = index
        curve.append(
            {
                "entry": index,
                "cumulative_profit": round(cumulative, 4),
                "balance": round(balance, 4),
                "drawdown": round(drawdown, 4),
                "drawdown_percentage": round(drawdown_percentage, 6),
            }
        )
    ending_bankroll = float(initial_bankroll) + total_profit
    bankroll_shortfall = max(0.0, required_bankroll - float(initial_bankroll))
    return {
        "total_profit": round(total_profit, 4),
        "total_staked": round(total_staked, 4),
        "roi": round(total_profit / total_staked, 6) if total_staked else 0.0,
        "initial_bankroll": round(float(initial_bankroll), 4),
        "ending_bankroll": round(ending_bankroll, 4),
        "minimum_balance": round(minimum_balance, 4),
        "maximum_balance": round(maximum_balance, 4),
        "max_drawdown": round(max_drawdown, 4),
        "max_drawdown_percentage": round(max_drawdown_percentage, 6),
        "max_drawdown_peak_entry": max_drawdown_peak_entry,
        "max_drawdown_trough_entry": max_drawdown_trough_entry,
        "maximum_entry_exposure": round(float(maximum_entry_exposure), 4),
        "required_bankroll": round(required_bankroll, 4),
        "bankroll_sufficient": float(initial_bankroll) >= required_bankroll,
        "bankroll_shortfall": round(bankroll_shortfall, 4),
        "curve": curve,
    }


def _summary_for_rows(
    rows: Sequence[dict[str, Any]],
    *,
    number_count: int,
    attempts: int,
) -> dict[str, Any]:
    total = len(rows)
    hits = sum(1 for row in rows if row["hit"])
    hit_rate = hits / total if total else 0.0
    random_rate = 1.0 - (1.0 - number_count / ROULETTE_SIZE) ** attempts
    return {
        "entries": total,
        "hits": hits,
        "misses": total - hits,
        "hit_rate": round(hit_rate, 6),
        "confidence_95": _wilson_interval(hits, total),
        "random_baseline": round(random_rate, 6),
        "lift_percentage_points": round((hit_rate - random_rate) * 100.0, 4),
    }


def run_probability_backtest_from_history(
    history_desc: Sequence[int],
    *,
    roulette_id: str,
    number_count: int = 10,
    attempts: int = 4,
    entries_limit: int = 300,
    minimum_history: int = 100,
    initial_bankroll: float = 1000.0,
) -> dict[str, Any]:
    """Executa replay walk-forward e recalcula o ranking apos cada tentativa.

    ``history_desc`` segue o contrato da API atual: o primeiro item e o giro
    mais recente. A inversao para ordem cronologica ocorre uma unica vez aqui.
    """

    if isinstance(number_count, bool) or not 1 <= int(number_count) <= 36:
        raise ValueError("number_count deve estar entre 1 e 36")
    if isinstance(attempts, bool) or not 1 <= int(attempts) <= 12:
        raise ValueError("attempts deve estar entre 1 e 12")
    if isinstance(entries_limit, bool) or not 1 <= int(entries_limit) <= 2000:
        raise ValueError("entries_limit deve estar entre 1 e 2000")
    if (
        isinstance(initial_bankroll, bool)
        or not math.isfinite(float(initial_bankroll))
        or not 0 < float(initial_bankroll) <= 1_000_000_000
    ):
        raise ValueError("initial_bankroll deve estar entre 0 e 1 bilhao")
    if (
        isinstance(minimum_history, bool)
        or not MINIMUM_BACKTEST_HISTORY <= int(minimum_history) <= 5000
    ):
        raise ValueError("minimum_history deve estar entre 50 e 5000")

    normalized_desc = _validate_history_desc(history_desc)
    required = int(minimum_history) + int(attempts)
    if len(normalized_desc) < required:
        raise LookupError(
            f"Historico insuficiente: recebidos {len(normalized_desc)}, minimo {required}."
        )

    chronological = list(reversed(normalized_desc))
    anchor_indexes = list(
        range(int(minimum_history) - 1, len(chronological) - int(attempts))
    )
    if len(anchor_indexes) > int(entries_limit):
        anchor_indexes = anchor_indexes[-int(entries_limit) :]

    rows: list[dict[str, Any]] = []
    hit_by_attempt = {attempt: 0 for attempt in range(1, int(attempts) + 1)}
    total_log_loss = 0.0
    prediction_count = 0

    for entry_index, anchor_index in enumerate(anchor_indexes, start=1):
        context = list(chronological[: anchor_index + 1])
        attempt_rows: list[dict[str, Any]] = []
        first_hit_attempt: int | None = None
        hit_number: int | None = None

        for attempt in range(1, int(attempts) + 1):
            actual_number = chronological[anchor_index + attempt]
            prediction = calculate_number_probabilities(
                context,
                order="chronological",
                number_count=int(number_count),
            )
            selected = [int(number) for number in prediction["selected"]]
            probability_by_number = {
                int(row["number"]): float(row["probability"])
                for row in prediction["ranking"]
            }
            actual_probability = max(1e-15, probability_by_number[actual_number])
            total_log_loss += -math.log(actual_probability)
            prediction_count += 1
            hit = actual_number in set(selected)
            attempt_rows.append(
                {
                    "attempt": attempt,
                    "trigger": int(context[-1]),
                    "context_size": len(context),
                    "selected": selected,
                    "selected_probability_mass": round(
                        float(prediction["selected_probability_mass"]), 8
                    ),
                    "actual_number": int(actual_number),
                    "actual_probability": round(actual_probability, 8),
                    "hit": hit,
                }
            )
            if hit:
                first_hit_attempt = attempt
                hit_number = int(actual_number)
                hit_by_attempt[attempt] += 1
                break

            # O resultado passa a fazer parte do passado antes da nova conta.
            context.append(int(actual_number))

        used_attempts = first_hit_attempt or int(attempts)
        invested = float(int(number_count) * used_attempts)
        profit = 36.0 - invested if first_hit_attempt else -invested
        rows.append(
            {
                "entry": entry_index,
                "anchor_index": anchor_index,
                "anchor_number": int(chronological[anchor_index]),
                "hit": first_hit_attempt is not None,
                "first_hit_attempt": first_hit_attempt,
                "hit_number": hit_number,
                "attempts_used": used_attempts,
                "invested": invested,
                "profit": profit,
                "attempt_details": attempt_rows,
            }
        )

    summary = _summary_for_rows(
        rows, number_count=int(number_count), attempts=int(attempts)
    )
    attempts_summary: list[dict[str, Any]] = []
    cumulative_hits = 0
    for attempt in range(1, int(attempts) + 1):
        first_hits = hit_by_attempt[attempt]
        cumulative_hits += first_hits
        observed_rate = cumulative_hits / len(rows) if rows else 0.0
        random_rate = 1.0 - (1.0 - int(number_count) / ROULETTE_SIZE) ** attempt
        attempts_summary.append(
            {
                "attempt": attempt,
                "first_hits": first_hits,
                "cumulative_hits": cumulative_hits,
                "cumulative_hit_rate": round(observed_rate, 6),
                "random_baseline": round(random_rate, 6),
                "lift_percentage_points": round(
                    (observed_rate - random_rate) * 100.0, 4
                ),
            }
        )

    non_overlapping_rows = rows[:: int(attempts)]
    average_log_loss = total_log_loss / prediction_count if prediction_count else 0.0
    return {
        "available": True,
        "engine_version": "central-probability-v1",
        "roulette_id": str(roulette_id),
        "causal": True,
        "recalculates_after_each_miss": True,
        "source_order": "newest_first",
        "internal_order": "chronological",
        "history_size": len(normalized_desc),
        "minimum_history": int(minimum_history),
        "number_count": int(number_count),
        "max_attempts": int(attempts),
        "evaluated_entries": len(rows),
        "summary": summary,
        "attempts": attempts_summary,
        "non_overlapping": {
            "step": int(attempts),
            **_summary_for_rows(
                non_overlapping_rows,
                number_count=int(number_count),
                attempts=int(attempts),
            ),
        },
        "probability_quality": {
            "average_log_loss": round(average_log_loss, 6),
            "uniform_log_loss": round(math.log(ROULETTE_SIZE), 6),
            "predictions_evaluated": prediction_count,
            "score_is_calibrated_probability": False,
        },
        "profit": _profit_summary(
            rows,
            initial_bankroll=float(initial_bankroll),
            maximum_entry_exposure=float(int(number_count) * int(attempts)),
        ),
        "profit_model": {
            "currency": "units",
            "unit_stake_per_number": 1.0,
            "initial_bankroll": round(float(initial_bankroll), 4),
            "straight_up_payout_to_one": 35,
            "flat_stake": True,
            "stop_after_first_hit": True,
        },
        "details": rows[-MAX_DETAIL_ROWS:],
        "details_truncated": len(rows) > MAX_DETAIL_ROWS,
    }


async def analyze_current_probability(
    *, roulette_id: str, history_limit: int, number_count: int
) -> dict[str, Any]:
    history_desc = await fetch_history_desc(roulette_id, history_limit)
    if not history_desc:
        raise LookupError(f"Nenhum resultado encontrado para {roulette_id}.")
    result = await asyncio.to_thread(
        calculate_number_probabilities,
        history_desc,
        order="newest_first",
        number_count=number_count,
    )
    return {**result, "roulette_id": roulette_id, "source": "mongodb"}


async def run_probability_backtest(
    *,
    roulette_id: str,
    history_limit: int,
    number_count: int,
    attempts: int,
    entries_limit: int,
    minimum_history: int,
    initial_bankroll: float,
) -> dict[str, Any]:
    history_desc = await fetch_history_desc(roulette_id, history_limit)
    if not history_desc:
        raise LookupError(f"Nenhum resultado encontrado para {roulette_id}.")
    return await asyncio.to_thread(
        run_probability_backtest_from_history,
        history_desc,
        roulette_id=roulette_id,
        number_count=number_count,
        attempts=attempts,
        entries_limit=entries_limit,
        minimum_history=minimum_history,
        initial_bankroll=initial_bankroll,
    )


__all__ = [
    "analyze_current_probability",
    "run_probability_backtest",
    "run_probability_backtest_from_history",
]
