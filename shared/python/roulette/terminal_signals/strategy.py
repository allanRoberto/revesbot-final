"""Simulação cronológica de seleção dinâmica de mesas.

O ranking de cada formação usa somente desfechos cujo resultado já era conhecido
antes da ativação. As formações podem se sobrepor e os fluxos financeiros
continuam ordenados pelos timestamps reais das tentativas.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from functools import lru_cache
from typing import Any, Iterable, Mapping, Sequence

from .performance import simulate_profitability, summarize_trials, wilson_interval
from .performance import payout_multiplier


SELECTION_MODES = ("all", "top3", "top1", "fixed")


def _utc(value: Any) -> datetime:
    if not isinstance(value, datetime):
        return datetime.min.replace(tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _attempts(row: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    cached = row.get("_strategy_attempts")
    if isinstance(cached, list):
        return cached
    return sorted(
        (
            attempt
            for attempt in row.get("attempts") or []
            if int(attempt.get("attempt") or 0) >= 1
        ),
        key=lambda attempt: int(attempt.get("attempt") or 0),
    )


def known_outcome(
    row: Mapping[str, Any],
    *,
    max_attempts: int,
) -> tuple[datetime, bool] | None:
    """Retorna quando o resultado do cenário ficou conhecido e se foi vitória."""

    observed = _attempts(row)
    for attempt in observed:
        number = int(attempt.get("attempt") or 0)
        if number > max_attempts:
            break
        if bool(attempt.get("hit")):
            return _utc(attempt.get("timestamp_utc")), True
    horizon = next(
        (
            attempt
            for attempt in observed
            if int(attempt.get("attempt") or 0) == max_attempts
        ),
        None,
    )
    if horizon is None:
        return None
    return _utc(horizon.get("timestamp_utc")), False


def _rank_tables(
    known_by_table: Mapping[str, Sequence[bool]],
    *,
    ranking_lookback: int,
    tie_break_lookback: int,
    minimum_samples: int,
    minimum_assertiveness: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for roulette_id, history in known_by_table.items():
        metrics = _rank_metrics(
            tuple(history[-tie_break_lookback:]),
            ranking_lookback,
            minimum_samples,
            minimum_assertiveness,
        )
        if metrics is None:
            continue
        (
            sample,
            wins,
            rate,
            lower,
            upper,
            tie_sample,
            tie_wins,
            tie_rate,
            tie_lower,
            tie_upper,
        ) = metrics
        rows.append(
            {
                "roulette_id": roulette_id,
                "sample": sample,
                "wins": wins,
                "losses": sample - wins,
                "assertiveness": rate,
                "confidence_lower": lower,
                "confidence_upper": upper,
                "tie_sample": tie_sample,
                "tie_wins": tie_wins,
                "tie_assertiveness": tie_rate,
                "tie_confidence_lower": tie_lower,
                "tie_confidence_upper": tie_upper,
            }
        )
    return _sort_ranking(rows)


def _sort_ranking(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    ranked = [dict(row) for row in rows]
    ranked.sort(
        key=lambda item: (
            item["confidence_lower"],
            item["assertiveness"],
            item["tie_confidence_lower"],
            item["tie_assertiveness"],
            item["sample"],
            item["roulette_id"],
        ),
        reverse=True,
    )
    for index, row in enumerate(ranked, start=1):
        row["rank"] = index
    return ranked


def _update_ranking(
    cache: dict[str, dict[str, Any]],
    known_by_table: Mapping[str, Sequence[bool]],
    changed_tables: set[str],
    *,
    ranking_lookback: int,
    tie_break_lookback: int,
    minimum_samples: int,
    minimum_assertiveness: float,
) -> list[dict[str, Any]]:
    for roulette_id in changed_tables:
        row = _rank_tables(
            {roulette_id: known_by_table[roulette_id]},
            ranking_lookback=ranking_lookback,
            tie_break_lookback=tie_break_lookback,
            minimum_samples=minimum_samples,
            minimum_assertiveness=minimum_assertiveness,
        )
        if row:
            cache[roulette_id] = row[0]
        else:
            cache.pop(roulette_id, None)
    return _sort_ranking(cache.values())


@lru_cache(maxsize=100_000)
def _rank_metrics(
    recent_outcomes: tuple[bool, ...],
    ranking_lookback: int,
    minimum_samples: int,
    minimum_assertiveness: float,
) -> tuple[int, int, float, float, float, int, int, float, float, float] | None:
    primary = recent_outcomes[-ranking_lookback:]
    if len(primary) < minimum_samples:
        return None
    wins = primary.count(True)
    rate = wins / len(primary)
    if rate < minimum_assertiveness:
        return None
    tie_wins = recent_outcomes.count(True)
    tie_rate = tie_wins / len(recent_outcomes) if recent_outcomes else 0.0
    lower, upper = wilson_interval(wins, len(primary))
    tie_lower, tie_upper = wilson_interval(tie_wins, len(recent_outcomes))
    return (
        len(primary),
        wins,
        round(rate, 6),
        round(lower, 6),
        round(upper, 6),
        len(recent_outcomes),
        tie_wins,
        round(tie_rate, 6),
        round(tie_lower, 6),
        round(tie_upper, 6),
    )


def _selected_tables(
    ranking: Sequence[Mapping[str, Any]],
    *,
    selection_mode: str,
    fixed_roulette_ids: set[str],
) -> tuple[str, ...]:
    if selection_mode == "top1":
        return (
            (str(ranking[0]["roulette_id"]),)
            if len(ranking) >= 1
            else ()
        )
    if selection_mode == "top3":
        return (
            tuple(str(item["roulette_id"]) for item in ranking[:3])
            if len(ranking) >= 3
            else ()
        )
    if selection_mode == "fixed":
        return tuple(sorted(fixed_roulette_ids))
    return ()


def _build_evaluation(
    rows: Sequence[Mapping[str, Any]],
    *,
    max_attempts: int,
    ranking_lookback: int,
    tie_break_lookback: int,
    minimum_samples: int,
    minimum_assertiveness: float,
    common_cohort_horizon: int,
    activation_cutoff: datetime | None,
    needs_historical_ranking: bool,
) -> dict[str, Any]:
    entries = [
        row
        for row in rows
        if int(row.get("attempts_observed") or len(_attempts(row)))
        >= common_cohort_horizon
        and (
            activation_cutoff is None
            or _utc(row.get("activation_timestamp_utc")) >= _utc(activation_cutoff)
        )
    ]
    entries.sort(
        key=lambda row: (
            _utc(row.get("activation_timestamp_utc")),
            str(row.get("event_id") or ""),
        )
    )

    outcomes: list[tuple[datetime, str, bool, str]] = []
    for row in rows:
        known = known_outcome(row, max_attempts=max_attempts)
        if known is None:
            continue
        known_at, won = known
        outcomes.append(
            (
                known_at,
                str(row.get("roulette_id") or ""),
                won,
                str(row.get("event_id") or ""),
            )
        )
    outcomes.sort(key=lambda item: (item[0], item[3]))

    known_by_table: dict[str, list[bool]] = defaultdict(list)
    ranking_cache: dict[str, dict[str, Any]] = {}
    ranking: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    outcome_index = 0
    if needs_historical_ranking:
        for entry in entries:
            activation = _utc(entry.get("activation_timestamp_utc"))
            changed_tables: set[str] = set()
            while (
                outcome_index < len(outcomes)
                and outcomes[outcome_index][0] < activation
            ):
                known_at, roulette_id, won, _ = outcomes[outcome_index]
                known_by_table[roulette_id].append(won)
                changed_tables.add(roulette_id)
                outcome_index += 1
            if changed_tables:
                ranking = _update_ranking(
                    ranking_cache,
                    known_by_table,
                    changed_tables,
                    ranking_lookback=ranking_lookback,
                    tie_break_lookback=tie_break_lookback,
                    minimum_samples=minimum_samples,
                    minimum_assertiveness=minimum_assertiveness,
                )
            decisions.append(
                {
                    "entry": entry,
                    "top1": _selected_tables(
                        ranking,
                        selection_mode="top1",
                        fixed_roulette_ids=set(),
                    ),
                    "top3": _selected_tables(
                        ranking,
                        selection_mode="top3",
                        fixed_roulette_ids=set(),
                    ),
                }
            )
    else:
        decisions = [{"entry": entry, "top1": (), "top3": ()} for entry in entries]

    now = datetime.now(timezone.utc)
    current_changes: set[str] = set()
    while outcome_index < len(outcomes) and outcomes[outcome_index][0] <= now:
        known_at, roulette_id, won, _ = outcomes[outcome_index]
        known_by_table[roulette_id].append(won)
        current_changes.add(roulette_id)
        outcome_index += 1
    if current_changes:
        current_ranking = _update_ranking(
            ranking_cache,
            known_by_table,
            current_changes,
            ranking_lookback=ranking_lookback,
            tie_break_lookback=tie_break_lookback,
            minimum_samples=minimum_samples,
            minimum_assertiveness=minimum_assertiveness,
        )
    else:
        current_ranking = ranking
    return {
        "entries": entries,
        "decisions": decisions,
        "current_ranking": current_ranking,
    }


def _compact_performance(
    rows: Sequence[Mapping[str, Any]],
    *,
    initial_bank: Decimal,
    attempt_stakes: Sequence[Decimal],
    max_attempts: int,
    payout_mode: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    wins = 0
    cashflows: list[tuple[datetime, str, int, Decimal, Decimal]] = []
    for row in rows:
        target_size = int(row.get("target_size") or 0)
        if not 1 <= target_size <= 37:
            continue
        event_id = str(row.get("event_id") or "")
        roulette_id = str(row.get("roulette_id") or "")
        for attempt in _attempts(row):
            number = int(attempt.get("attempt") or 0)
            if number > max_attempts:
                break
            stake = Decimal(attempt_stakes[number - 1])
            hit = bool(attempt.get("hit"))
            cashflows.append(
                (
                    _utc(attempt.get("timestamp_utc")),
                    event_id,
                    number,
                    stake * Decimal(target_size),
                    stake * payout_multiplier(roulette_id, payout_mode)
                    if hit
                    else Decimal("0"),
                )
            )
            if hit:
                wins += 1
                break
    cashflows.sort(key=lambda item: (item[0], item[1], item[2]))
    bank = Decimal(initial_bank)
    peak = bank
    drawdown = Decimal("0")
    total_staked = Decimal("0")
    total_returned = Decimal("0")
    for _, _, _, cost, returned in cashflows:
        bank += returned - cost
        total_staked += cost
        total_returned += returned
        peak = max(peak, bank)
        drawdown = max(drawdown, peak - bank)
    net = bank - Decimal(initial_bank)
    resolved = len(rows)
    summary = {
        "resolved": resolved,
        "won": wins,
        "lost": resolved - wins,
        "assertiveness": round(wins / resolved, 6) if resolved else 0.0,
    }
    profitability = {
        "net_profit": round(float(net), 2),
        "roi_on_staked": (
            round(float(net / total_staked), 6) if total_staked else 0.0
        ),
        "total_staked": round(float(total_staked), 2),
        "total_returned": round(float(total_returned), 2),
        "max_drawdown": round(float(drawdown), 2),
    }
    return summary, profitability


def simulate_table_strategy(
    trials: Iterable[Mapping[str, Any]],
    *,
    selection_mode: str,
    max_attempts: int,
    ranking_lookback: int,
    tie_break_lookback: int,
    minimum_samples: int,
    minimum_assertiveness: float,
    initial_bank: Decimal,
    attempt_stakes: Sequence[Decimal],
    payout_mode: str,
    common_cohort_horizon: int = 10,
    activation_cutoff: datetime | None = None,
    fixed_roulette_ids: Sequence[str] | None = None,
    maximum_chart_points: int = 500,
    _evaluation: Mapping[str, Any] | None = None,
    _include_details: bool = True,
) -> dict[str, Any]:
    if selection_mode not in SELECTION_MODES:
        raise ValueError(f"modo de seleção inválido: {selection_mode}")
    if not 2 <= int(max_attempts) <= 10:
        raise ValueError("as tentativas da estratégia precisam estar entre 2 e 10")
    if not 1 <= int(minimum_samples) <= int(ranking_lookback):
        raise ValueError("a amostra mínima precisa caber na janela principal")
    if tie_break_lookback < ranking_lookback:
        raise ValueError("a janela de desempate não pode ser menor que a principal")
    if not 0 <= float(minimum_assertiveness) <= 1:
        raise ValueError("a assertividade mínima precisa estar entre 0 e 1")

    fixed_ids = {str(value) for value in fixed_roulette_ids or [] if str(value)}
    rows = [
        dict(row)
        for row in trials
        if str(row.get("roulette_id") or "")
    ]
    evaluation = dict(
        _evaluation
        or _build_evaluation(
            rows,
            max_attempts=max_attempts,
            ranking_lookback=ranking_lookback,
            tie_break_lookback=tie_break_lookback,
            minimum_samples=minimum_samples,
            minimum_assertiveness=minimum_assertiveness,
            common_cohort_horizon=common_cohort_horizon,
            activation_cutoff=activation_cutoff,
            needs_historical_ranking=selection_mode in {"top1", "top3"},
        )
    )
    entries = list(evaluation["entries"])
    selected_rows: list[dict[str, Any]] = []
    rejected_no_ranking = 0
    rejected_not_selected = 0
    selection_changes: list[dict[str, Any]] = []
    previous_selection: tuple[str, ...] | None = None

    for decision in evaluation["decisions"]:
        entry = decision["entry"]
        activation = _utc(entry.get("activation_timestamp_utc"))
        selected_tables = tuple(decision.get(selection_mode) or ())
        if selection_mode == "fixed":
            selected_tables = tuple(sorted(fixed_ids))
        if selection_mode in {"top1", "top3"} and selected_tables != previous_selection:
            selection_changes.append(
                {
                    "timestamp_utc": activation.isoformat(),
                    "tables": list(selected_tables),
                }
            )
            previous_selection = selected_tables

        if selection_mode == "all":
            selected_rows.append(entry)
        elif selection_mode == "fixed":
            if str(entry.get("roulette_id")) in fixed_ids:
                selected_rows.append(entry)
            else:
                rejected_not_selected += 1
        elif not selected_tables:
            rejected_no_ranking += 1
        elif str(entry.get("roulette_id")) in selected_tables:
            selected_rows.append(entry)
        else:
            rejected_not_selected += 1

    current_ranking = [dict(row) for row in evaluation["current_ranking"]]
    current_selected = _selected_tables(
        current_ranking,
        selection_mode=selection_mode,
        fixed_roulette_ids=fixed_ids,
    )
    for row in current_ranking:
        row["selected_now"] = str(row["roulette_id"]) in current_selected

    if _include_details:
        summary = summarize_trials(
            selected_rows,
            max_attempts=max_attempts,
            cohort_horizon=common_cohort_horizon,
        )
        profitability = simulate_profitability(
            selected_rows,
            initial_bank=initial_bank,
            attempt_stakes=attempt_stakes,
            max_attempts=max_attempts,
            cohort_horizon=common_cohort_horizon,
            payout_mode=payout_mode,
            maximum_chart_points=maximum_chart_points,
        )
    else:
        summary, profitability = _compact_performance(
            selected_rows,
            initial_bank=initial_bank,
            attempt_stakes=attempt_stakes,
            max_attempts=max_attempts,
            payout_mode=payout_mode,
        )
    return {
        "selection_mode": selection_mode,
        "max_attempts": int(max_attempts),
        "ranking_lookback": int(ranking_lookback),
        "tie_break_lookback": int(tie_break_lookback),
        "minimum_samples": int(minimum_samples),
        "minimum_assertiveness": round(float(minimum_assertiveness), 6),
        "common_cohort_horizon": int(common_cohort_horizon),
        "entries_considered": len(entries),
        "selected_signals": len(selected_rows),
        "rejected_no_ranking": rejected_no_ranking,
        "rejected_not_selected": rejected_not_selected,
        "selection_rate": round(
            len(selected_rows) / len(entries) if entries else 0.0,
            6,
        ),
        "current_selected_tables": list(current_selected),
        "current_ranking": current_ranking,
        "selection_changes": selection_changes[-100:],
        "selected_event_ids": [
            str(row.get("event_id") or "") for row in selected_rows[-500:]
        ],
        "summary": summary,
        "profitability": profitability,
    }


def compare_strategy_matrix(
    trials: Iterable[Mapping[str, Any]],
    *,
    max_attempts_values: Sequence[int],
    selection_modes: Sequence[str],
    ranking_lookback: int,
    tie_break_lookback: int,
    minimum_samples: int,
    minimum_assertiveness: float,
    initial_bank: Decimal,
    attempt_stakes: Sequence[Decimal],
    payout_mode: str,
    common_cohort_horizon: int,
    activation_cutoff: datetime | None,
    fixed_roulette_ids: Sequence[str] | None = None,
    maximum_chart_points: int = 500,
    detailed_selection: tuple[str, int] | None = None,
) -> list[dict[str, Any]]:
    rows = []
    for source in trials:
        row = dict(source)
        row["_strategy_attempts"] = _attempts(row)
        rows.append(row)
    modes = tuple(dict.fromkeys(selection_modes))
    results: list[dict[str, Any]] = []
    for attempts in max_attempts_values:
        evaluation = _build_evaluation(
            rows,
            max_attempts=attempts,
            ranking_lookback=ranking_lookback,
            tie_break_lookback=tie_break_lookback,
            minimum_samples=minimum_samples,
            minimum_assertiveness=minimum_assertiveness,
            common_cohort_horizon=common_cohort_horizon,
            activation_cutoff=activation_cutoff,
            needs_historical_ranking=bool({"top1", "top3"}.intersection(modes)),
        )
        for mode in modes:
            results.append(
                simulate_table_strategy(
                    rows,
                    selection_mode=mode,
                    max_attempts=attempts,
                    ranking_lookback=ranking_lookback,
                    tie_break_lookback=tie_break_lookback,
                    minimum_samples=minimum_samples,
                    minimum_assertiveness=minimum_assertiveness,
                    initial_bank=initial_bank,
                    attempt_stakes=attempt_stakes,
                    payout_mode=payout_mode,
                    common_cohort_horizon=common_cohort_horizon,
                    activation_cutoff=activation_cutoff,
                    fixed_roulette_ids=fixed_roulette_ids,
                    maximum_chart_points=maximum_chart_points,
                    _evaluation=evaluation,
                    _include_details=detailed_selection == (mode, attempts),
                )
            )
    return results
