"""Transições puras para acompanhar tentativas prospectivas."""

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
    if str(trial.get("status") or "") != "pending":
        return None
    observed_ids = [str(value) for value in trial.get("attempt_history_ids") or []]
    if str(history_id) in observed_ids:
        return None
    if str(history_id) == str(trial.get("activation_history_id") or ""):
        return None

    targets = {int(value) for value in trial.get("targets") or []}
    attempts = list(trial.get("attempts") or [])
    max_attempts = max(1, int(trial.get("max_attempts") or 2))
    attempt_number = len(attempts) + 1
    if attempt_number > max_attempts:
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
    resolved = hit or attempt_number >= max_attempts
    return {
        "attempts": attempts,
        "attempt_history_ids": [*observed_ids, str(history_id)],
        "attempts_observed": attempt_number,
        "first_hit_attempt": attempt_number if hit else None,
        "status": "resolved" if resolved else "pending",
        "outcome": "won" if hit else ("lost" if resolved else "pending"),
        "resolved_at_utc": timestamp if resolved else None,
        "updated_at_utc": timestamp,
    }
