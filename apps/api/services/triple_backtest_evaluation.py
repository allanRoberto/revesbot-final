"""Pure evaluation of already-ranked trio signals against a frozen result stream."""
from __future__ import annotations

from bisect import bisect_right
from copy import deepcopy
from typing import Any


SKIP_STATUSES = {"repeated_trio", "no_evidence"}


def _validate(rows: list[dict[str, Any]], signals: list[dict[str, Any]], attempts: int) -> None:
    if type(attempts) is not int or attempts < 1:
        raise ValueError("attempts must be a positive integer")
    if not isinstance(rows, list) or not isinstance(signals, list):
        raise TypeError("rows and signals must be lists")
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise TypeError(f"rows[{index}] must be a mapping")
        if type(row.get("value")) is not int or not 0 <= row["value"] <= 36:
            raise ValueError(f"rows[{index}].value must be an integer from 0 to 36")
        if not isinstance(row.get("timestamp"), str) or not row["timestamp"]:
            raise ValueError(f"rows[{index}].timestamp must be a non-empty string")
        if not isinstance(row.get("source_id"), str) or not row["source_id"]:
            raise ValueError(f"rows[{index}].source_id must be a non-empty string")
    for index, signal in enumerate(signals):
        if not isinstance(signal, dict):
            raise TypeError(f"signals[{index}] must be a mapping")
        end_index = signal.get("end_index")
        if type(end_index) is not int or not 0 <= end_index < len(rows):
            raise ValueError(f"signals[{index}].end_index is outside rows")
        selected = signal.get("selected_numbers")
        status = signal.get("status")
        if status is not None and status not in SKIP_STATUSES:
            raise ValueError(f"signals[{index}].status is not a supported pre-evaluation status")
        if not isinstance(selected, list) or (not selected and status not in SKIP_STATUSES):
            raise ValueError(
                f"signals[{index}].selected_numbers must be non-empty unless the signal is skipped"
            )
        if (len(selected) > 37 or any(type(number) is not int or not 0 <= number <= 36
                                     for number in selected)
                or len(set(selected)) != len(selected)):
            raise ValueError(
                f"signals[{index}].selected_numbers must contain distinct integers from 0 to 36"
            )


def evaluate_signals(
    rows: list[dict[str, Any]], signals: list[dict[str, Any]], attempts: int,
    prevent_overlapping_bets: bool = False,
) -> dict[str, Any]:
    """Evaluate fixed selections without calculating or changing their ranking.

    A known hit within ``attempts`` is a win even at the sample edge. A signal
    without a hit needs all attempts to become a loss; otherwise it is incomplete.
    Recovery describes the first later hit of an evaluated loss, if one is present
    in this finite sample; absence means unresolved in the observed sample only.
    """
    _validate(rows, signals, attempts)
    if type(prevent_overlapping_bets) is not bool:
        raise TypeError("prevent_overlapping_bets must be a boolean")

    positions: list[list[int]] = [[] for _ in range(37)]
    for index, row in enumerate(rows):
        positions[row["value"]].append(index)

    counts = {"evaluated": 0, "wins": 0, "losses": 0, "incomplete": 0,
              "repeated_trio": 0, "no_evidence": 0, "overlap_skipped": 0}
    win_counts = [0] * attempts
    recovery_counts: dict[int, int] = {}
    output_signals = []
    locked_until_index = -1
    active_signal_id = None

    for original in signals:
        result = deepcopy(original)
        end_index = original["end_index"]
        available = min(attempts, len(rows) - end_index - 1)
        result["available_attempts"] = available
        result["checked_numbers"] = [
            row["value"] for row in rows[end_index + 1:end_index + 1 + available]
        ]
        result.update({
            "first_hit_attempt": None,
            "hit_number": None,
            "hit_rank": None,
            "recovery_extra_attempts": None,
            "followup_observed": None,
            "blocked_by_signal_id": None,
            "blocked_until_position": None,
        })

        input_status = original.get("status")
        if input_status in SKIP_STATUSES:
            result["status"] = input_status
            counts[input_status] += 1
            output_signals.append(result)
            continue

        if prevent_overlapping_bets and end_index < locked_until_index:
            result.update({
                "status": "overlap_skipped",
                "available_attempts": 0,
                "checked_numbers": [],
                "blocked_by_signal_id": active_signal_id,
                "blocked_until_position": locked_until_index + 1,
            })
            counts["overlap_skipped"] += 1
            output_signals.append(result)
            continue

        first = None
        selected = original["selected_numbers"]
        for rank, number in enumerate(selected, 1):
            number_positions = positions[number]
            offset = bisect_right(number_positions, end_index)
            if offset < len(number_positions):
                position = number_positions[offset]
                candidate = (position, rank, number)
                if first is None or candidate[:2] < first[:2]:
                    first = candidate
        if first is not None:
            position, rank, number = first
            result["first_hit_attempt"] = position - end_index
            result["hit_number"] = number
            result["hit_rank"] = rank

        if first is not None and result["first_hit_attempt"] <= attempts:
            counts["evaluated"] += 1
            result["status"] = "win"
            counts["wins"] += 1
            win_counts[result["first_hit_attempt"] - 1] += 1
            locked_until_index = end_index + result["first_hit_attempt"]
        elif available < attempts:
            result["status"] = "incomplete"
            counts["incomplete"] += 1
            locked_until_index = end_index + available
        else:
            counts["evaluated"] += 1
            result["status"] = "loss"
            counts["losses"] += 1
            locked_until_index = end_index + attempts
            result["followup_observed"] = max(0, len(rows) - end_index - 1 - attempts)
            if first is not None:
                extra = result["first_hit_attempt"] - attempts
                result["recovery_extra_attempts"] = extra
                recovery_counts[result["first_hit_attempt"]] = (
                    recovery_counts.get(result["first_hit_attempt"], 0) + 1
                )
        if prevent_overlapping_bets:
            active_signal_id = result.get("signal_id")
        output_signals.append(result)

    recovered = sum(recovery_counts.values())
    evaluated = counts["evaluated"]
    summary = {
        "total_signals": len(signals),
        **counts,
        "accuracy_pct": counts["wins"] * 100.0 / evaluated if evaluated else None,
        "win_attempts": [
            {"attempt": attempt, "count": win_counts[attempt - 1]}
            for attempt in range(1, attempts + 1)
        ],
        "recovered_losses": recovered,
        "unresolved_losses": counts["losses"] - recovered,
        "recovery_attempts": [
            {"attempt": attempt, "extra_attempts": attempt - attempts,
             "count": recovery_counts[attempt]}
            for attempt in sorted(recovery_counts)
        ],
        "max_recovery_attempt": max(recovery_counts, default=None),
    }
    return {"summary": summary, "signals": output_signals}
