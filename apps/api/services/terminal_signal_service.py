from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping, Sequence

from bson import ObjectId
from pymongo import DESCENDING

from api.core.db import (
    history_coll,
    terminal_signal_trials_coll,
    terminal_signal_worker_state_coll,
)
from shared.python.roulette.terminal_signals.catalog import (
    COLLECTION_HORIZON,
    DEFAULT_ATTEMPT_STAKES,
    ENGINE_VERSION,
    VARIANTS,
    get_variant,
)
from shared.python.roulette.terminal_signals.performance import (
    compare_attempt_horizons,
    simulate_profitability,
    summarize_trials,
)
from shared.python.roulette.terminal_signals.strategy import (
    compare_strategy_matrix,
    simulate_table_strategy,
)


WINDOW_HOURS: dict[str, int | None] = {
    "1h": 1,
    "3h": 3,
    "6h": 6,
    "12h": 12,
    "24h": 24,
    "7d": 24 * 7,
    "all": None,
}


def _cutoff(window: str) -> datetime | None:
    if window not in WINDOW_HOURS:
        raise ValueError(f"janela inválida: {window}")
    hours = WINDOW_HOURS[window]
    return datetime.now(timezone.utc) - timedelta(hours=hours) if hours is not None else None


def _iso(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return value


def _analysis_payload(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not value:
        return None
    return {
        "motor": value.get("motor"),
        "idx0": value.get("idx0"),
        "idx1": value.get("idx1"),
        "terminal": value.get("terminal"),
        "reason": value.get("reason"),
        "metadata": dict(value.get("metadata") or {}),
    }


def serialize_trial(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("_id") or ""),
        "event_id": str(row.get("event_id") or ""),
        "engine_version": str(row.get("engine_version") or ""),
        "variant": str(row.get("variant") or ""),
        "roulette_id": str(row.get("roulette_id") or ""),
        "activation_history_id": str(row.get("activation_history_id") or ""),
        "activation_timestamp_utc": _iso(row.get("activation_timestamp_utc")),
        "activation_number": row.get("activation_number"),
        "activation_snapshot": [int(value) for value in row.get("activation_snapshot") or []],
        "terminal_a": row.get("terminal_a"),
        "terminal_b": row.get("terminal_b"),
        "motor_a": _analysis_payload(row.get("motor_a")),
        "motor_b": _analysis_payload(row.get("motor_b")),
        "targets": [int(value) for value in row.get("targets") or []],
        "target_size": int(row.get("target_size") or 0),
        "max_attempts": int(row.get("max_attempts") or COLLECTION_HORIZON),
        "collection_horizon": int(
            row.get("collection_horizon") or row.get("max_attempts") or 10
        ),
        "attempts": [
            {
                "attempt": int(attempt.get("attempt") or 0),
                "number": int(attempt.get("number") or 0),
                "history_id": str(attempt.get("history_id") or ""),
                "timestamp_utc": _iso(attempt.get("timestamp_utc")),
                "hit": bool(attempt.get("hit")),
            }
            for attempt in row.get("attempts") or []
        ],
        "first_hit_attempt": row.get("first_hit_attempt"),
        "first_hit_at_utc": _iso(row.get("first_hit_at_utc")),
        "attempts_observed": int(row.get("attempts_observed") or 0),
        "collection_status": str(
            row.get("collection_status")
            or ("complete" if row.get("status") == "resolved" else "collecting")
        ),
        "collection_completed_at_utc": _iso(row.get("collection_completed_at_utc")),
        "status": str(row.get("status") or ""),
        "outcome": str(row.get("outcome") or ""),
        "shadow_only": bool(row.get("shadow_only", True)),
        "created_at_utc": _iso(row.get("created_at_utc")),
        "resolved_at_utc": _iso(row.get("resolved_at_utc")),
    }


class TerminalSignalService:
    async def catalog(self) -> dict[str, Any]:
        pipeline = [
            {"$match": {"roulette_id": {"$regex": "^pragmatic-"}}},
            {
                "$group": {
                    "_id": "$roulette_id",
                    "worker_variants": {"$addToSet": "$worker_variant"},
                    "last_seen_at_utc": {"$max": "$last_timestamp_utc"},
                }
            },
            {"$sort": {"_id": 1}},
        ]
        rows = await terminal_signal_worker_state_coll.aggregate(pipeline).to_list(length=None)
        if not rows:
            roulette_ids = await history_coll.distinct(
                "roulette_id",
                {"roulette_id": {"$regex": "^pragmatic-"}},
            )
            rows = [{"_id": roulette_id} for roulette_id in sorted(roulette_ids)]
        return {
            "engine_version": ENGINE_VERSION,
            "collection_horizon": COLLECTION_HORIZON,
            "default_attempt_stakes": list(DEFAULT_ATTEMPT_STAKES),
            "variants": [variant.as_payload() for variant in VARIANTS],
            "roulettes": [
                {
                    "id": str(row["_id"]),
                    "name": str(row["_id"]).replace("pragmatic-", "").replace("-", " ").title(),
                    "history_count": None,
                    "monitored_variants": sorted(row.get("worker_variants") or []),
                    "last_seen_at_utc": _iso(row.get("last_seen_at_utc")),
                }
                for row in rows
            ],
            "generated_at_utc": datetime.now(timezone.utc),
        }

    @staticmethod
    def _query(
        variant: str,
        *,
        roulette_ids: Sequence[str] | None,
        window: str,
        status: str | None = None,
    ) -> dict[str, Any]:
        get_variant(variant)
        query: dict[str, Any] = {"variant": variant}
        if roulette_ids:
            query["roulette_id"] = {"$in": list(dict.fromkeys(map(str, roulette_ids)))}
        cutoff = _cutoff(window)
        if cutoff is not None:
            query["activation_timestamp_utc"] = {"$gte": cutoff}
        if status and status != "all":
            if status in {"won", "lost"}:
                query["outcome"] = status
            elif status == "pending":
                query["status"] = "pending"
            else:
                raise ValueError(f"status inválido: {status}")
        return query

    async def _summary_rows(
        self,
        variant: str,
        *,
        roulette_ids: Sequence[str] | None,
        window: str,
        maximum_records: int,
    ) -> list[dict[str, Any]]:
        query = self._query(variant, roulette_ids=roulette_ids, window=window)
        projection = {
            "_id": 0,
            "event_id": 1,
            "roulette_id": 1,
            "status": 1,
            "first_hit_attempt": 1,
            "attempts": 1,
            "attempts_observed": 1,
            "collection_horizon": 1,
            "target_size": 1,
            "activation_timestamp_utc": 1,
        }
        return await (
            terminal_signal_trials_coll.find(query, projection)
            .sort([("activation_timestamp_utc", DESCENDING), ("_id", DESCENDING)])
            .limit(maximum_records)
            .to_list(length=maximum_records)
        )

    async def summary(
        self,
        variant: str,
        *,
        roulette_ids: Sequence[str] | None,
        window: str,
        max_attempts: int = 2,
        maximum_records: int = 50_000,
    ) -> dict[str, Any]:
        spec = get_variant(variant)
        safe_attempts = max(2, min(COLLECTION_HORIZON, int(max_attempts)))
        safe_maximum = max(100, min(200_000, int(maximum_records)))
        rows = await self._summary_rows(
            variant,
            roulette_ids=roulette_ids,
            window=window,
            maximum_records=safe_maximum,
        )
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(str(row.get("roulette_id") or ""), []).append(row)
        breakdown = [
            {
                "roulette_id": roulette_id,
                **summarize_trials(group_rows, max_attempts=safe_attempts),
            }
            for roulette_id, group_rows in grouped.items()
            if roulette_id
        ]
        breakdown.sort(
            key=lambda row: (row["assertiveness"], row["resolved"], row["roulette_id"]),
            reverse=True,
        )
        return {
            "engine_version": ENGINE_VERSION,
            "variant": spec.as_payload(),
            "simulation_attempts": safe_attempts,
            "window": window,
            "roulette_ids": list(roulette_ids or []),
            "records_capped": len(rows) >= safe_maximum,
            "overall": summarize_trials(rows, max_attempts=safe_attempts),
            "by_roulette": breakdown,
            "generated_at_utc": datetime.now(timezone.utc),
        }

    async def history(
        self,
        variant: str,
        *,
        roulette_ids: Sequence[str] | None,
        window: str,
        status: str | None,
        limit: int,
        skip: int,
    ) -> dict[str, Any]:
        query = self._query(
            variant,
            roulette_ids=roulette_ids,
            window=window,
            status=status,
        )
        safe_limit = max(1, min(500, int(limit)))
        safe_skip = max(0, int(skip))
        total, rows = await asyncio.gather(
            terminal_signal_trials_coll.count_documents(query),
            terminal_signal_trials_coll.find(query)
            .sort([("activation_timestamp_utc", DESCENDING), ("_id", DESCENDING)])
            .skip(safe_skip)
            .limit(safe_limit)
            .to_list(length=safe_limit),
        )
        return {
            "total": int(total),
            "limit": safe_limit,
            "skip": safe_skip,
            "trials": [serialize_trial(row) for row in rows],
        }

    async def profitability(
        self,
        variant: str,
        *,
        roulette_ids: Sequence[str] | None,
        window: str,
        initial_bank: Decimal,
        attempt_stakes: Sequence[Decimal],
        max_attempts: int,
        payout_mode: str,
        maximum_records: int,
        maximum_chart_points: int,
    ) -> dict[str, Any]:
        spec = get_variant(variant)
        safe_attempts = max(2, min(COLLECTION_HORIZON, int(max_attempts)))
        safe_maximum = max(100, min(200_000, int(maximum_records)))
        query = self._query(
            variant,
            roulette_ids=roulette_ids,
            window=window,
            status=None,
        )
        query["attempts_observed"] = {"$gte": safe_attempts}
        rows = await (
            terminal_signal_trials_coll.find(
                query,
                {
                    "_id": 0,
                    "event_id": 1,
                    "roulette_id": 1,
                    "status": 1,
                    "target_size": 1,
                    "attempts": 1,
                    "attempts_observed": 1,
                    "activation_timestamp_utc": 1,
                },
            )
            .sort([("activation_timestamp_utc", DESCENDING), ("_id", DESCENDING)])
            .limit(safe_maximum)
            .to_list(length=safe_maximum)
        )
        result = simulate_profitability(
            rows,
            initial_bank=initial_bank,
            attempt_stakes=attempt_stakes,
            max_attempts=safe_attempts,
            payout_mode=payout_mode,
            maximum_chart_points=maximum_chart_points,
        )
        return {
            "engine_version": ENGINE_VERSION,
            "variant": spec.as_payload(),
            "simulation_attempts": safe_attempts,
            "window": window,
            "roulette_ids": list(roulette_ids or []),
            "records_capped": len(rows) >= safe_maximum,
            **result,
            "generated_at_utc": datetime.now(timezone.utc),
        }

    async def scenarios(
        self,
        variant: str,
        *,
        roulette_ids: Sequence[str] | None,
        window: str,
        initial_bank: Decimal,
        attempt_stakes: Sequence[Decimal],
        minimum_attempts: int,
        maximum_attempts: int,
        payout_mode: str,
        maximum_records: int,
        maximum_chart_points: int,
    ) -> dict[str, Any]:
        spec = get_variant(variant)
        minimum = max(2, min(COLLECTION_HORIZON, int(minimum_attempts)))
        maximum = max(minimum, min(COLLECTION_HORIZON, int(maximum_attempts)))
        if len(attempt_stakes) < maximum:
            raise ValueError("faltam fichas para a comparação solicitada")
        safe_maximum = max(100, min(200_000, int(maximum_records)))
        query = self._query(
            variant,
            roulette_ids=roulette_ids,
            window=window,
            status=None,
        )
        query["attempts_observed"] = {"$gte": maximum}
        rows = await (
            terminal_signal_trials_coll.find(
                query,
                {
                    "_id": 0,
                    "event_id": 1,
                    "roulette_id": 1,
                    "target_size": 1,
                    "attempts": 1,
                    "attempts_observed": 1,
                    "activation_timestamp_utc": 1,
                },
            )
            .sort([("activation_timestamp_utc", DESCENDING), ("_id", DESCENDING)])
            .limit(safe_maximum)
            .to_list(length=safe_maximum)
        )
        comparison = compare_attempt_horizons(
            rows,
            minimum_attempts=minimum,
            maximum_attempts=maximum,
            common_cohort_horizon=maximum,
            initial_bank=initial_bank,
            attempt_stakes=attempt_stakes,
            payout_mode=payout_mode,
            maximum_chart_points=maximum_chart_points,
        )
        best_roi = max(
            comparison,
            key=lambda item: item["profitability"]["roi_on_staked"],
            default=None,
        )
        best_profit = max(
            comparison,
            key=lambda item: item["profitability"]["net_profit"],
            default=None,
        )
        return {
            "engine_version": ENGINE_VERSION,
            "variant": spec.as_payload(),
            "window": window,
            "roulette_ids": list(roulette_ids or []),
            "common_cohort_horizon": maximum,
            "common_cohort_signals": len(rows),
            "records_capped": len(rows) >= safe_maximum,
            "best_roi_attempts": best_roi["attempts"] if best_roi else None,
            "best_profit_attempts": best_profit["attempts"] if best_profit else None,
            "scenarios": comparison,
            "generated_at_utc": datetime.now(timezone.utc),
        }

    async def strategy(
        self,
        variant: str,
        *,
        roulette_ids: Sequence[str] | None,
        window: str,
        selection_mode: str,
        ranking_lookback: int,
        tie_break_lookback: int,
        minimum_samples: int,
        minimum_assertiveness: Decimal,
        fixed_roulette_ids: Sequence[str] | None,
        max_attempts: int,
        minimum_attempts: int,
        maximum_attempts: int,
        comparison_modes: Sequence[str],
        initial_bank: Decimal,
        attempt_stakes: Sequence[Decimal],
        payout_mode: str,
        maximum_records: int,
        maximum_chart_points: int,
    ) -> dict[str, Any]:
        spec = get_variant(variant)
        safe_maximum = max(100, min(200_000, int(maximum_records)))
        safe_attempts = max(2, min(COLLECTION_HORIZON, int(max_attempts)))
        minimum = max(2, min(COLLECTION_HORIZON, int(minimum_attempts)))
        maximum = max(minimum, min(COLLECTION_HORIZON, int(maximum_attempts)))
        query: dict[str, Any] = {"variant": variant}
        universe = list(dict.fromkeys(map(str, roulette_ids or [])))
        if universe:
            query["roulette_id"] = {"$in": universe}
        rows = await (
            terminal_signal_trials_coll.find(
                query,
                {
                    "_id": 0,
                    "event_id": 1,
                    "roulette_id": 1,
                    "target_size": 1,
                    "attempts": 1,
                    "attempts_observed": 1,
                    "activation_timestamp_utc": 1,
                },
            )
            .sort([("activation_timestamp_utc", DESCENDING), ("_id", DESCENDING)])
            .limit(safe_maximum)
            .to_list(length=safe_maximum)
        )
        activation_cutoff = _cutoff(window)
        common = {
            "ranking_lookback": int(ranking_lookback),
            "tie_break_lookback": int(tie_break_lookback),
            "minimum_samples": int(minimum_samples),
            "minimum_assertiveness": float(minimum_assertiveness),
            "initial_bank": initial_bank,
            "attempt_stakes": attempt_stakes,
            "payout_mode": payout_mode,
            "common_cohort_horizon": maximum,
            "activation_cutoff": activation_cutoff,
            "fixed_roulette_ids": fixed_roulette_ids,
            "maximum_chart_points": maximum_chart_points,
        }
        modes = tuple(
            dict.fromkeys(
                [*map(str, comparison_modes), str(selection_mode)]
            )
        )
        matrix_results = compare_strategy_matrix(
            rows,
            max_attempts_values=tuple(range(minimum, maximum + 1)),
            selection_modes=modes,
            detailed_selection=(str(selection_mode), safe_attempts),
            **common,
        )
        selected = next(
            (
                item
                for item in matrix_results
                if item["selection_mode"] == selection_mode
                and item["max_attempts"] == safe_attempts
            ),
            None,
        )
        if selected is None:
            selected = simulate_table_strategy(
                rows,
                selection_mode=selection_mode,
                max_attempts=safe_attempts,
                **common,
            )
        matrix = [
            {
                "selection_mode": item["selection_mode"],
                "attempts": item["max_attempts"],
                "entries_considered": item["entries_considered"],
                "selected_signals": item["selected_signals"],
                "selection_rate": item["selection_rate"],
                "assertiveness": item["summary"]["assertiveness"],
                "won": item["summary"]["won"],
                "lost": item["summary"]["lost"],
                "net_profit": item["profitability"]["net_profit"],
                "roi_on_staked": item["profitability"]["roi_on_staked"],
                "total_staked": item["profitability"]["total_staked"],
                "max_drawdown": item["profitability"]["max_drawdown"],
            }
            for item in matrix_results
        ]
        eligible_matrix = [item for item in matrix if item["selected_signals"] > 0]
        best_roi = max(
            eligible_matrix,
            key=lambda item: item["roi_on_staked"],
            default=None,
        )
        best_profit = max(
            eligible_matrix,
            key=lambda item: item["net_profit"],
            default=None,
        )
        return {
            "engine_version": ENGINE_VERSION,
            "variant": spec.as_payload(),
            "window": window,
            "roulette_ids": universe,
            "records_loaded": len(rows),
            "records_capped": len(rows) >= safe_maximum,
            "common_cohort_horizon": maximum,
            "selected_strategy": selected,
            "matrix": matrix,
            "best_roi": best_roi,
            "best_profit": best_profit,
            "generated_at_utc": datetime.now(timezone.utc),
        }


terminal_signal_service = TerminalSignalService()
