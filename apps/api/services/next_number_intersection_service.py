from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Sequence

from api.core.db import history_coll
from api.services.roulette_analysis import EURO_WHEEL_ORDER


DEFAULT_INTERSECTION_OCCURRENCES = 15
MAX_INTERSECTION_OCCURRENCES = 50
INITIAL_HISTORY_SCAN = 1_000
MAX_HISTORY_SCAN = 10_000
NUMBER_MIN = 0
NUMBER_MAX = 36
INTERSECTION_VERSION = "next_number_intersection_v1"

WHEEL_ORDER = tuple(int(number) for number in EURO_WHEEL_ORDER)
WHEEL_INDEX = {number: index for index, number in enumerate(WHEEL_ORDER)}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_roulette_id(roulette_id: Any) -> str:
    safe_roulette_id = str(roulette_id or "").strip()
    if not safe_roulette_id:
        raise ValueError("roulette_id e obrigatorio.")
    return safe_roulette_id


def _coerce_number(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("Os numeros base devem estar entre 0 e 36.")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError("Os numeros base devem estar entre 0 e 36.") from None
    if number < NUMBER_MIN or number > NUMBER_MAX:
        raise ValueError("Os numeros base devem estar entre 0 e 36.")
    return number


def normalize_base_numbers(values: Sequence[Any]) -> List[int]:
    numbers = [_coerce_number(value) for value in values]
    if len(numbers) != 3:
        raise ValueError("Selecione exatamente 3 numeros base.")
    if len(set(numbers)) != len(numbers):
        raise ValueError("Selecione 3 numeros base diferentes.")
    return numbers


def _coerce_occurrence_limit(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError(
            f"occurrences deve estar entre 1 e {MAX_INTERSECTION_OCCURRENCES}."
        )
    try:
        limit = int(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"occurrences deve estar entre 1 e {MAX_INTERSECTION_OCCURRENCES}."
        ) from None
    if limit < 1 or limit > MAX_INTERSECTION_OCCURRENCES:
        raise ValueError(
            f"occurrences deve estar entre 1 e {MAX_INTERSECTION_OCCURRENCES}."
        )
    return limit


def extract_followups(
    history_desc: Sequence[Any],
    base_numbers: Sequence[Any],
    occurrence_limit: Any = DEFAULT_INTERSECTION_OCCURRENCES,
) -> Dict[int, List[int]]:
    """Extrai o giro seguinte às ocorrências, com o histórico mais recente primeiro."""

    safe_bases = normalize_base_numbers(base_numbers)
    safe_limit = _coerce_occurrence_limit(occurrence_limit)
    selected = set(safe_bases)
    groups: Dict[int, List[int]] = {number: [] for number in safe_bases}

    normalized_history: List[int | None] = []
    for value in history_desc:
        try:
            normalized_history.append(_coerce_number(value))
        except ValueError:
            normalized_history.append(None)

    # No histórico descendente, history[index - 1] saiu cronologicamente
    # depois de history[index]. A posição zero ainda não possui sucessor.
    for index in range(1, len(normalized_history)):
        base_number = normalized_history[index]
        pulled_number = normalized_history[index - 1]
        if base_number not in selected or pulled_number is None:
            continue
        bucket = groups[int(base_number)]
        if len(bucket) < safe_limit:
            bucket.append(int(pulled_number))
        if all(len(groups[number]) >= safe_limit for number in safe_bases):
            break

    return groups


def _frequency_rows(values: Sequence[int]) -> List[Dict[str, int]]:
    counts = Counter(int(value) for value in values)
    return [
        {"number": int(number), "count": int(count)}
        for number, count in sorted(
            counts.items(),
            key=lambda item: (-int(item[1]), int(item[0])),
        )
    ]


def rank_neighbor_intersections(
    groups: Mapping[int, Sequence[int]],
    base_numbers: Sequence[Any],
) -> List[Dict[str, Any]]:
    safe_bases = normalize_base_numbers(base_numbers)
    counters = [Counter(int(value) for value in groups.get(base, [])) for base in safe_bases]
    relations: Dict[tuple[int, int, int], Dict[str, Any]] = {}

    for pivot_index, pivot in enumerate(WHEEL_ORDER):
        left_neighbor = WHEEL_ORDER[(pivot_index - 1) % len(WHEEL_ORDER)]
        right_neighbor = WHEEL_ORDER[(pivot_index + 1) % len(WHEEL_ORDER)]
        neighborhood = {left_neighbor, pivot, right_neighbor}
        options = [
            [number for number in counter if number in neighborhood]
            for counter in counters
        ]
        if any(not values for values in options):
            continue

        for first in options[0]:
            for second in options[1]:
                for third in options[2]:
                    values = (int(first), int(second), int(third))
                    # A relação precisa conter seu centro. Assim, com três bases,
                    # ela varia apenas de zero a dois vizinhos substitutos.
                    if pivot not in values:
                        continue
                    neighbor_count = sum(number != pivot for number in values)
                    occurrence_counts = tuple(
                        int(counters[index][number])
                        for index, number in enumerate(values)
                    )
                    support_product = 1
                    for count in occurrence_counts:
                        support_product *= count
                    support_sum = sum(occurrence_counts)
                    candidate = {
                        "center_number": int(pivot),
                        "values": list(values),
                        "neighbor_count": int(neighbor_count),
                        "wheel_neighbors": [int(left_neighbor), int(right_neighbor)],
                        "occurrence_counts": list(occurrence_counts),
                        "support_product": int(support_product),
                        "support_sum": int(support_sum),
                    }
                    previous = relations.get(values)
                    if previous is None:
                        relations[values] = candidate
                        continue
                    previous_key = (
                        int(previous["neighbor_count"]),
                        -int(previous["support_product"]),
                        -int(previous["support_sum"]),
                    )
                    candidate_key = (
                        int(candidate["neighbor_count"]),
                        -int(candidate["support_product"]),
                        -int(candidate["support_sum"]),
                    )
                    if candidate_key < previous_key:
                        relations[values] = candidate

    ranking = sorted(
        relations.values(),
        key=lambda item: (
            int(item["neighbor_count"]),
            -int(item["support_product"]),
            -int(item["support_sum"]),
            int(item["center_number"]),
            tuple(int(value) for value in item["values"]),
        ),
    )
    strength_by_neighbors = {
        0: ("exact", "Exata"),
        1: ("one_neighbor", "Forte - 1 vizinho"),
        2: ("two_neighbors", "Fraca - 2 vizinhos"),
    }
    for position, item in enumerate(ranking, start=1):
        strength, strength_label = strength_by_neighbors[int(item["neighbor_count"])]
        item["position"] = int(position)
        item["strength"] = strength
        item["strength_label"] = strength_label
    return ranking


def build_next_number_intersection_payload(
    *,
    roulette_id: str,
    history_desc: Sequence[Any],
    base_numbers: Sequence[Any],
    occurrence_limit: Any = DEFAULT_INTERSECTION_OCCURRENCES,
    generated_at_utc: datetime | None = None,
    last_history_timestamp_utc: Any = None,
) -> Dict[str, Any]:
    safe_roulette_id = _coerce_roulette_id(roulette_id)
    safe_bases = normalize_base_numbers(base_numbers)
    safe_limit = _coerce_occurrence_limit(occurrence_limit)
    groups = extract_followups(history_desc, safe_bases, safe_limit)
    ranking = rank_neighbor_intersections(groups, safe_bases)

    group_rows = []
    for base_number in safe_bases:
        pulled_numbers = list(groups[base_number])
        group_rows.append(
            {
                "base_number": int(base_number),
                "pulled_numbers": pulled_numbers,
                "collected_occurrences": len(pulled_numbers),
                "requested_occurrences": int(safe_limit),
                "complete": len(pulled_numbers) >= safe_limit,
                "unique_count": len(set(pulled_numbers)),
                "frequencies": _frequency_rows(pulled_numbers),
            }
        )

    counts = Counter(int(item["neighbor_count"]) for item in ranking)
    complete = all(bool(group["complete"]) for group in group_rows)
    warnings = []
    if not complete:
        incomplete = [
            f'{group["base_number"]}: {group["collected_occurrences"]}/{safe_limit}'
            for group in group_rows
            if not group["complete"]
        ]
        warnings.append(
            "Historico insuficiente para completar todas as bases ("
            + ", ".join(incomplete)
            + ")."
        )

    return {
        "roulette_id": safe_roulette_id,
        "version": INTERSECTION_VERSION,
        "generated_at_utc": generated_at_utc or _utc_now(),
        "last_history_timestamp_utc": last_history_timestamp_utc,
        "base_numbers": safe_bases,
        "occurrence_limit": int(safe_limit),
        "history_scanned": len(history_desc),
        "complete": complete,
        "warnings": warnings,
        "groups": group_rows,
        "summary": {
            "total_relations": len(ranking),
            "exact_count": int(counts.get(0, 0)),
            "one_neighbor_count": int(counts.get(1, 0)),
            "two_neighbors_count": int(counts.get(2, 0)),
        },
        "ranking": ranking,
    }


async def get_next_number_intersection(
    *,
    roulette_id: str,
    base_numbers: Sequence[Any],
    occurrence_limit: Any = DEFAULT_INTERSECTION_OCCURRENCES,
) -> Dict[str, Any]:
    safe_roulette_id = _coerce_roulette_id(roulette_id)
    safe_bases = normalize_base_numbers(base_numbers)
    safe_limit = _coerce_occurrence_limit(occurrence_limit)
    initial_limit = min(
        MAX_HISTORY_SCAN,
        max(INITIAL_HISTORY_SCAN, safe_limit * 75),
    )

    async def fetch(limit: int) -> List[Dict[str, Any]]:
        cursor = (
            history_coll.find(
                {"roulette_id": safe_roulette_id},
                {"_id": 1, "value": 1, "timestamp": 1},
            )
            .sort([("timestamp", -1), ("_id", -1)])
            .limit(limit)
        )
        return await cursor.to_list(length=limit)

    docs = await fetch(initial_limit)
    if not docs:
        raise LookupError(f"Nenhum historico encontrado para {safe_roulette_id}.")

    def build(current_docs: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        return build_next_number_intersection_payload(
            roulette_id=safe_roulette_id,
            history_desc=[doc.get("value") for doc in current_docs],
            base_numbers=safe_bases,
            occurrence_limit=safe_limit,
            last_history_timestamp_utc=current_docs[0].get("timestamp") if current_docs else None,
        )

    payload = build(docs)
    if not payload["complete"] and initial_limit < MAX_HISTORY_SCAN:
        docs = await fetch(MAX_HISTORY_SCAN)
        payload = build(docs)
    return payload


__all__ = [
    "DEFAULT_INTERSECTION_OCCURRENCES",
    "MAX_INTERSECTION_OCCURRENCES",
    "build_next_number_intersection_payload",
    "extract_followups",
    "get_next_number_intersection",
    "normalize_base_numbers",
    "rank_neighbor_intersections",
]
