"""Transições puras para coletar até dez giros prospectivos por formação."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping


def advance_trial(
    trial: Mapping[str, Any],
    *,
    number: int,
    history_id: str,
    timestamp: datetime,
) -> dict[str, Any] | None:
    if str(trial.get("collection_status") or trial.get("status") or "") not in {
        "collecting",
        "pending",
    }:
        return None
    observed_ids = [str(value) for value in trial.get("attempt_history_ids") or []]
    if str(history_id) in observed_ids:
        return None
    if str(history_id) == str(trial.get("activation_history_id") or ""):
        return None

    targets = {int(value) for value in trial.get("targets") or []}
    attempts = list(trial.get("attempts") or [])
    collection_horizon = max(
        1,
        int(trial.get("collection_horizon") or trial.get("max_attempts") or 10),
    )
    attempt_number = len(attempts) + 1
    if attempt_number > collection_horizon:
        return None
    hit = int(number) in targets
    attempt = {
        "attempt": attempt_number,
        "number": int(number),
        "history_id": str(history_id),
        "timestamp_utc": timestamp,
        "hit": hit,
    }
    attempts.append(attempt)
    previous_first_hit = trial.get("first_hit_attempt")
    first_hit_attempt = (
        int(previous_first_hit)
        if previous_first_hit is not None
        else (attempt_number if hit else None)
    )
    collection_complete = attempt_number >= collection_horizon
    return {
        "attempts": attempts,
        "attempt_history_ids": [*observed_ids, str(history_id)],
        "attempts_observed": attempt_number,
        "first_hit_attempt": first_hit_attempt,
        "first_hit_at_utc": (
            trial.get("first_hit_at_utc")
            or (timestamp if hit and previous_first_hit is None else None)
        ),
        "collection_status": "complete" if collection_complete else "collecting",
        "collection_completed_at_utc": timestamp if collection_complete else None,
        "status": "resolved" if collection_complete else "pending",
        "outcome": (
            "won"
            if first_hit_attempt is not None
            else ("lost" if collection_complete else "pending")
        ),
        "resolved_at_utc": timestamp if collection_complete else None,
        "updated_at_utc": timestamp,
    }
