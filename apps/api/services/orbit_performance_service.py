from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Sequence

from shared.python.roulette.orbit.performance import build_performance_summary

from api.core.db import orbit_prediction_trials_coll


def serialize_trial_history(trial: Dict[str, Any]) -> Dict[str, Any]:
    top9 = [int(value) for value in trial.get("top9") or []]
    top12 = [int(value) for value in trial.get("top12") or []]
    numbers = [int(value) for value in trial.get("attempt_numbers") or []]
    timestamps = list(trial.get("attempt_timestamps_utc") or [])
    top9_first = trial.get("top9_first_hit_attempt")
    top12_first = trial.get("top12_first_hit_attempt")
    top9_first = int(top9_first) if top9_first is not None else None
    top12_first = int(top12_first) if top12_first is not None else None
    attempts = [
        {
            "attempt": index + 1,
            "number": number,
            "timestamp_utc": timestamps[index] if index < len(timestamps) else None,
            "top9_match": number in top9,
            "top12_match": number in top12,
            "top12_only_match": number in top12 and number not in top9,
        }
        for index, number in enumerate(numbers)
    ]
    status = str(trial.get("status") or "pending")

    def outcome(first_hit: int | None) -> Dict[str, Any]:
        hit_timestamp = None
        if first_hit is not None and first_hit <= len(timestamps):
            hit_timestamp = timestamps[first_hit - 1]
        return {
            "status": "hit" if first_hit is not None else ("miss" if status == "resolved" else "pending"),
            "first_hit_attempt": first_hit,
            "first_hit_timestamp_utc": hit_timestamp,
        }

    if top9_first is not None:
        display_status = "top9_hit"
    elif top12_first is not None:
        display_status = "top12_hit"
    elif status == "resolved":
        display_status = "miss"
    else:
        display_status = "pending"
    recent_pivots = [int(value) for value in trial.get("recent_pivots") or []]
    return {
        "trial_id": str(trial.get("trial_id") or ""),
        "roulette_id": str(trial.get("roulette_id") or ""),
        "anchor_history_id": str(trial.get("anchor_history_id") or ""),
        "anchor_timestamp_utc": trial.get("anchor_timestamp_utc"),
        "anchor_number": recent_pivots[0] if recent_pivots else None,
        "recent_pivots": recent_pivots,
        "top9": top9,
        "top12": top12,
        "attempts": attempts,
        "attempts_observed": len(numbers),
        "max_attempts": int(trial.get("max_attempts") or 10),
        "status": status,
        "display_status": display_status,
        "top9_outcome": outcome(top9_first),
        "top12_outcome": outcome(top12_first),
    }


class OrbitPerformanceService:
    async def summarize_roulette(
        self,
        roulette_id: str,
        *,
        max_attempts: int = 10,
        maximum_records: int = 50_000,
    ) -> Dict[str, Any]:
        safe_maximum = max(100, min(200_000, int(maximum_records)))
        safe_attempts = max(1, min(20, int(max_attempts)))
        query = {
            "roulette_id": str(roulette_id),
            "status": "resolved",
            "attempts_observed": {"$gte": safe_attempts},
        }
        projection = {
            "_id": 0,
            "anchor_timestamp_utc": 1,
            "status": 1,
            "attempts_observed": 1,
            "top9_first_hit_attempt": 1,
            "top12_first_hit_attempt": 1,
        }
        rows, pending = await asyncio.gather(
            orbit_prediction_trials_coll.find(query, projection)
            .sort([("anchor_timestamp_utc", -1), ("_id", -1)])
            .limit(safe_maximum)
            .to_list(length=safe_maximum),
            orbit_prediction_trials_coll.count_documents(
                {"roulette_id": str(roulette_id), "status": "pending"}
            ),
        )
        summary = build_performance_summary(
            rows,
            now=datetime.now(timezone.utc),
            max_attempts=safe_attempts,
        )
        return {
            "available": bool(rows),
            "roulette_id": str(roulette_id),
            "pending_trials": int(pending),
            "records_capped": len(rows) >= safe_maximum,
            **summary,
        }

    async def summarize_many(
        self,
        roulette_ids: Sequence[str],
        *,
        max_attempts: int = 10,
        maximum_records: int = 50_000,
    ) -> list[Dict[str, Any]]:
        return list(
            await asyncio.gather(
                *(
                    self.summarize_roulette(
                        roulette_id,
                        max_attempts=max_attempts,
                        maximum_records=maximum_records,
                    )
                    for roulette_id in roulette_ids
                )
            )
        )

    async def history_for_roulette(
        self,
        roulette_id: str,
        *,
        limit: int = 20,
    ) -> Dict[str, Any]:
        safe_limit = max(1, min(50, int(limit)))
        projection = {
            "_id": 0,
            "trial_id": 1,
            "roulette_id": 1,
            "anchor_history_id": 1,
            "anchor_timestamp_utc": 1,
            "recent_pivots": 1,
            "top9": 1,
            "top12": 1,
            "attempt_numbers": 1,
            "attempt_timestamps_utc": 1,
            "attempts_observed": 1,
            "max_attempts": 1,
            "top9_first_hit_attempt": 1,
            "top12_first_hit_attempt": 1,
            "status": 1,
        }
        rows = await (
            orbit_prediction_trials_coll.find(
                {"roulette_id": str(roulette_id)},
                projection,
            )
            .sort([("anchor_timestamp_utc", -1), ("_id", -1)])
            .limit(safe_limit)
            .to_list(length=safe_limit)
        )
        return {
            "roulette_id": str(roulette_id),
            "count": len(rows),
            "limit": safe_limit,
            "items": [serialize_trial_history(row) for row in rows],
        }

    async def history_many(
        self,
        roulette_ids: Sequence[str],
        *,
        limit: int = 20,
    ) -> list[Dict[str, Any]]:
        return list(
            await asyncio.gather(
                *(
                    self.history_for_roulette(roulette_id, limit=limit)
                    for roulette_id in roulette_ids
                )
            )
        )


orbit_performance_service = OrbitPerformanceService()
