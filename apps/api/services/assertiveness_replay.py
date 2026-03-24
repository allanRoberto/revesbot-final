from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Dict, List

SuggestionProvider = Callable[[List[int]], Awaitable[Dict[str, Any]]]


async def fetch_history_desc(roulette_id: str, limit: int) -> List[int]:
    from api.core.db import history_coll

    safe_limit = max(1, min(10_000, int(limit)))
    cursor = (
        history_coll
        .find({"roulette_id": roulette_id})
        .sort("timestamp", -1)
        .limit(safe_limit)
    )
    docs = await cursor.to_list(length=safe_limit)
    return [int(doc["value"]) for doc in docs if 0 <= int(doc.get("value", -1)) <= 36]


def normalize_chip_values(raw_values: List[float] | None, max_attempts: int) -> List[float]:
    safe_attempts = max(1, int(max_attempts))
    parsed: List[float] = []
    for raw in raw_values or []:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            parsed.append(value)

    if not parsed:
        parsed = [1.0]

    while len(parsed) < safe_attempts:
        parsed.append(parsed[-1])

    return parsed[:safe_attempts]


async def run_assertiveness_replay(
    *,
    roulette_id: str,
    history_desc: List[int],
    suggestion_provider: SuggestionProvider,
    min_history_size: int,
    entries_limit: int,
    max_attempts: int,
    min_confidence: int,
    chip_values: List[float],
) -> Dict[str, Any]:
    normalized_desc = [int(n) for n in history_desc if 0 <= int(n) <= 36]
    safe_attempts = max(1, min(12, int(max_attempts)))
    safe_min_history = max(1, min(500, int(min_history_size)))
    safe_min_confidence = max(0, min(100, int(min_confidence)))
    schedule = normalize_chip_values(chip_values, safe_attempts)

    if len(normalized_desc) < safe_min_history + safe_attempts:
        return {
            "available": False,
            "roulette_id": roulette_id,
            "error": "Histórico insuficiente para replay.",
            "history_size": len(normalized_desc),
            "required_min": safe_min_history + safe_attempts,
        }

    chronological = list(reversed(normalized_desc))
    anchor_indexes = list(range(safe_min_history - 1, len(chronological) - safe_attempts))
    if entries_limit > 0 and len(anchor_indexes) > int(entries_limit):
        anchor_indexes = anchor_indexes[-int(entries_limit):]

    details: List[Dict[str, Any]] = []
    hit_by_attempt = {attempt: 0 for attempt in range(1, safe_attempts + 1)}
    signals_taken = 0
    skipped_unavailable = 0
    skipped_confidence = 0
    hits = 0
    misses = 0
    total_profit = 0.0
    total_invested = 0.0

    for anchor_idx in anchor_indexes:
        context_chronological = chronological[: anchor_idx + 1]
        context_desc = list(reversed(context_chronological))
        suggestion_result = await suggestion_provider(context_desc)

        if not bool(suggestion_result.get("available", False)):
            skipped_unavailable += 1
            continue

        suggestion = [
            int(n)
            for n in (suggestion_result.get("suggestion") or suggestion_result.get("list") or [])
            if 0 <= int(n) <= 36
        ]
        if not suggestion:
            skipped_unavailable += 1
            continue

        confidence = suggestion_result.get("confidence", {}) or {}
        confidence_score = int(confidence.get("score", 0) or 0)
        if confidence_score < safe_min_confidence:
            skipped_confidence += 1
            continue

        signals_taken += 1
        future_numbers = chronological[anchor_idx + 1: anchor_idx + 1 + safe_attempts]
        suggestion_size = len(suggestion)
        suggestion_set = set(suggestion)
        invested = 0.0
        hit_attempt = 0
        hit_number = None
        profit = 0.0

        for attempt_idx, number in enumerate(future_numbers, start=1):
            chip_value = float(schedule[attempt_idx - 1])
            invested += chip_value * suggestion_size
            if number in suggestion_set:
                payout = 36.0 * chip_value
                profit = payout - invested
                hit_attempt = attempt_idx
                hit_number = int(number)
                hits += 1
                hit_by_attempt[attempt_idx] += 1
                break

        if hit_attempt == 0:
            misses += 1
            profit = -invested

        total_profit += profit
        total_invested += invested
        details.append(
            {
                "entry_number": int(context_chronological[-1]),
                "context_size": len(context_desc),
                "suggestion": suggestion,
                "suggestion_size": suggestion_size,
                "confidence": {
                    "score": confidence_score,
                    "label": confidence.get("label", "Baixa"),
                },
                "future_numbers": [int(n) for n in future_numbers],
                "max_attempts": safe_attempts,
                "hit": hit_attempt > 0,
                "hit_attempt": hit_attempt or None,
                "hit_number": hit_number,
                "invested": round(invested, 2),
                "profit": round(profit, 2),
            }
        )

    hit_rate = (hits / signals_taken) if signals_taken > 0 else 0.0
    roi = (total_profit / total_invested) if total_invested > 0 else 0.0

    return {
        "available": True,
        "roulette_id": roulette_id,
        "history_size": len(normalized_desc),
        "entries_analyzed": len(anchor_indexes),
        "signals_taken": signals_taken,
        "skipped_unavailable": skipped_unavailable,
        "skipped_confidence": skipped_confidence,
        "hits": hits,
        "misses": misses,
        "hit_rate": round(hit_rate, 4),
        "hit_rate_by_attempt": {
            str(attempt): {
                "hits": count,
                "rate": round((count / signals_taken), 4) if signals_taken > 0 else 0.0,
            }
            for attempt, count in hit_by_attempt.items()
        },
        "total_invested": round(total_invested, 2),
        "total_profit": round(total_profit, 2),
        "roi": round(roi, 4),
        "chip_values": schedule,
        "details": details,
    }
