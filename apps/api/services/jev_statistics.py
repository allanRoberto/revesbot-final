"""Deterministic statistics and System One payload construction for Jev."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from api.schemas.jev import GROUP_KEYS


FORECAST_HORIZON_SPINS = 3
BASELINE_ASSUMPTION = (
    "37 equally likely outcomes and independent spins; this is a reference model, "
    "not a measured property of this wheel."
)
STATISTICS_NOTE = "Counts and gaps are descriptive, not validated signals."
QUESTION_TEXT = (
    "Will at least one of target_numbers appear in at least one of the next three spins, "
    "immediately AFTER the last value in state.history?"
)
QUESTION_RULES = [
    "Evaluate the future occurrence itself, not whether it is possible.",
    "The target group is fixed for all three future spins.",
    "Do not include any already observed spin in the target event.",
    "Several groups may hit; this is not an exclusive choice.",
    "Use only the supplied past data. Future results are unknown.",
    "Use the supplied fair-independent probability as a reference.",
    "Recent frequency and absence alone do not establish predictability.",
]


def calculate_group_statistics(history: Sequence[int], numbers: Sequence[int]) -> dict[str, Any]:
    group_numbers = list(numbers)
    group_set = set(group_numbers)
    recent_window = list(history[-min(30, len(history)):])

    spins_since_last_hit: int | None = None
    for distance, number in enumerate(reversed(history)):
        if number in group_set:
            spins_since_last_hit = distance
            break

    size = len(group_set)
    return {
        "numbers": group_numbers,
        "size": size,
        "recent_window_size": len(recent_window),
        "hits_in_recent_window": sum(number in group_set for number in recent_window),
        "spins_since_last_hit": spins_since_last_hit,
        "fair_independent_baseline": 1 - (1 - size / 37) ** FORECAST_HORIZON_SPINS,
    }


def calculate_all_group_statistics(
    history: Sequence[int], groups: Mapping[str, Sequence[int]]
) -> dict[str, dict[str, Any]]:
    return {
        group_id: calculate_group_statistics(history, groups[group_id])
        for group_id in GROUP_KEYS
    }


def build_jev_state(
    history: Sequence[int], group_statistics: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    return {
        "roulette": "single_zero_0_to_36",
        "roulette_slug": "pragmatic-auto-roulette",
        "history_order": "oldest_to_newest",
        "history": list(history),
        "observed_spins": len(history),
        "latest_observed_number": history[-1],
        "forecast_horizon_spins": FORECAST_HORIZON_SPINS,
        "groups": {group_id: dict(group_statistics[group_id]) for group_id in GROUP_KEYS},
        "baseline_assumption": BASELINE_ASSUMPTION,
        "statistics_note": STATISTICS_NOTE,
    }


def build_jev_questions(groups: Mapping[str, Sequence[int]]) -> dict[str, dict[str, Any]]:
    return {
        group_id: {
            "type": "noul",
            "instructions": {
                "target_numbers": list(groups[group_id]),
                "question": QUESTION_TEXT,
                "rules": list(QUESTION_RULES),
            },
            "criteria": {
                "true": "At least one of the next three results is in target_numbers.",
                "false": "None of the next three results is in target_numbers.",
            },
        }
        for group_id in GROUP_KEYS
    }
