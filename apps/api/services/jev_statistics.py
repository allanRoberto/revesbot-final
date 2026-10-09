"""Deterministic roulette evidence and System One payload construction for Jev.

Jev judges supplied evidence; it does not have to rediscover roulette geometry or
derive number attributes from opaque tokens. Everything in this module is
causal and deterministic. No future result is included in the state.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

from api.schemas.jev import GROUP_KEYS
from api.services.jev_history_service import ROULETTE_SLUG
from api.services.jev_estelar import build_estelar_context


FORECAST_HORIZON_SPINS = 3
RECENT_STATISTICS_WINDOW = 30
RECENT_ENRICHED_WINDOW = 20
MAX_SEQUENCE_EPISODES = 12
SEQUENCE_CONTEXT_DEPTH = 5
RANKING_SEQUENCE_EPISODES = 8
RELATIONAL_SCHEMA_VERSION = "jev-roulette-relational-v1"

EUROPEAN_WHEEL = (
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8,
    23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12,
    35, 3, 26,
)
WHEEL_INDEX = {number: index for index, number in enumerate(EUROPEAN_WHEEL)}
RED_NUMBERS = frozenset({
    1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36,
})
SECTORS = {
    "voisins_zero": frozenset({
        22, 18, 29, 7, 28, 12, 35, 3, 26, 0, 32, 15, 19, 4, 21, 2, 25,
    }),
    "tiers_cylindre": frozenset({27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33}),
    "orphelins": frozenset({1, 20, 14, 31, 9, 17, 34, 6}),
}
MIRROR_PAIRS = (
    (1, 10), (2, 20), (3, 30), (6, 9), (12, 21), (13, 31),
    (16, 19), (23, 32), (26, 29),
)
MIRRORS = {
    number: mirror
    for left, right in MIRROR_PAIRS
    for number, mirror in ((left, right), (right, left))
}
TERMINAL_GROUPS = {
    "147": frozenset({1, 4, 7}),
    "258": frozenset({2, 5, 8}),
    "369": frozenset({3, 6, 9}),
}

BASELINE_ASSUMPTION = (
    "37 equally likely outcomes and independent spins; this is a reference model, "
    "not a measured property of this wheel."
)
STATISTICS_NOTE = (
    "All counts, relations, gaps and sequence similarities are descriptive evidence. "
    "They do not establish a causal cycle or make a random outcome deterministic."
)
QUESTION_TEXT = (
    "Will at least one of target_numbers appear in at least one of the next three spins, "
    "immediately AFTER the last value in state.history?"
)
QUESTION_RULES = [
    "Evaluate the future occurrence itself, not whether it is possible.",
    "The target group is fixed for all three future spins.",
    "A hit requires the observed number itself to belong to target_numbers.",
    "A mirror, wheel neighbor, terminal, digit-sum substitute or analogous number is not a hit unless it is also in target_numbers.",
    "Treat relational and sequence evidence as descriptive context, not as proof of causality.",
    "Discount evidence with low support and compare observed rates with the supplied fair-independent baseline.",
    "Do not include any already observed spin in the target event.",
    "Several groups may hit; this is not an exclusive choice.",
    "Use only the supplied past data. Future results are unknown.",
]


def _digit_sum(number: int) -> int:
    return sum(int(character) for character in str(number))


def _terminal_group(number: int) -> str | None:
    terminal = number % 10
    return next((name for name, members in TERMINAL_GROUPS.items() if terminal in members), None)


def _sector(number: int) -> str:
    return next(name for name, members in SECTORS.items() if number in members)


def _wheel_distance(left: int, right: int) -> int:
    distance = abs(WHEEL_INDEX[left] - WHEEL_INDEX[right])
    return min(distance, len(EUROPEAN_WHEEL) - distance)


def number_card(number: int) -> dict[str, Any]:
    """Return an explicit, JSON-safe ontology card for one roulette number."""
    if isinstance(number, bool) or not isinstance(number, int) or not 0 <= number <= 36:
        raise ValueError("number must be an integer from 0 to 36")
    position = WHEEL_INDEX[number]
    return {
        "number": number,
        "wheel_position": position,
        "wheel_neighbors_distance_1": [
            EUROPEAN_WHEEL[(position - 1) % 37],
            EUROPEAN_WHEEL[(position + 1) % 37],
        ],
        "wheel_neighbors_distance_2": [
            EUROPEAN_WHEEL[(position - 2) % 37],
            EUROPEAN_WHEEL[(position + 2) % 37],
        ],
        "mirror": MIRRORS.get(number),
        "digit_sum": _digit_sum(number),
        "terminal": number % 10,
        "terminal_group": _terminal_group(number),
        "color": "green" if number == 0 else ("red" if number in RED_NUMBERS else "black"),
        "parity": None if number == 0 else ("even" if number % 2 == 0 else "odd"),
        "dozen": None if number == 0 else ((number - 1) // 12) + 1,
        "column": None if number == 0 else ((number - 1) % 3) + 1,
        "range": None if number == 0 else ("low" if number <= 18 else "high"),
        "sector": _sector(number),
    }


NUMBER_CATALOG = tuple(number_card(number) for number in range(37))


def relation_labels(left: int, right: int) -> list[str]:
    """Describe every supported relation between two observed numbers."""
    labels: list[str] = []
    if left == right:
        labels.append("exact")
    wheel_distance = _wheel_distance(left, right)
    if wheel_distance == 1:
        labels.append("wheel_neighbor_distance_1")
    elif wheel_distance == 2:
        labels.append("wheel_neighbor_distance_2")
    if MIRRORS.get(left) == right:
        labels.append("mirror")
    if _digit_sum(left) == right or _digit_sum(right) == left:
        labels.append("digit_sum_substitution")
    if left != 0 and right != 0 and left % 10 == right % 10:
        labels.append("same_terminal")
    left_group = _terminal_group(left)
    if left_group is not None and left_group == _terminal_group(right):
        labels.append("same_terminal_group")
    return labels


_RELATION_SIMILARITY = {
    "exact": 1.0,
    "mirror": 0.85,
    "wheel_neighbor_distance_1": 0.80,
    "wheel_neighbor_distance_2": 0.65,
    "digit_sum_substitution": 0.55,
    "same_terminal": 0.35,
    "same_terminal_group": 0.20,
}


def _sequence_alignment(historical: Sequence[int], current: Sequence[int]) -> dict[str, Any]:
    positions = []
    scores = []
    for offset, (past_number, current_number) in enumerate(zip(historical, current), start=-2):
        relations = relation_labels(past_number, current_number)
        score = max((_RELATION_SIMILARITY[label] for label in relations), default=0.0)
        positions.append({
            "offset": offset,
            "historical_number": past_number,
            "current_number": current_number,
            "relations": relations,
            "position_similarity": score,
        })
        scores.append(score)
    return {
        "positions": positions,
        "mean_similarity": round(sum(scores) / len(scores), 4),
        "exact_positions": sum("exact" in row["relations"] for row in positions),
    }


def _sequence_evidence(history: Sequence[int]) -> dict[str, Any]:
    if len(history) < 3:
        return {
            "anchor_trio": list(history),
            "exact_occurrences": [],
            "relational_analogues": [],
        }

    anchor = list(history[-3:])
    current_start = len(history) - 3
    exact_occurrences = []
    relational_analogues = []
    for start in range(current_start):
        historical = list(history[start:start + 3])
        before = list(history[max(0, start - SEQUENCE_CONTEXT_DEPTH):start])
        after = list(history[
            start + 3:min(len(history), start + 3 + SEQUENCE_CONTEXT_DEPTH)
        ])
        alignment = _sequence_alignment(historical, anchor)
        episode = {
            "start_index": start,
            "historical_trio": historical,
            "before": before,
            "after": after,
            "alignment": alignment,
        }
        if historical == anchor:
            exact_occurrences.append(episode)
        elif alignment["mean_similarity"] >= 0.55:
            relational_analogues.append(episode)

    exact_occurrence_count = len(exact_occurrences)
    exact_occurrences = exact_occurrences[-MAX_SEQUENCE_EPISODES:]
    relational_analogues.sort(
        key=lambda row: (row["alignment"]["mean_similarity"], row["start_index"]),
        reverse=True,
    )
    return {
        "anchor_trio": anchor,
        "anchor_order": "oldest_to_newest",
        "exact_occurrence_count": exact_occurrence_count,
        "exact_occurrence_count_returned": len(exact_occurrences),
        "exact_occurrences": exact_occurrences,
        "relational_analogue_count": len(relational_analogues),
        "relational_analogue_count_returned": min(len(relational_analogues), MAX_SEQUENCE_EPISODES),
        "relational_analogues": relational_analogues[:MAX_SEQUENCE_EPISODES],
        "selection_note": "Only prior episodes are eligible; no result after the prediction cutoff is used.",
    }


def build_ranking_relational_context(history: Sequence[int]) -> dict[str, Any]:
    """Build a compact relational context shared by live ranking and backtest.

    The ranking request has a strict byte limit, so immutable number facts and
    sequence episodes are represented as declared-column rows instead of verbose
    objects. The source history is always the caller's already-cutoff window.
    """
    evidence = _sequence_evidence(history)
    episode_columns = [
        "start_index",
        "historical_trio",
        "before_up_to_5",
        "after_up_to_5",
        "mean_similarity",
        "relations_by_position",
    ]

    def episode_row(episode: Mapping[str, Any]) -> list[Any]:
        return [
            episode["start_index"],
            episode["historical_trio"],
            episode["before"],
            episode["after"],
            episode["alignment"]["mean_similarity"],
            [position["relations"] for position in episode["alignment"]["positions"]],
        ]

    profile_columns = [
        "number",
        "wheel_position",
        "wheel_neighbor_d1_left",
        "wheel_neighbor_d1_right",
        "wheel_neighbor_d2_left",
        "wheel_neighbor_d2_right",
        "mirror",
        "digit_sum",
        "terminal",
        "terminal_group",
        "range",
        "sector",
    ]
    profiles = [
        [
            card["number"],
            card["wheel_position"],
            *card["wheel_neighbors_distance_1"],
            *card["wheel_neighbors_distance_2"],
            card["mirror"],
            card["digit_sum"],
            card["terminal"],
            card["terminal_group"],
            card["range"],
            card["sector"],
        ]
        for card in NUMBER_CATALOG
    ]
    estelar = build_estelar_context(
        history,
        number_catalog=NUMBER_CATALOG,
        relation_labels_fn=relation_labels,
    )
    return {
        "schema_version": RELATIONAL_SCHEMA_VERSION,
        "prediction_cutoff_index": len(history) - 1,
        "relations_are_descriptive_not_causal": True,
        "roulette_ontology": {
            "wheel_order": list(EUROPEAN_WHEEL),
            "mirror_pairs": [list(pair) for pair in MIRROR_PAIRS],
            "terminal_groups": {name: sorted(members) for name, members in TERMINAL_GROUPS.items()},
            "terminal_definition": "last decimal digit",
            "digit_sum_definition": "sum of decimal digits",
            "sectors": {name: sorted(members) for name, members in SECTORS.items()},
        },
        "number_profile_columns": profile_columns,
        "number_profiles": profiles,
        "sequence_evidence": {
            "anchor_trio": evidence["anchor_trio"],
            "anchor_order": evidence.get("anchor_order", "oldest_to_newest"),
            "episode_columns": episode_columns,
            "exact_occurrence_count": evidence.get("exact_occurrence_count", 0),
            "exact_episodes": [
                episode_row(episode)
                for episode in evidence["exact_occurrences"][-RANKING_SEQUENCE_EPISODES:]
            ],
            "relational_analogue_count": evidence.get("relational_analogue_count", 0),
            "relational_episodes": [
                episode_row(episode)
                for episode in evidence["relational_analogues"][:RANKING_SEQUENCE_EPISODES]
            ],
        },
        "known_patterns": {
            "estelar": estelar,
        },
        "interpretation_rules": [
            "Exact equality, mirror, wheel distance, terminal and digit-sum relations are separate evidence types.",
            "Sequence similarity is a retrieval score, not a probability and not proof of a repeating cycle.",
            "Estelar candidate retrieval is descriptive evidence and must be discounted until walk-forward validation supports it.",
            "Estelar protection numbers are context only and do not count as exact hits.",
            "Only an exact future number wins; a related substitute does not count as that number.",
            "All episode results are before or at the supplied historical cutoff; no later spin is present.",
        ],
    }


def calculate_group_statistics(history: Sequence[int], numbers: Sequence[int]) -> dict[str, Any]:
    group_numbers = list(numbers)
    group_set = set(group_numbers)
    recent_window = list(history[-min(RECENT_STATISTICS_WINDOW, len(history)):])

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


def _attribute_profile(numbers: Sequence[int]) -> dict[str, Any]:
    cards = [NUMBER_CATALOG[number] for number in numbers]
    keys = ("color", "parity", "dozen", "column", "range", "sector", "terminal_group")
    profile: dict[str, Any] = {}
    for key in keys:
        counts = Counter(card[key] for card in cards if card[key] is not None)
        profile[key] = dict(sorted(counts.items(), key=lambda row: str(row[0])))
    profile["terminals"] = dict(sorted(Counter(card["terminal"] for card in cards).items()))
    profile["digit_sums"] = dict(sorted(Counter(card["digit_sum"] for card in cards).items()))
    return profile


def _episode_group_evidence(episodes: Sequence[Mapping[str, Any]], numbers: Sequence[int]) -> dict[str, Any]:
    group = set(numbers)
    complete = [episode for episode in episodes if len(episode["after"]) >= FORECAST_HORIZON_SPINS]
    hits = [episode for episode in complete if any(number in group for number in episode["after"][:3])]
    return {
        "complete_episodes": len(complete),
        "episodes_with_exact_group_hit_in_next_three": len(hits),
        "observed_rate": (len(hits) / len(complete)) if complete else None,
    }


def _recent_relation_evidence(history: Sequence[int], numbers: Sequence[int]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for observed in history[-RECENT_STATISTICS_WINDOW:]:
        observed_labels = {
            label
            for target in numbers
            for label in relation_labels(observed, target)
        }
        counts.update(observed_labels)
    return dict(sorted(counts.items()))


def build_jev_state(
    history: Sequence[int], group_statistics: Mapping[str, Mapping[str, Any]],
    *, roulette_slug: str = ROULETTE_SLUG,
) -> dict[str, Any]:
    sequence_evidence = _sequence_evidence(history)
    recent = list(history[-RECENT_ENRICHED_WINDOW:])
    recent_enriched = [
        {
            "offset_from_latest": index - len(recent) + 1,
            **NUMBER_CATALOG[number],
        }
        for index, number in enumerate(recent)
    ]
    groups = {}
    for group_id in GROUP_KEYS:
        statistics = dict(group_statistics[group_id])
        numbers = list(statistics["numbers"])
        groups[group_id] = {
            **statistics,
            "attribute_profile": _attribute_profile(numbers),
            "recent_relation_counts": _recent_relation_evidence(history, numbers),
            "exact_sequence_evidence": _episode_group_evidence(
                sequence_evidence["exact_occurrences"], numbers
            ),
            "relational_sequence_evidence": _episode_group_evidence(
                sequence_evidence["relational_analogues"], numbers
            ),
        }

    estelar = build_estelar_context(
        history,
        number_catalog=NUMBER_CATALOG,
        relation_labels_fn=relation_labels,
    )
    return {
        "schema_version": RELATIONAL_SCHEMA_VERSION,
        "task": {
            "kind": "non_exclusive_group_occurrence_forecast",
            "prediction_cutoff": "immediately_after_history_last_value",
            "success_definition": "At least one exact observed number belongs to the fixed target group within the next three spins.",
            "relations_are_context_not_hits": True,
        },
        "roulette": "single_zero_0_to_36",
        "roulette_slug": roulette_slug,
        "roulette_ontology": {
            "wheel_order": list(EUROPEAN_WHEEL),
            "wheel_neighbor_distances": [1, 2],
            "mirror_pairs": [list(pair) for pair in MIRROR_PAIRS],
            "terminal_definition": "last decimal digit",
            "terminal_groups": {name: sorted(members) for name, members in TERMINAL_GROUPS.items()},
            "digit_sum_definition": "sum of decimal digits",
            "sectors": {name: sorted(members) for name, members in SECTORS.items()},
        },
        "number_catalog": {str(card["number"]): dict(card) for card in NUMBER_CATALOG},
        "history_order": "oldest_to_newest",
        "history": list(history),
        "observed_spins": len(history),
        "latest_observed_number": history[-1],
        "recent_enriched_history": recent_enriched,
        "sequence_evidence": sequence_evidence,
        "known_patterns": {
            "estelar": estelar,
        },
        "forecast_horizon_spins": FORECAST_HORIZON_SPINS,
        "groups": groups,
        "baseline_assumption": BASELINE_ASSUMPTION,
        "statistics_note": STATISTICS_NOTE,
    }


def build_jev_questions(groups: Mapping[str, Sequence[int]]) -> dict[str, dict[str, Any]]:
    return {
        group_id: {
            "type": "noul",
            "instructions": {
                "target_group_id": group_id,
                "target_numbers": list(groups[group_id]),
                "question": QUESTION_TEXT,
                "evidence_to_consider": [
                    f"state.groups.{group_id}",
                    "state.recent_enriched_history",
                "state.sequence_evidence",
                "state.known_patterns",
                "state.roulette_ontology",
                    "state.number_catalog",
                ],
                "rules": list(QUESTION_RULES),
            },
            "criteria": {
                "true": "At least one of the next three exact results is in target_numbers.",
                "false": "None of the next three exact results is in target_numbers.",
            },
        }
        for group_id in GROUP_KEYS
    }
