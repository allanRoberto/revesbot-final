"""Deterministic, causal evidence builder for the Estelar pattern.

The module translates the operational parts of the Estelar specification into a
compact evidence block.  It does not claim that roulette spins are causal or
cyclical and it never turns a related number into an exact hit.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Mapping, Sequence


ESTELAR_SCHEMA_VERSION = "jev-estelar-v1"
SHORT_MEMORY = 20
LONG_MEMORY = 200
MAX_REFERENCE_ROWS = 8
MAX_CANDIDATES = 9
MAX_STEP = 3  # zero, one or two intervening spins
MIN_REFERENCE_OCCURRENCES = 2
DISPERSED_TERMINAL_MIN_REFERENCES = 4

CORE_PROPERTY_KEYS = ("dozen", "column", "parity", "color")
REINFORCEMENT_PROPERTY_KEYS = ("range", "street")

# Retrieval strengths only.  These values are not probabilities.
RELATION_STRENGTH = {
    "exact": 6,
    "wheel_neighbor_distance_1": 5,
    "same_terminal": 4,
    "mirror": 3,
    "property_match": 2,
}


def _street(number: int) -> int | None:
    return None if number == 0 else ((number - 1) // 3) + 1


def _card_map(number_catalog: Sequence[Mapping[str, Any]]) -> dict[int, dict[str, Any]]:
    cards: dict[int, dict[str, Any]] = {}
    for raw in number_catalog:
        card = dict(raw)
        number = int(card["number"])
        card["street"] = _street(number)
        cards[number] = card
    if set(cards) != set(range(37)):
        raise ValueError("number_catalog must contain every roulette number from 0 to 36")
    return cards


def _property_relation(
    left: int,
    right: int,
    cards: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any] | None:
    if left == 0 or right == 0:
        return None
    matching_core = [
        key for key in CORE_PROPERTY_KEYS if cards[left].get(key) == cards[right].get(key)
    ]
    if len(matching_core) < 3:
        return None
    reinforcing = [
        key
        for key in REINFORCEMENT_PROPERTY_KEYS
        if cards[left].get(key) is not None and cards[left].get(key) == cards[right].get(key)
    ]
    return {
        "label": "property_match",
        "matching_core_properties": matching_core,
        "reinforcing_properties": reinforcing,
    }


def _best_relation(
    observed: int,
    expected: int,
    *,
    cards: Mapping[int, Mapping[str, Any]],
    relation_labels_fn: Callable[[int, int], Sequence[str]],
) -> dict[str, Any] | None:
    labels = set(relation_labels_fn(observed, expected))
    for label in ("exact", "wheel_neighbor_distance_1", "same_terminal", "mirror"):
        if label in labels:
            return {"label": label, "strength": RELATION_STRENGTH[label]}
    property_match = _property_relation(observed, expected, cards)
    if property_match is None:
        return None
    return {**property_match, "strength": RELATION_STRENGTH["property_match"]}


def _match_pair(
    observed: tuple[int, int],
    expected: tuple[int, int],
    *,
    cards: Mapping[int, Mapping[str, Any]],
    relation_labels_fn: Callable[[int, int], Sequence[str]],
) -> dict[str, Any] | None:
    relations = [
        _best_relation(
            observed_number,
            expected_number,
            cards=cards,
            relation_labels_fn=relation_labels_fn,
        )
        for observed_number, expected_number in zip(observed, expected)
    ]
    if any(relation is None for relation in relations):
        return None
    concrete = [dict(relation) for relation in relations if relation is not None]
    property_count = sum(row["label"] == "property_match" for row in concrete)
    # Parallel properties only complete a structure that has a stronger anchor.
    if property_count == len(concrete):
        return None
    terminal_substitutions = sum(
        row["label"] == "same_terminal" and observed[index] != expected[index]
        for index, row in enumerate(concrete)
    )
    return {
        "relations": concrete,
        "strength": sum(row["strength"] for row in concrete),
        "terminal_substitutions": terminal_substitutions,
    }


def _reference_pairs(
    history: Sequence[int],
    expected: tuple[int, int],
    *,
    cards: Mapping[int, Mapping[str, Any]],
    relation_labels_fn: Callable[[int, int], Sequence[str]],
) -> list[dict[str, Any]]:
    # The final two spins are the current activation and cannot support themselves.
    cutoff = len(history) - 2
    memory_start = max(0, cutoff - LONG_MEMORY)
    rows: list[dict[str, Any]] = []
    for first_index in range(memory_start, cutoff):
        for step in range(1, MAX_STEP + 1):
            second_index = first_index + step
            if second_index >= cutoff:
                break
            observed = (int(history[first_index]), int(history[second_index]))
            match = _match_pair(
                observed,
                expected,
                cards=cards,
                relation_labels_fn=relation_labels_fn,
            )
            if match is None:
                continue
            continuations = [
                {
                    "index": index,
                    "number": int(history[index]),
                    "distance_after_pair": index - second_index,
                }
                for index in range(second_index + 1, min(cutoff, second_index + MAX_STEP + 1))
            ]
            if not continuations:
                continue
            rows.append(
                {
                    "indexes": [first_index, second_index],
                    "observed_pair": list(observed),
                    "gap_between_pair": step - 1,
                    "relations": match["relations"],
                    "match_strength": match["strength"],
                    "terminal_substitutions": match["terminal_substitutions"],
                    "continuations": continuations,
                }
            )
    rows.sort(key=lambda row: (row["indexes"][1], row["match_strength"]), reverse=True)
    return rows


def _eligible_references(rows: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    copied = [dict(row) for row in rows]
    dispersed = any(int(row.get("terminal_substitutions", 0)) > 1 for row in copied)
    required = DISPERSED_TERMINAL_MIN_REFERENCES if dispersed else MIN_REFERENCE_OCCURRENCES
    return copied, len(copied) >= required


def _candidate_evidence(
    references_by_direction: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[int, dict[str, Any]]:
    evidence: dict[int, dict[str, Any]] = defaultdict(
        lambda: {
            "direct_mentions": 0,
            "directions": set(),
            "reference_indexes": set(),
            "distance_weight": 0.0,
            "match_strength": 0,
        }
    )
    for direction, rows in references_by_direction.items():
        for row in rows:
            for continuation in row["continuations"]:
                number = int(continuation["number"])
                if number == 0:
                    continue
                item = evidence[number]
                item["direct_mentions"] += 1
                item["directions"].add(direction)
                item["reference_indexes"].add(tuple(row["indexes"]))
                item["distance_weight"] += 1 / int(continuation["distance_after_pair"])
                item["match_strength"] += int(row["match_strength"])
    return evidence


def _chain_candidates(
    history: Sequence[int],
    direct_numbers: Sequence[int],
) -> dict[int, dict[str, Any]]:
    cutoff = len(history) - 2
    memory_start = max(0, cutoff - LONG_MEMORY)
    direct_set = set(direct_numbers)
    chains: dict[int, dict[str, Any]] = defaultdict(
        lambda: {"chain_mentions": 0, "opened_by": set(), "source_indexes": set()}
    )
    for index in range(memory_start, cutoff - 1):
        source = int(history[index])
        if source not in direct_set:
            continue
        for distance in range(1, MAX_STEP + 1):
            target_index = index + distance
            if target_index >= cutoff:
                break
            target = int(history[target_index])
            if target == 0:
                continue
            item = chains[target]
            item["chain_mentions"] += 1
            item["opened_by"].add(source)
            item["source_indexes"].add(index)
    return chains


def _protection_candidates(
    core_numbers: Sequence[int],
    *,
    cards: Mapping[int, Mapping[str, Any]],
    relation_labels_fn: Callable[[int, int], Sequence[str]],
) -> dict[int, dict[str, Any]]:
    protection: dict[int, dict[str, Any]] = defaultdict(
        lambda: {"protection_for": set(), "relations": set(), "strength": 0}
    )
    for core in core_numbers:
        for candidate in range(37):
            if candidate == core:
                continue
            relation = _best_relation(
                candidate,
                core,
                cards=cards,
                relation_labels_fn=relation_labels_fn,
            )
            if relation is None or relation["label"] == "property_match":
                continue
            item = protection[candidate]
            item["protection_for"].add(core)
            item["relations"].add(relation["label"])
            item["strength"] = max(item["strength"], int(relation["strength"]))
    # Zero is protection metadata in Estelar, never a formation equivalent.
    zero = protection[0]
    zero["relations"].add("zero_protection")
    zero["strength"] = max(zero["strength"], 1)
    return protection


def _serialize_candidate(
    number: int,
    *,
    layer: str,
    score: float,
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    serialized: dict[str, Any] = {
        "number": number,
        "layer": layer,
        "retrieval_score": round(float(score), 6),
    }
    for key, value in evidence.items():
        if isinstance(value, set):
            ordered = sorted(value)
            serialized[f"{key}_count"] = len(ordered)
            serialized[key] = ordered[-8:]
        else:
            serialized[key] = value
    return serialized


def _compact_reference(row: Mapping[str, Any]) -> list[Any]:
    return [
        list(row["indexes"]),
        list(row["observed_pair"]),
        int(row["gap_between_pair"]),
        [relation["label"] for relation in row["relations"]],
        int(row["match_strength"]),
        [
            [
                int(continuation["index"]),
                int(continuation["number"]),
                int(continuation["distance_after_pair"]),
            ]
            for continuation in row["continuations"]
        ],
    ]


def build_estelar_context(
    history: Sequence[int],
    *,
    number_catalog: Sequence[Mapping[str, Any]],
    relation_labels_fn: Callable[[int, int], Sequence[str]],
) -> dict[str, Any]:
    """Build compact Estelar evidence using only the supplied historical cutoff."""
    normalized = [int(number) for number in history]
    cards = _card_map(number_catalog)
    base = {
        "schema_version": ESTELAR_SCHEMA_VERSION,
        "status": "hypothesis_pending_walk_forward_validation",
        "causal_cutoff_index": len(normalized) - 1,
        "history_window": min(len(normalized), LONG_MEMORY),
        "short_memory": normalized[-SHORT_MEMORY:],
        "rules": {
            "reference_memory_spins": LONG_MEMORY,
            "maximum_intervening_spins": MAX_STEP - 1,
            "minimum_reference_occurrences": MIN_REFERENCE_OCCURRENCES,
            "dispersed_terminal_minimum_references": DISPERSED_TERMINAL_MIN_REFERENCES,
            "property_minimum_core_matches": 3,
            "zero_is_protection_not_equivalence": True,
            "related_number_is_not_exact_hit": True,
        },
        "current_pair": normalized[-2:] if len(normalized) >= 2 else normalized,
        "activation": "insufficient_history",
        "directions": {},
        "candidate_layers": {"core": [], "secondary": [], "protection": []},
        "candidate_ranking": [],
        "interpretation_note": (
            "Retrieval scores rank descriptive connections; they are not probabilities "
            "and do not establish a causal roulette cycle."
        ),
    }
    if len(normalized) < 6:
        return base

    current_pair = (normalized[-2], normalized[-1])
    orientations = {
        "forward": current_pair,
        "reverse": (current_pair[1], current_pair[0]),
    }
    active_references: dict[str, list[dict[str, Any]]] = {}
    for direction, expected in orientations.items():
        rows = _reference_pairs(
            normalized,
            expected,
            cards=cards,
            relation_labels_fn=relation_labels_fn,
        )
        eligible_rows, active = _eligible_references(rows)
        required = (
            DISPERSED_TERMINAL_MIN_REFERENCES
            if any(row["terminal_substitutions"] > 1 for row in eligible_rows)
            else MIN_REFERENCE_OCCURRENCES
        )
        base["directions"][direction] = {
            "expected_pair": list(expected),
            "reference_count": len(eligible_rows),
            "required_reference_count": required,
            "active": active,
            "reference_columns": [
                "indexes",
                "observed_pair",
                "gap_between_pair",
                "relation_labels",
                "match_strength",
                "continuations_index_number_distance",
            ],
            "references": [
                _compact_reference(row) for row in eligible_rows[:MAX_REFERENCE_ROWS]
            ],
        }
        if active:
            active_references[direction] = eligible_rows

    if not active_references:
        total_references = sum(row["reference_count"] for row in base["directions"].values())
        base["activation"] = "attention_only" if total_references else "none"
        return base

    base["activation"] = "confirmed_reference_structure"
    direct = _candidate_evidence(active_references)
    direct_ranked = sorted(
        direct,
        key=lambda number: (
            -len(direct[number]["directions"]),
            -direct[number]["direct_mentions"],
            -direct[number]["distance_weight"],
            -direct[number]["match_strength"],
            number,
        ),
    )
    core_numbers = direct_ranked[:3]
    used = set(core_numbers)
    core = []
    for number in core_numbers:
        item = direct[number]
        score = (
            len(item["directions"]) * 100
            + item["direct_mentions"] * 10
            + item["distance_weight"]
            + item["match_strength"] / 100
        )
        core.append(_serialize_candidate(number, layer="core", score=score, evidence=item))

    chains = _chain_candidates(normalized, direct_ranked[:6])
    secondary_numbers = sorted(
        (number for number in chains if number not in used),
        key=lambda number: (
            -len(chains[number]["opened_by"]),
            -chains[number]["chain_mentions"],
            number,
        ),
    )[:3]
    used.update(secondary_numbers)
    secondary = []
    for number in secondary_numbers:
        item = chains[number]
        score = len(item["opened_by"]) * 50 + item["chain_mentions"]
        secondary.append(
            _serialize_candidate(number, layer="secondary", score=score, evidence=item)
        )

    protections = _protection_candidates(
        core_numbers,
        cards=cards,
        relation_labels_fn=relation_labels_fn,
    )
    protection_numbers = sorted(
        (number for number in protections if number not in used),
        key=lambda number: (
            number != 0,
            -len(protections[number]["protection_for"]),
            -protections[number]["strength"],
            number,
        ),
    )[:3]
    protection = []
    for number in protection_numbers:
        item = protections[number]
        score = len(item["protection_for"]) * 10 + item["strength"]
        protection.append(
            _serialize_candidate(number, layer="protection", score=score, evidence=item)
        )

    ranking = (core + secondary + protection)[:MAX_CANDIDATES]
    base["candidate_layers"] = {
        "core": core,
        "secondary": secondary,
        "protection": protection,
    }
    base["candidate_ranking"] = [candidate["number"] for candidate in ranking]
    base["candidate_count"] = len(ranking)
    base["cross_direction_candidates"] = sorted(
        number for number, item in direct.items() if len(item["directions"]) > 1
    )
    return base
