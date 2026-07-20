from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from shared.python.roulette.orbit.triggers.catalog import (
    DEFAULT_MAX_ATTEMPTS,
    STRATEGIES,
    TRIGGER_ENGINE_VERSION,
    get_strategy,
)
from shared.python.roulette.orbit.triggers.performance import (
    build_trigger_performance_summary,
)

from api.core.db import orbit_trigger_candidates_coll, orbit_trigger_trials_coll


def _as_utc(value: Any) -> Any:
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def serialize_trigger_trial(trial: Mapping[str, Any]) -> dict[str, Any]:
    entry_numbers = [int(value) for value in trial.get("entry_numbers") or []]
    base_numbers = [int(value) for value in trial.get("base_numbers") or []]
    numbers = [int(value) for value in trial.get("attempt_numbers") or []]
    timestamps = list(trial.get("attempt_timestamps_utc") or [])
    first_hit_raw = trial.get("first_hit_attempt")
    first_hit = int(first_hit_raw) if first_hit_raw is not None else None
    status = str(trial.get("status") or "pending")
    attempts = [
        {
            "attempt": index + 1,
            "number": number,
            "timestamp_utc": _as_utc(timestamps[index]) if index < len(timestamps) else None,
            "match": number in entry_numbers,
        }
        for index, number in enumerate(numbers)
    ]
    hit_timestamp = None
    if first_hit is not None and first_hit <= len(timestamps):
        hit_timestamp = _as_utc(timestamps[first_hit - 1])
    outcome_status = "hit" if first_hit is not None else ("miss" if status == "resolved" else "pending")
    return {
        "event_id": str(trial.get("event_id") or ""),
        "engine_version": str(trial.get("engine_version") or ""),
        "strategy_slug": str(trial.get("strategy_slug") or ""),
        "roulette_id": str(trial.get("roulette_id") or ""),
        "activation_history_id": str(trial.get("activation_history_id") or ""),
        "activation_timestamp_utc": _as_utc(trial.get("activation_timestamp_utc")),
        "activation_number": trial.get("activation_number"),
        "activation_prediction_id": str(trial.get("activation_prediction_id") or ""),
        "source_trial_id": str(trial.get("source_trial_id") or ""),
        "recent_pivots": [int(value) for value in trial.get("recent_pivots") or []],
        "base_numbers": base_numbers,
        "entry_numbers": entry_numbers,
        "target_size": int(trial.get("target_size") or len(entry_numbers)),
        "metadata": dict(trial.get("metadata") or {}),
        "attempts": attempts,
        "attempts_observed": len(numbers),
        "max_attempts": int(trial.get("max_attempts") or DEFAULT_MAX_ATTEMPTS),
        "status": status,
        "display_status": outcome_status,
        "outcome": {
            "status": outcome_status,
            "first_hit_attempt": first_hit,
            "first_hit_timestamp_utc": hit_timestamp,
        },
    }


class OrbitTriggerService:
    async def summarize(
        self,
        strategy_slug: str,
        roulette_ids: Sequence[str],
        *,
        maximum_records: int = 50_000,
    ) -> dict[str, Any]:
        get_strategy(strategy_slug)
        ids = [str(value) for value in roulette_ids]
        safe_maximum = max(100, min(200_000, int(maximum_records)))
        query: dict[str, Any] = {
            "strategy_slug": strategy_slug,
            "roulette_id": {"$in": ids},
            "status": "resolved",
            "attempts_observed": {"$gte": DEFAULT_MAX_ATTEMPTS},
        }
        projection = {
            "_id": 0,
            "activation_timestamp_utc": 1,
            "attempts_observed": 1,
            "first_hit_attempt": 1,
            "status": 1,
            "target_size": 1,
        }
        rows, pending, total, active_candidates, latest = await asyncio.gather(
            orbit_trigger_trials_coll.find(query, projection)
            .sort([("activation_timestamp_utc", -1), ("_id", -1)])
            .limit(safe_maximum)
            .to_list(length=safe_maximum),
            orbit_trigger_trials_coll.count_documents(
                {
                    "strategy_slug": strategy_slug,
                    "roulette_id": {"$in": ids},
                    "status": "pending",
                }
            ),
            orbit_trigger_trials_coll.count_documents(
                {"strategy_slug": strategy_slug, "roulette_id": {"$in": ids}}
            ),
            orbit_trigger_candidates_coll.count_documents(
                {
                    "strategy_slug": strategy_slug,
                    "roulette_id": {"$in": ids},
                    "status": "armed",
                }
            ),
            orbit_trigger_trials_coll.find_one(
                {"strategy_slug": strategy_slug, "roulette_id": {"$in": ids}},
                {"_id": 0, "activation_timestamp_utc": 1},
                sort=[("activation_timestamp_utc", -1), ("_id", -1)],
            ),
        )
        return {
            "strategy_slug": strategy_slug,
            "available": bool(rows or pending),
            "total_trials": int(total),
            "pending_trials": int(pending),
            "active_candidates": int(active_candidates),
            "latest_activation_timestamp_utc": (
                _as_utc(latest.get("activation_timestamp_utc")) if latest else None
            ),
            "records_capped": len(rows) >= safe_maximum,
            **build_trigger_performance_summary(
                rows,
                now=datetime.now(timezone.utc),
                max_attempts=DEFAULT_MAX_ATTEMPTS,
            ),
        }

    async def history(
        self,
        strategy_slug: str,
        roulette_id: str,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        get_strategy(strategy_slug)
        safe_limit = max(1, min(50, int(limit)))
        rows = await (
            orbit_trigger_trials_coll.find(
                {"strategy_slug": strategy_slug, "roulette_id": str(roulette_id)},
                {"_id": 0},
            )
            .sort([("activation_timestamp_utc", -1), ("_id", -1)])
            .limit(safe_limit)
            .to_list(length=safe_limit)
        )
        return [serialize_trigger_trial(row) for row in rows]

    async def roulette_detail(
        self,
        strategy_slug: str,
        roulette_id: str,
        *,
        history_limit: int = 20,
    ) -> dict[str, Any]:
        performance, history = await asyncio.gather(
            self.summarize(strategy_slug, [roulette_id]),
            self.history(strategy_slug, roulette_id, limit=history_limit),
        )
        return {
            "roulette_id": str(roulette_id),
            "performance": performance,
            "history": history,
        }

    async def detail(
        self,
        strategy_slug: str,
        roulette_ids: Sequence[str],
        *,
        history_limit: int = 20,
    ) -> dict[str, Any]:
        strategy = get_strategy(strategy_slug)
        ids = tuple(dict.fromkeys(str(value) for value in roulette_ids))
        overall, roulettes = await asyncio.gather(
            self.summarize(strategy_slug, ids),
            asyncio.gather(
                *(
                    self.roulette_detail(
                        strategy_slug,
                        roulette_id,
                        history_limit=history_limit,
                    )
                    for roulette_id in ids
                )
            ),
        )
        return {
            "engine_version": TRIGGER_ENGINE_VERSION,
            "strategy": strategy.as_payload(),
            "overall": overall,
            "roulettes": list(roulettes),
            "generated_at": datetime.now(timezone.utc),
        }

    async def catalog(self, roulette_ids: Sequence[str]) -> dict[str, Any]:
        ids = tuple(dict.fromkeys(str(value) for value in roulette_ids))
        summaries = await asyncio.gather(
            *(self.summarize(strategy.slug, ids) for strategy in STRATEGIES)
        )
        return {
            "engine_version": TRIGGER_ENGINE_VERSION,
            "max_attempts": DEFAULT_MAX_ATTEMPTS,
            "strategies": [
                {**strategy.as_payload(), "performance": summary}
                for strategy, summary in zip(STRATEGIES, summaries)
            ],
            "generated_at": datetime.now(timezone.utc),
        }


orbit_trigger_service = OrbitTriggerService()
