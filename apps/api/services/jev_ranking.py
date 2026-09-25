"""Deterministic 0-36 profiles and directed pull relations for Jev ranking."""
from __future__ import annotations

import hashlib
from typing import Any, Sequence

from api.services.jev_statistics import FORECAST_HORIZON_SPINS


ROULETTE_NUMBERS = tuple(range(37))
NUMBER_KEYS = tuple(f"numero_{number:02d}" for number in ROULETTE_NUMBERS)
CATALOG_VERSION = "pull_relations_v1"
STATE_SCHEMA_VERSION = "roulette_ranking_v1"
MIN_RELATION_SUPPORT = 30
HISTORY_TAIL_LIMIT = 500
MAX_PATTERN_QUESTIONS = 12
SMOOTHING_STRENGTH = 37.0
FREQUENCY_WINDOWS = (10, 30, 100)
RELATION_WINDOWS = (100, 300)
SINGLE_NUMBER_BASELINE = 1 - (36 / 37) ** FORECAST_HORIZON_SPINS

RED_NUMBERS = frozenset(
    {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
)

PATTERN_DEFINITIONS = (
    {
        "id": "stable_positive_pull",
        "description": "Taxa suavizada acima da base e sustentada nas janelas com suporte.",
    },
    {
        "id": "positive_pull",
        "description": "Taxa suavizada acima da base, ainda sem estabilidade recente suficiente.",
    },
    {
        "id": "recent_positive_pull",
        "description": "Elevação recente acima da base sem confirmação no histórico completo.",
    },
    {
        "id": "stable_negative_relation",
        "description": "Taxa suavizada abaixo da base e sustentada nas janelas com suporte.",
    },
    {
        "id": "recent_negative_relation",
        "description": "Queda recente abaixo da base sem confirmação no histórico completo.",
    },
    {
        "id": "unstable_relation",
        "description": "Janelas com direções conflitantes em relação à base.",
    },
    {
        "id": "neutral_relation",
        "description": "Relação próxima da referência ou sem efeito descritivo relevante.",
    },
    {
        "id": "low_support",
        "description": "Poucas ocorrências válidas do número de origem.",
    },
)


def number_key(number: int) -> str:
    return f"numero_{number:02d}"


def relation_key(source_number: int, target_number: int) -> str:
    return f"relacao_{source_number:02d}_{target_number:02d}"


def _safe_rate(hits: int, support: int) -> float | None:
    return hits / support if support else None


def _smoothed_rate(hits: int, support: int) -> float:
    return (hits + SINGLE_NUMBER_BASELINE * SMOOTHING_STRENGTH) / (
        support + SMOOTHING_STRENGTH
    )


def _count_relations(
    history: Sequence[int], source_number: int, *, start_index: int = 0
) -> tuple[int, list[int]]:
    support = 0
    hits = [0] * len(ROULETTE_NUMBERS)
    last_source_index = len(history) - FORECAST_HORIZON_SPINS
    for index in range(max(0, start_index), max(0, last_source_index)):
        if history[index] != source_number:
            continue
        support += 1
        future_numbers = set(history[index + 1 : index + 1 + FORECAST_HORIZON_SPINS])
        for target_number in future_numbers:
            hits[target_number] += 1
    return support, hits


def _relation_window(
    history: Sequence[int], source_number: int, target_number: int, window_size: int
) -> dict[str, Any]:
    start_index = max(0, len(history) - window_size)
    support, hits = _count_relations(history, source_number, start_index=start_index)
    target_hits = hits[target_number]
    raw_rate = _safe_rate(target_hits, support)
    smoothed = _smoothed_rate(target_hits, support)
    return {
        "window_spins": min(window_size, len(history)),
        "support": support,
        "hits": target_hits,
        "raw_rate": raw_rate,
        "smoothed_rate": smoothed,
        "lift_vs_baseline": smoothed / SINGLE_NUMBER_BASELINE,
    }


def _classify_relation(relation: dict[str, Any]) -> str:
    if relation["support"] < MIN_RELATION_SUPPORT:
        return "low_support"

    full_lift = relation["lift_vs_baseline"]
    eligible_lifts = [
        item["lift_vs_baseline"]
        for item in relation["windows"].values()
        if item["support"] >= 10
    ]
    has_positive = any(lift >= 1.25 for lift in eligible_lifts)
    has_negative = any(lift <= 0.75 for lift in eligible_lifts)
    if has_positive and has_negative:
        return "unstable_relation"
    if full_lift >= 1.25:
        if eligible_lifts and all(lift >= 1.05 for lift in eligible_lifts):
            return "stable_positive_pull"
        return "positive_pull"
    if full_lift <= 0.75:
        if eligible_lifts and all(lift <= 0.95 for lift in eligible_lifts):
            return "stable_negative_relation"
        return "recent_negative_relation"
    if has_positive:
        return "recent_positive_pull"
    if has_negative:
        return "recent_negative_relation"
    return "neutral_relation"


def _relation_strength(relation: dict[str, Any]) -> float:
    support_factor = min(1.0, relation["support"] / 100)
    effect_factor = min(1.0, abs(relation["lift_vs_baseline"] - 1.0))
    eligible_lifts = [
        item["lift_vs_baseline"]
        for item in relation["windows"].values()
        if item["support"] >= 10
    ]
    stability_factor = 1.0
    if eligible_lifts:
        full_direction = relation["lift_vs_baseline"] >= 1.0
        matching = sum((lift >= 1.0) == full_direction for lift in eligible_lifts)
        stability_factor = matching / len(eligible_lifts)
    return round(support_factor * effect_factor * stability_factor, 6)


def calculate_pull_relations(history: Sequence[int]) -> dict[str, Any]:
    """Catalogue A -> B relations for the latest observed number A."""
    source_number = history[-1]
    support, hits = _count_relations(history, source_number)
    relations: list[dict[str, Any]] = []
    for target_number in ROULETTE_NUMBERS:
        target_hits = hits[target_number]
        smoothed = _smoothed_rate(target_hits, support)
        relation: dict[str, Any] = {
            "relation_id": f"pull:{source_number}->{target_number}:h{FORECAST_HORIZON_SPINS}",
            "question_id": relation_key(source_number, target_number),
            "source_number": source_number,
            "target_number": target_number,
            "horizon_spins": FORECAST_HORIZON_SPINS,
            "support": support,
            "hits": target_hits,
            "raw_rate": _safe_rate(target_hits, support),
            "smoothed_rate": smoothed,
            "fair_baseline": SINGLE_NUMBER_BASELINE,
            "lift_vs_baseline": smoothed / SINGLE_NUMBER_BASELINE,
            "windows": {
                f"last_{window_size}": _relation_window(
                    history, source_number, target_number, window_size
                )
                for window_size in RELATION_WINDOWS
            },
        }
        relation["classification"] = _classify_relation(relation)
        relation["deterministic_strength"] = _relation_strength(relation)
        relations.append(relation)

    candidate_types = {
        "stable_positive_pull",
        "positive_pull",
        "recent_positive_pull",
        "stable_negative_relation",
        "recent_negative_relation",
        "unstable_relation",
    }
    candidates = sorted(
        (relation for relation in relations if relation["classification"] in candidate_types),
        key=lambda item: (-item["deterministic_strength"], item["target_number"]),
    )[:MAX_PATTERN_QUESTIONS]
    return {
        "catalog_version": CATALOG_VERSION,
        "source_number": source_number,
        "horizon_spins": FORECAST_HORIZON_SPINS,
        "minimum_support": MIN_RELATION_SUPPORT,
        "definitions": [dict(item) for item in PATTERN_DEFINITIONS],
        "relations": relations,
        "candidates": candidates,
    }


def _number_attributes(number: int) -> dict[str, Any]:
    if number == 0:
        return {"color": "green", "parity": None, "dozen": None, "column": None}
    return {
        "color": "red" if number in RED_NUMBERS else "black",
        "parity": "even" if number % 2 == 0 else "odd",
        "dozen": ((number - 1) // 12) + 1,
        "column": 3 if number % 3 == 0 else number % 3,
    }


def _number_profile(
    history: Sequence[int], number: int, relation: dict[str, Any]
) -> dict[str, Any]:
    positions = [index for index, value in enumerate(history) if value == number]
    intervals = [right - left for left, right in zip(positions, positions[1:])]
    current_gap = len(history) - 1 - positions[-1] if positions else None
    return {
        "number": number,
        "attributes": _number_attributes(number),
        "baseline_probability": SINGLE_NUMBER_BASELINE,
        "frequency": {
            "all": {"spins": len(history), "hits": len(positions), "rate": len(positions) / len(history)},
            **{
                f"last_{window_size}": {
                    "spins": min(window_size, len(history)),
                    "hits": sum(value == number for value in history[-window_size:]),
                    "rate": sum(value == number for value in history[-window_size:])
                    / min(window_size, len(history)),
                }
                for window_size in FREQUENCY_WINDOWS
            },
        },
        "gap": {
            "current": current_gap,
            "average_interval": sum(intervals) / len(intervals) if intervals else None,
            "maximum_interval": max(intervals) if intervals else None,
        },
        "pull_relation_from_latest": relation,
    }


def _history_digest(history: Sequence[int]) -> str:
    encoded = ",".join(str(number) for number in history).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def build_ranking_state(
    history: Sequence[int], catalog: dict[str, Any]
) -> dict[str, Any]:
    relations_by_target = {
        relation["target_number"]: relation for relation in catalog["relations"]
    }
    tail = list(history[-HISTORY_TAIL_LIMIT:])
    raw_scope = (
        "full_history"
        if len(tail) == len(history)
        else f"last_{len(tail)}_of_{len(history)}"
    )
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "task": {
            "type": "rank_numbers_from_pull_relations",
            "roulette": "single_zero_0_to_36",
            "roulette_slug": "pragmatic-auto-roulette",
            "forecast_horizon_spins": FORECAST_HORIZON_SPINS,
            "universe": list(ROULETTE_NUMBERS),
            "include_zero": True,
        },
        "history_context": {
            "history_order": "oldest_to_newest",
            "observed_spins": len(history),
            "latest_observed_number": history[-1],
            "raw_history_scope": raw_scope,
            "recent_history": tail,
            "full_history_sha256": _history_digest(history),
        },
        "number_profiles": [
            _number_profile(history, number, relations_by_target[number])
            for number in ROULETTE_NUMBERS
        ],
        "pattern_catalog": {
            "catalog_version": catalog["catalog_version"],
            "source_number": catalog["source_number"],
            "minimum_support": catalog["minimum_support"],
            "definitions": catalog["definitions"],
            "candidates": catalog["candidates"],
        },
        "interpretation_rules": [
            "Pull relations are descriptive conditional frequencies, not causal links.",
            "Use support, smoothing, recent windows and full-history stability together.",
            "Compare every estimate with the supplied fair-independent baseline.",
            "Low support, recency and absence alone do not establish predictability.",
            "Several target numbers may occur during the three-spin horizon.",
        ],
    }


def build_ranking_questions(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    questions: dict[str, dict[str, Any]] = {}
    for number in ROULETTE_NUMBERS:
        questions[number_key(number)] = {
            "type": "noul",
            "instructions": {
                "target_number": number,
                "forecast_horizon_spins": FORECAST_HORIZON_SPINS,
                "question": (
                    "Will target_number appear at least once in any of the next three spins "
                    "immediately after state.history_context?"
                ),
                "evidence": (
                    "Use the matching state.number_profiles entry and its directed pull relation."
                ),
            },
            "criteria": {
                "true": "The target number appears at least once in the next three spins.",
                "false": "The target number does not appear in any of the next three spins.",
            },
        }

    for candidate in catalog["candidates"]:
        questions[candidate["question_id"]] = {
            "type": "noul",
            "instructions": {
                "relation_id": candidate["relation_id"],
                "source_number": candidate["source_number"],
                "target_number": candidate["target_number"],
                "question": (
                    "Is this catalogued directed relation materially relevant to the target "
                    "number estimate for the supplied three-spin context?"
                ),
                "rules": [
                    "Treat the relation as descriptive evidence, not causality.",
                    "Require adequate support and consistency across supplied windows.",
                    "Reject relevance when the apparent effect is unstable or sample-starved.",
                ],
            },
            "criteria": {
                "true": "The relation is sufficiently supported and relevant to this estimate.",
                "false": "The relation is insufficient, unstable, or not relevant to this estimate.",
            },
        }
    return questions


def build_ranking_payload(history: Sequence[int]) -> dict[str, Any]:
    catalog = calculate_pull_relations(history)
    state = build_ranking_state(history, catalog)
    questions = build_ranking_questions(catalog)
    return {"catalog": catalog, "state": state, "questions": questions}
