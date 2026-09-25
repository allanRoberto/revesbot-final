"""Deterministic 0-36 evidence and mixed Jev questions for roulette ranking."""
from __future__ import annotations

import hashlib
from typing import Any, Sequence

from api.services.jev_statistics import FORECAST_HORIZON_SPINS


ROULETTE_NUMBERS = tuple(range(37))
NUMBER_KEYS = tuple(f"numero_{number:02d}" for number in ROULETTE_NUMBERS)
NEXT_SPIN_CHOICE_KEY = "proxima_rodada"
REGIME_CHOICE_KEY = "regime_atual"
CATALOG_VERSION = "pull_relations_v2"
STATE_SCHEMA_VERSION = "roulette_ranking_v3"
MIN_RELATION_SUPPORT = 30
HISTORY_TAIL_LIMIT = 200
MAX_PATTERN_QUESTIONS = 12
SMOOTHING_STRENGTH = 37.0
FREQUENCY_WINDOWS = (10, 30, 100, 300, 1000)
RELATION_WINDOWS = (100, 300)
RELATION_HORIZONS = tuple(range(1, FORECAST_HORIZON_SPINS + 1))

NUMBER_PROFILE_COLUMNS = (
    "number",
    "color",
    "parity",
    "dozen",
    "column",
    "all_spins",
    "all_hits",
    "all_rate",
    *(field for window in FREQUENCY_WINDOWS for field in (f"last_{window}_hits", f"last_{window}_rate")),
    "gap_current",
    "gap_average_interval",
    "gap_maximum_interval",
    "gap_historical_percentile",
)
RELATION_EVIDENCE_COLUMNS = (
    "target_number",
    "classification",
    "deterministic_strength",
    *(
        field
        for horizon in RELATION_HORIZONS
        for field in (
            f"h{horizon}_support",
            f"h{horizon}_hits",
            f"h{horizon}_raw_rate",
            f"h{horizon}_smoothed_rate",
            f"h{horizon}_lift",
        )
    ),
    *(
        field
        for window in RELATION_WINDOWS
        for field in (
            f"last_{window}_support",
            f"last_{window}_hits",
            f"last_{window}_raw_rate",
            f"last_{window}_smoothed_rate",
            f"last_{window}_lift",
        )
    ),
    "pair_support",
    "pair_hits",
    "pair_raw_rate",
    "pair_smoothed_rate",
    "pair_lift",
)


def horizon_baseline(horizon_spins: int) -> float:
    return 1 - (36 / 37) ** horizon_spins


SINGLE_SPIN_BASELINE = horizon_baseline(1)
SINGLE_NUMBER_BASELINE = horizon_baseline(FORECAST_HORIZON_SPINS)

RED_NUMBERS = frozenset(
    {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
)

PATTERN_DEFINITIONS = (
    {"id": "stable_positive_pull", "description": "Taxa suavizada acima da base e sustentada nas janelas com suporte."},
    {"id": "positive_pull", "description": "Taxa suavizada acima da base, ainda sem estabilidade recente suficiente."},
    {"id": "recent_positive_pull", "description": "Elevação recente acima da base sem confirmação no histórico completo."},
    {"id": "stable_negative_relation", "description": "Taxa suavizada abaixo da base e sustentada nas janelas com suporte."},
    {"id": "recent_negative_relation", "description": "Queda recente abaixo da base sem confirmação no histórico completo."},
    {"id": "unstable_relation", "description": "Janelas com direções conflitantes em relação à base."},
    {"id": "neutral_relation", "description": "Relação próxima da referência ou sem efeito descritivo relevante."},
    {"id": "low_support", "description": "Poucas ocorrências válidas do número de origem."},
)

REGIME_CRITERIA = {
    "neutral": "Sem evidência descritiva dominante entre frequência, transição e atraso.",
    "frequency_concentration": "A janela recente está concentrada em poucos números.",
    "transition_driven": "As transições do último número têm efeitos sustentados e relevantes.",
    "gap_driven": "Atrasos históricos extremos são a evidência descritiva dominante.",
    "unstable": "Janelas e sinais disponíveis divergem materialmente entre si.",
}


def number_key(number: int) -> str:
    return f"numero_{number:02d}"


def relation_key(source_number: int, target_number: int) -> str:
    return f"relacao_{source_number:02d}_{target_number:02d}"


def _safe_rate(hits: int, support: int) -> float | None:
    return hits / support if support else None


def _smoothed_rate(hits: int, support: int, baseline: float) -> float:
    return (hits + baseline * SMOOTHING_STRENGTH) / (support + SMOOTHING_STRENGTH)


def _count_relations(
    history: Sequence[int],
    source_number: int,
    *,
    horizon_spins: int = FORECAST_HORIZON_SPINS,
    start_index: int = 0,
) -> tuple[int, list[int]]:
    support = 0
    hits = [0] * len(ROULETTE_NUMBERS)
    last_source_index = len(history) - horizon_spins
    for index in range(max(0, start_index), max(0, last_source_index)):
        if history[index] != source_number:
            continue
        support += 1
        future_numbers = set(history[index + 1 : index + 1 + horizon_spins])
        for target_number in future_numbers:
            hits[target_number] += 1
    return support, hits


def _count_pair_relations(
    history: Sequence[int],
    previous_number: int,
    source_number: int,
    *,
    horizon_spins: int = FORECAST_HORIZON_SPINS,
) -> tuple[int, list[int]]:
    support = 0
    hits = [0] * len(ROULETTE_NUMBERS)
    last_source_index = len(history) - horizon_spins
    for index in range(1, max(1, last_source_index)):
        if history[index - 1] != previous_number or history[index] != source_number:
            continue
        support += 1
        future_numbers = set(history[index + 1 : index + 1 + horizon_spins])
        for target_number in future_numbers:
            hits[target_number] += 1
    return support, hits


def _relation_metrics(hits: int, support: int, horizon_spins: int) -> dict[str, Any]:
    baseline = horizon_baseline(horizon_spins)
    smoothed = _smoothed_rate(hits, support, baseline)
    return {
        "horizon_spins": horizon_spins,
        "support": support,
        "hits": hits,
        "raw_rate": _safe_rate(hits, support),
        "smoothed_rate": smoothed,
        "fair_baseline": baseline,
        "lift_vs_baseline": smoothed / baseline,
    }


def _relation_window(
    history: Sequence[int], source_number: int, target_number: int, window_size: int
) -> dict[str, Any]:
    start_index = max(0, len(history) - window_size)
    support, hits = _count_relations(
        history,
        source_number,
        horizon_spins=FORECAST_HORIZON_SPINS,
        start_index=start_index,
    )
    return {
        "window_spins": min(window_size, len(history)),
        **_relation_metrics(hits[target_number], support, FORECAST_HORIZON_SPINS),
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
    """Catalogue A -> B and (A-1, A) -> B relations for the latest context."""
    source_number = history[-1]
    previous_number = history[-2] if len(history) >= 2 else None
    counts_by_horizon = {
        horizon: _count_relations(history, source_number, horizon_spins=horizon)
        for horizon in RELATION_HORIZONS
    }
    pair_support, pair_hits = (
        _count_pair_relations(history, previous_number, source_number)
        if previous_number is not None
        else (0, [0] * len(ROULETTE_NUMBERS))
    )
    support, hits = counts_by_horizon[FORECAST_HORIZON_SPINS]
    relations: list[dict[str, Any]] = []
    for target_number in ROULETTE_NUMBERS:
        full_metrics = _relation_metrics(hits[target_number], support, FORECAST_HORIZON_SPINS)
        relation: dict[str, Any] = {
            "relation_id": f"pull:{source_number}->{target_number}:h{FORECAST_HORIZON_SPINS}",
            "question_id": relation_key(source_number, target_number),
            "source_number": source_number,
            "target_number": target_number,
            **full_metrics,
            "horizons": {
                f"horizon_{horizon}": _relation_metrics(
                    counts_by_horizon[horizon][1][target_number],
                    counts_by_horizon[horizon][0],
                    horizon,
                )
                for horizon in RELATION_HORIZONS
            },
            "windows": {
                f"last_{window_size}": _relation_window(history, source_number, target_number, window_size)
                for window_size in RELATION_WINDOWS
            },
            "pair_relation_from_latest_pair": {
                "previous_number": previous_number,
                "source_number": source_number,
                **_relation_metrics(pair_hits[target_number], pair_support, FORECAST_HORIZON_SPINS),
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
        "previous_number": previous_number,
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


def _rounded(value: float | None) -> float | None:
    return round(value, 6) if value is not None else None


def _number_profile_row(history: Sequence[int], number: int) -> list[Any]:
    positions = [index for index, value in enumerate(history) if value == number]
    intervals = [right - left for left, right in zip(positions, positions[1:])]
    current_gap = len(history) - 1 - positions[-1] if positions else None
    gap_percentile = (
        sum(interval <= current_gap for interval in intervals) / len(intervals)
        if intervals and current_gap is not None
        else None
    )
    attributes = _number_attributes(number)
    frequency_values: list[Any] = []
    for window_size in FREQUENCY_WINDOWS:
        window = history[-window_size:]
        hits = sum(value == number for value in window)
        frequency_values.extend((hits, _rounded(hits / len(window))))
    return [
        number,
        attributes["color"],
        attributes["parity"],
        attributes["dozen"],
        attributes["column"],
        len(history),
        len(positions),
        _rounded(len(positions) / len(history)),
        *frequency_values,
        current_gap,
        _rounded(sum(intervals) / len(intervals)) if intervals else None,
        max(intervals) if intervals else None,
        _rounded(gap_percentile),
    ]


def _relation_evidence_row(relation: dict[str, Any]) -> list[Any]:
    values: list[Any] = [
        relation["target_number"],
        relation["classification"],
        _rounded(relation["deterministic_strength"]),
    ]
    for horizon in RELATION_HORIZONS:
        evidence = relation["horizons"][f"horizon_{horizon}"]
        values.extend(
            (
                evidence["support"],
                evidence["hits"],
                _rounded(evidence["raw_rate"]),
                _rounded(evidence["smoothed_rate"]),
                _rounded(evidence["lift_vs_baseline"]),
            )
        )
    for window_size in RELATION_WINDOWS:
        evidence = relation["windows"][f"last_{window_size}"]
        values.extend(
            (
                evidence["support"],
                evidence["hits"],
                _rounded(evidence["raw_rate"]),
                _rounded(evidence["smoothed_rate"]),
                _rounded(evidence["lift_vs_baseline"]),
            )
        )
    pair = relation["pair_relation_from_latest_pair"]
    values.extend(
        (
            pair["support"],
            pair["hits"],
            _rounded(pair["raw_rate"]),
            _rounded(pair["smoothed_rate"]),
            _rounded(pair["lift_vs_baseline"]),
        )
    )
    return values


def _history_digest(history: Sequence[int]) -> str:
    encoded = ",".join(str(number) for number in history).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _build_regime_evidence(history: Sequence[int], relations: Sequence[dict[str, Any]]) -> dict[str, Any]:
    recent = history[-min(30, len(history)) :]
    recent_counts = [recent.count(number) for number in ROULETTE_NUMBERS]
    concentration = sum((count / len(recent)) ** 2 for count in recent_counts)
    fair_concentration = 1 / len(ROULETTE_NUMBERS)
    relation_counts = {
        pattern["id"]: sum(relation["classification"] == pattern["id"] for relation in relations)
        for pattern in PATTERN_DEFINITIONS
    }
    strongest = max(relations, key=lambda item: item["deterministic_strength"])
    if relation_counts["unstable_relation"] >= 3:
        deterministic_hint = "unstable"
    elif strongest["deterministic_strength"] >= 0.35:
        deterministic_hint = "transition_driven"
    elif concentration >= fair_concentration * 2.0:
        deterministic_hint = "frequency_concentration"
    else:
        deterministic_hint = "neutral"
    return {
        "recent_window_spins": len(recent),
        "recent_concentration_hhi": _rounded(concentration),
        "fair_uniform_concentration_hhi": _rounded(fair_concentration),
        "relation_classification_counts": relation_counts,
        "strongest_relation": {
            "source_number": strongest["source_number"],
            "target_number": strongest["target_number"],
            "classification": strongest["classification"],
            "deterministic_strength": _rounded(strongest["deterministic_strength"]),
        },
        "deterministic_hint": deterministic_hint,
        "hint_is_not_a_prediction": True,
    }


def build_ranking_state(history: Sequence[int], catalog: dict[str, Any]) -> dict[str, Any]:
    tail = list(history[-HISTORY_TAIL_LIMIT:])
    raw_scope = "full_history" if len(tail) == len(history) else f"last_{len(tail)}_of_{len(history)}"
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "task": {
            "type": "rank_numbers_from_multi_horizon_evidence",
            "roulette": "single_zero_0_to_36",
            "roulette_slug": "pragmatic-auto-roulette",
            "forecast_horizons_spins": list(RELATION_HORIZONS),
            "universe": list(ROULETTE_NUMBERS),
            "include_zero": True,
            "fair_baselines": {
                "next_spin": _rounded(SINGLE_SPIN_BASELINE),
                **{
                    f"within_next_{horizon}_spins": _rounded(horizon_baseline(horizon))
                    for horizon in RELATION_HORIZONS
                },
            },
        },
        "history_context": {
            "history_order": "oldest_to_newest",
            "observed_spins": len(history),
            "previous_observed_number": history[-2] if len(history) >= 2 else None,
            "latest_observed_number": history[-1],
            "raw_history_scope": raw_scope,
            "recent_history": tail,
            "full_history_sha256": _history_digest(history),
        },
        "regime_evidence": _build_regime_evidence(history, catalog["relations"]),
        "evidence_tables": {
            "row_format": "Each row follows its columns array in the same order.",
            "frequency_windows_spins": list(FREQUENCY_WINDOWS),
            "relation_source_number": catalog["source_number"],
            "pair_previous_number": catalog["previous_number"],
            "number_profile_columns": list(NUMBER_PROFILE_COLUMNS),
            "number_profiles": [
                _number_profile_row(history, number) for number in ROULETTE_NUMBERS
            ],
            "relation_columns": list(RELATION_EVIDENCE_COLUMNS),
            "relations_from_latest": [
                _relation_evidence_row(relation) for relation in catalog["relations"]
            ],
        },
        "pattern_catalog": {
            "catalog_version": catalog["catalog_version"],
            "source_number": catalog["source_number"],
            "previous_number": catalog["previous_number"],
            "minimum_support": catalog["minimum_support"],
            "definitions": catalog["definitions"],
            "candidates": [
                {
                    "relation_id": candidate["relation_id"],
                    "question_id": candidate["question_id"],
                    "source_number": candidate["source_number"],
                    "target_number": candidate["target_number"],
                    "classification": candidate["classification"],
                    "deterministic_strength": candidate["deterministic_strength"],
                }
                for candidate in catalog["candidates"]
            ],
        },
        "interpretation_rules": [
            "Pull relations are descriptive conditional frequencies, not causal links.",
            "Use support, smoothing, horizons, recent windows and full-history stability together.",
            "Compare every estimate with its supplied fair-independent baseline.",
            "Low support, recency, gaps and absence alone do not establish predictability.",
            "Next-spin Choice probabilities must form one distribution across all 37 numbers.",
            "The three-spin Noul estimates are marginal events and need not sum to one.",
        ],
    }


def build_ranking_questions(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    questions: dict[str, dict[str, Any]] = {}
    for number in ROULETTE_NUMBERS:
        questions[number_key(number)] = {
            "type": "noul",
            "instructions": (
                f"Estimate whether roulette number {number} appears at least once within the next "
                "3 spins. Use its rows in evidence_tables."
            ),
        }

    questions[NEXT_SPIN_CHOICE_KEY] = {
        "type": "choice",
        "instructions": (
            "Choose the immediately next roulette number using h1 evidence; include 0 equally."
        ),
        "criteria": {str(number): f"Next result is {number}." for number in ROULETTE_NUMBERS},
    }
    questions[REGIME_CHOICE_KEY] = {
        "type": "choice",
        "instructions": "Classify the current evidence structure, not whether a bet will win.",
        "criteria": dict(REGIME_CRITERIA),
    }

    for candidate in catalog["candidates"]:
        questions[candidate["question_id"]] = {
            "type": "score",
            "instructions": (
                f"Score descriptive evidence for {candidate['source_number']} -> "
                f"{candidate['target_number']}; consider support, smoothing, horizons and windows."
            ),
            "criteria": [
                "Insufficient or conflicting evidence.",
                "Weak evidence with limited support, effect or consistency.",
                "Consistent evidence with reasonable support and effect.",
                "Strong evidence, robust support and cross-view consistency.",
            ],
        }
    return questions


def build_ranking_payload(history: Sequence[int]) -> dict[str, Any]:
    catalog = calculate_pull_relations(history)
    state = build_ranking_state(history, catalog)
    questions = build_ranking_questions(catalog)
    return {"catalog": catalog, "state": state, "questions": questions}
