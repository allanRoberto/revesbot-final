from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List

from api.helpers.utils.get_mirror import get_mirror
from api.services.base_suggestion import (
    WHEEL_INDEX,
    WHEEL_ORDER,
    get_neighbors as get_wheel_neighbors,
)


PROTECTED_HISTORY_WINDOW = 50
PROTECTED_EXCLUDED_COUNT = 2
PROTECTED_WAIT_SPINS = 3
PROTECTED_DIRECT_NEIGHBOR_SPAN = 1
PROTECTED_DERIVED_NEIGHBOR_SPAN = 1

RELATION_LABELS = {
    "excluded": "numero excluido",
    "sequence": "sequencia numerica",
    "sequence_mirror": "espelho da sequencia",
    "sequence_neighbor": "vizinho da sequencia",
    "wheel_neighbor": "vizinho de roleta",
    "neighbor_sequence": "sequencia do vizinho",
    "mirror": "espelho",
    "mirror_neighbor": "vizinho do espelho",
    "neighbor_mirror": "espelho do vizinho",
    "same_terminal": "mesmo terminal",
}

ENABLED_PROTECTED_RELATIONS = {
    "excluded",
    "sequence",
    "mirror",
    "same_terminal",
}


def _safe_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if 0 <= parsed <= 36:
        return parsed
    return None


def _is_relation_enabled(relation: str) -> bool:
    return str(relation or "") in ENABLED_PROTECTED_RELATIONS


def _history_window(history_arr: List[int], from_index: int, window: int = PROTECTED_HISTORY_WINDOW) -> List[int]:
    values: List[int] = []
    end = max(0, int(from_index)) + max(1, int(window))
    for value in history_arr[max(0, int(from_index)):end]:
        parsed = _safe_int(value)
        if parsed is not None:
            values.append(parsed)
    return values


def _build_frequency_map(history_slice: List[int]) -> Dict[int, int]:
    counts = Counter(history_slice)
    return {number: int(counts.get(number, 0)) for number in range(37)}


def _same_terminal_numbers(base: int) -> Iterable[int]:
    terminal = int(base) % 10
    for number in range(37):
        if number != int(base) and (number % 10) == terminal:
            yield number


def _wheel_distance(left: int, right: int) -> int:
    if int(left) not in WHEEL_INDEX or int(right) not in WHEEL_INDEX:
        return 99
    wheel_size = len(WHEEL_ORDER)
    left_index = WHEEL_INDEX[int(left)]
    right_index = WHEEL_INDEX[int(right)]
    distance = abs(left_index - right_index)
    return min(distance, wheel_size - distance)


def _add_guard_detail(
    details: Dict[int, List[Dict[str, Any]]],
    seen: Dict[int, set[tuple[int, str, int | None]]],
    *,
    number: Any,
    source: int,
    relation: str,
    via: int | None = None,
) -> None:
    parsed = _safe_int(number)
    if parsed is None:
        return
    safe_via = _safe_int(via)
    key = (int(source), str(relation), safe_via)
    if key in seen[parsed]:
        return
    seen[parsed].add(key)
    item: Dict[str, Any] = {
        "source": int(source),
        "relation": str(relation),
    }
    if safe_via is not None:
        item["via"] = safe_via
    details[parsed].append(item)


def _build_guard_details(excluded_numbers: List[int]) -> Dict[int, List[Dict[str, Any]]]:
    details: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    seen: Dict[int, set[tuple[int, str, int | None]]] = defaultdict(set)

    for base in excluded_numbers:
        if _is_relation_enabled("excluded"):
            _add_guard_detail(details, seen, number=base, source=base, relation="excluded")

        if base > 0:
            sequence_number = base - 1
            if _is_relation_enabled("sequence"):
                _add_guard_detail(details, seen, number=sequence_number, source=base, relation="sequence")
            if _is_relation_enabled("sequence_neighbor"):
                for sequence_neighbor in get_wheel_neighbors(sequence_number, span=PROTECTED_DERIVED_NEIGHBOR_SPAN):
                    _add_guard_detail(
                        details,
                        seen,
                        number=sequence_neighbor,
                        source=base,
                        relation="sequence_neighbor",
                        via=sequence_number,
                    )
            if _is_relation_enabled("sequence_mirror"):
                for sequence_mirror in get_mirror(sequence_number):
                    _add_guard_detail(
                        details,
                        seen,
                        number=sequence_mirror,
                        source=base,
                        relation="sequence_mirror",
                        via=sequence_number,
                    )
        if base < 36:
            sequence_number = base + 1
            if _is_relation_enabled("sequence"):
                _add_guard_detail(details, seen, number=sequence_number, source=base, relation="sequence")
            if _is_relation_enabled("sequence_neighbor"):
                for sequence_neighbor in get_wheel_neighbors(sequence_number, span=PROTECTED_DERIVED_NEIGHBOR_SPAN):
                    _add_guard_detail(
                        details,
                        seen,
                        number=sequence_neighbor,
                        source=base,
                        relation="sequence_neighbor",
                        via=sequence_number,
                    )
            if _is_relation_enabled("sequence_mirror"):
                for sequence_mirror in get_mirror(sequence_number):
                    _add_guard_detail(
                        details,
                        seen,
                        number=sequence_mirror,
                        source=base,
                        relation="sequence_mirror",
                        via=sequence_number,
                    )

        if _is_relation_enabled("wheel_neighbor"):
            for neighbor in get_wheel_neighbors(base, span=PROTECTED_DIRECT_NEIGHBOR_SPAN):
                _add_guard_detail(details, seen, number=neighbor, source=base, relation="wheel_neighbor")
        if _is_relation_enabled("neighbor_sequence") or _is_relation_enabled("neighbor_mirror"):
            for neighbor in get_wheel_neighbors(base, span=PROTECTED_DERIVED_NEIGHBOR_SPAN):
                if _is_relation_enabled("neighbor_sequence"):
                    if neighbor > 0:
                        _add_guard_detail(
                            details,
                            seen,
                            number=neighbor - 1,
                            source=base,
                            relation="neighbor_sequence",
                            via=neighbor,
                        )
                    if neighbor < 36:
                        _add_guard_detail(
                            details,
                            seen,
                            number=neighbor + 1,
                            source=base,
                            relation="neighbor_sequence",
                            via=neighbor,
                        )
                if _is_relation_enabled("neighbor_mirror"):
                    for neighbor_mirror in get_mirror(neighbor):
                        _add_guard_detail(
                            details,
                            seen,
                            number=neighbor_mirror,
                            source=base,
                            relation="neighbor_mirror",
                            via=neighbor,
                        )

        if _is_relation_enabled("mirror") or _is_relation_enabled("mirror_neighbor"):
            for mirror in get_mirror(base):
                if _is_relation_enabled("mirror"):
                    _add_guard_detail(details, seen, number=mirror, source=base, relation="mirror", via=mirror)
                if _is_relation_enabled("mirror_neighbor"):
                    for neighbor in get_wheel_neighbors(mirror, span=PROTECTED_DERIVED_NEIGHBOR_SPAN):
                        _add_guard_detail(
                            details,
                            seen,
                            number=neighbor,
                            source=base,
                            relation="mirror_neighbor",
                            via=mirror,
                        )

        if _is_relation_enabled("same_terminal"):
            for number in _same_terminal_numbers(base):
                _add_guard_detail(details, seen, number=number, source=base, relation="same_terminal")

    return {int(number): list(items) for number, items in details.items()}


def _build_relation_description(match: Dict[str, Any]) -> str:
    source = _safe_int(match.get("source"))
    relation = str(match.get("relation") or "")
    via = _safe_int(match.get("via"))
    label = RELATION_LABELS.get(relation, relation or "relacao protegida")

    if source is None:
        return label
    if relation == "mirror" and via is not None:
        return f"{label} {via} de {source}"
    if relation == "sequence_mirror" and via is not None:
        return f"{label} {via} de {source}"
    if relation == "sequence_neighbor" and via is not None:
        return f"{label} {via} de {source}"
    if relation == "neighbor_sequence" and via is not None:
        return f"{label} {via} de {source}"
    if relation == "mirror_neighbor" and via is not None:
        return f"{label} {via} de {source}"
    if relation == "neighbor_mirror" and via is not None:
        return f"{label} {via} de {source}"
    return f"{label} de {source}"


def _collect_trigger_numbers(history_arr: List[int], from_index: int, focus_number: int) -> List[int]:
    trigger_numbers: List[int] = []
    candidates = [focus_number]
    previous_index = max(0, int(from_index)) + 1
    if previous_index < len(history_arr):
        candidates.append(history_arr[previous_index])

    for value in candidates:
        parsed = _safe_int(value)
        if parsed is None or parsed in trigger_numbers:
            continue
        trigger_numbers.append(parsed)
    return trigger_numbers


def _collect_guard_matches(
    guard_details: Dict[int, List[Dict[str, Any]]],
    trigger_numbers: List[int],
) -> List[Dict[str, Any]]:
    matches: List[Dict[str, Any]] = []
    seen: set[tuple[int, int, str, int | None]] = set()

    for trigger_number in trigger_numbers:
        trigger_matches = guard_details.get(int(trigger_number), [])
        for match in trigger_matches:
            source = _safe_int(match.get("source"))
            relation = str(match.get("relation") or "")
            via = _safe_int(match.get("via"))
            if source is None:
                continue
            dedupe_key = (int(trigger_number), int(source), relation, via)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            enriched_match = dict(match)
            enriched_match["trigger_number"] = int(trigger_number)
            matches.append(enriched_match)

    return matches


def _build_wait_reason(
    trigger_numbers: List[int],
    matches: List[Dict[str, Any]],
    excluded_numbers: List[int],
) -> str:
    if not matches:
        return ""

    trigger_details: List[str] = []
    for trigger_number in trigger_numbers:
        current_matches = [
            match
            for match in matches
            if _safe_int(match.get("trigger_number")) == int(trigger_number)
        ]
        if not current_matches:
            continue
        details_label = ", ".join(_build_relation_description(match) for match in current_matches)
        trigger_details.append(
            f"{trigger_number}{f' ({details_label})' if details_label else ''}"
        )

    details_label = ", ".join(trigger_details)
    excluded_label = ", ".join(str(number) for number in excluded_numbers)
    return (
        f"Contexto recente {details_label or 'n/a'} tocou a zona protegida dos excluidos {excluded_label}"
        f". Aguarde {PROTECTED_WAIT_SPINS} giros."
    )


def _group_matches_by_source(matches: List[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    grouped: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for match in matches:
        source = _safe_int(match.get("source"))
        if source is None:
            continue
        grouped[source].append(dict(match))
    return {int(source): items for source, items in grouped.items()}


def _build_swap_summary(
    trigger_numbers: List[int],
    final_excluded_numbers: List[int],
    swap_details: List[Dict[str, Any]],
) -> str:
    if not swap_details:
        return ""
    moves = ", ".join(
        f"{detail['replaced_number']}->{detail['replacement_number']}"
        for detail in swap_details
        if detail.get("replacement_number") is not None
    )
    final_label = ", ".join(str(number) for number in final_excluded_numbers) or "n/a"
    if len(trigger_numbers) == 1:
        prefix = f"numero {trigger_numbers[0]}"
    else:
        prefix = f"contexto {', '.join(str(number) for number in trigger_numbers)}"
    return (
        f"Aposta salva no {prefix}: trocas aplicadas {moves}. "
        f"Fora da jogada agora: {final_label}."
    ).strip()


def _find_safe_replacement(
    *,
    cold_ranking: List[int],
    trigger_numbers: List[int],
    blocked_numbers: set[int],
    replaced_number: int,
) -> Dict[str, Any]:
    del replaced_number
    for candidate in cold_ranking:
        if candidate in blocked_numbers:
            continue
        guard_details = _build_guard_details([candidate])
        if any(guard_details.get(int(trigger_number)) for trigger_number in trigger_numbers):
            continue
        return {
            "candidate": int(candidate),
            "blocked_by_distance": False,
            "blocked_candidate": None,
        }
    return {
        "candidate": None,
        "blocked_by_distance": False,
        "blocked_candidate": None,
    }


def _build_swap_details(
    *,
    trigger_numbers: List[int],
    original_excluded_numbers: List[int],
    cold_ranking: List[int],
    current_matches: List[Dict[str, Any]],
) -> Dict[str, Any]:
    matches_by_source = _group_matches_by_source(current_matches)
    if not matches_by_source:
        return {
            "final_excluded_numbers": list(original_excluded_numbers),
            "swap_details": [],
            "swap_applied": False,
            "swap_summary": "",
            "swap_blocked_by_distance": False,
            "swap_blocked_replaced_number": None,
            "swap_blocked_candidate": None,
        }

    final_excluded_numbers: List[int] = []
    swap_details: List[Dict[str, Any]] = []
    blocked_numbers = set(original_excluded_numbers)

    for base in original_excluded_numbers:
        base_matches = list(matches_by_source.get(int(base), []))
        if not base_matches:
            final_excluded_numbers.append(int(base))
            blocked_numbers.add(int(base))
            continue

        replacement_result = _find_safe_replacement(
            cold_ranking=cold_ranking,
            trigger_numbers=trigger_numbers,
            blocked_numbers=blocked_numbers.union(final_excluded_numbers),
            replaced_number=int(base),
        )
        replacement = replacement_result["candidate"]
        if replacement is None:
            final_excluded_numbers.append(int(base))
            continue

        match_trigger_numbers: List[int] = []
        for trigger_number in (
            _safe_int(match.get("trigger_number"))
            for match in base_matches
        ):
            if trigger_number is None or trigger_number in match_trigger_numbers:
                continue
            match_trigger_numbers.append(int(trigger_number))
        blocked_numbers.add(int(replacement))
        final_excluded_numbers.append(int(replacement))
        if len(base_matches) == 1:
            trigger_reason = _build_relation_description(base_matches[0])
        else:
            trigger_reason = ", ".join(
                (
                    f"{_build_relation_description(match)} no giro {match_trigger}"
                    if match_trigger is not None
                    else _build_relation_description(match)
                )
                for match in base_matches
                for match_trigger in [_safe_int(match.get("trigger_number"))]
            )
        swap_details.append(
            {
                "replaced_number": int(base),
                "replacement_number": int(replacement),
                "trigger_number": match_trigger_numbers[0] if match_trigger_numbers else None,
                "trigger_numbers": match_trigger_numbers,
                "trigger_matches": base_matches,
                "trigger_reason": trigger_reason,
            }
        )

    swap_applied = bool(swap_details) and len(swap_details) == len(matches_by_source)
    swap_summary = _build_swap_summary(trigger_numbers, final_excluded_numbers, swap_details) if swap_applied else ""
    return {
        "final_excluded_numbers": final_excluded_numbers,
        "swap_details": swap_details,
        "swap_applied": swap_applied,
        "swap_summary": swap_summary,
        "swap_blocked_by_distance": False,
        "swap_blocked_replaced_number": None,
        "swap_blocked_candidate": None,
    }


def _build_candidate_details(
    ordered_suggestion: List[int],
    excluded_numbers: List[int],
    frequency_map: Dict[int, int],
) -> Dict[str, Dict[str, Any]]:
    details: Dict[str, Dict[str, Any]] = {}
    ordered_set = set(ordered_suggestion)
    excluded_set = set(excluded_numbers)

    for number in range(37):
        reasons = [
            {
                "reason": "frequency_last_50",
                "weight": int(frequency_map.get(number, 0)),
            }
        ]
        if number in ordered_set:
            reasons.append({"reason": "included_protected_coverage", "weight": 1})
        if number in excluded_set:
            reasons.append({"reason": "excluded_cold_tail", "weight": -1})
        details[str(number)] = {
            "score": round(float(frequency_map.get(number, 0)), 4),
            "reasons": reasons,
        }

    return details


def build_protected_coverage_suggestion(
    *,
    history_arr: List[int],
    from_index: int,
    focus_number: int,
    base_list: List[int],
    candidate_list: List[int],
    protections: List[int],
    number_details: List[Dict[str, Any]],
    target_size: int,
    cold_count: int,
    recent_anchor_count: int = 3,
    protected_swap_enabled: bool = False,
) -> Dict[str, Any]:
    del base_list, candidate_list, protections, number_details, target_size, cold_count, recent_anchor_count

    history_slice = _history_window(history_arr, from_index, PROTECTED_HISTORY_WINDOW)
    frequency_map = _build_frequency_map(history_slice)
    trigger_numbers = _collect_trigger_numbers(history_arr, from_index, focus_number)

    cold_ranking = sorted(range(37), key=lambda number: (frequency_map[number], number))
    original_excluded_numbers = cold_ranking[:PROTECTED_EXCLUDED_COUNT]

    original_guard_details = _build_guard_details(original_excluded_numbers)
    original_matches = _collect_guard_matches(original_guard_details, trigger_numbers)

    final_excluded_numbers = list(original_excluded_numbers)
    protected_swap_details: List[Dict[str, Any]] = []
    protected_swap_applied = False
    protected_swap_summary = ""
    protected_swap_blocked_by_distance = False
    protected_swap_blocked_replaced_number = None
    protected_swap_blocked_candidate = None
    if protected_swap_enabled and original_matches:
        swap_result = _build_swap_details(
            trigger_numbers=trigger_numbers,
            original_excluded_numbers=original_excluded_numbers,
            cold_ranking=cold_ranking,
            current_matches=original_matches,
        )
        final_excluded_numbers = list(swap_result["final_excluded_numbers"])
        protected_swap_details = list(swap_result["swap_details"])
        protected_swap_applied = bool(swap_result["swap_applied"])
        protected_swap_summary = str(swap_result["swap_summary"] or "").strip()
        protected_swap_blocked_by_distance = bool(swap_result.get("swap_blocked_by_distance"))
        protected_swap_blocked_replaced_number = _safe_int(swap_result.get("swap_blocked_replaced_number"))
        protected_swap_blocked_candidate = _safe_int(swap_result.get("swap_blocked_candidate"))

    final_excluded_set = set(final_excluded_numbers)
    ordered_suggestion = sorted(
        [number for number in range(37) if number not in final_excluded_set],
        key=lambda number: (-frequency_map[number], number),
    )
    ordered_ranking = list(ordered_suggestion) + list(final_excluded_numbers)

    guard_details = _build_guard_details(final_excluded_numbers)
    guard_numbers = sorted(guard_details.keys())
    current_matches = _collect_guard_matches(guard_details, trigger_numbers)
    wait_recommended_spins = PROTECTED_WAIT_SPINS if current_matches else 0

    base_cold_rank = None
    if int(focus_number) in final_excluded_set:
        base_cold_rank = final_excluded_numbers.index(int(focus_number)) + 1

    excluded_tail_reasons = [
        {
            "number": int(number),
            "score": round(float(frequency_map.get(number, 0)), 4),
            "reasons": [
                {
                    "reason": "excluded_cold_tail",
                    "weight": int(frequency_map.get(number, 0)),
                }
            ],
        }
        for number in final_excluded_numbers
    ]

    wait_reason = _build_wait_reason(trigger_numbers, current_matches, final_excluded_numbers)
    return {
        "ordered_suggestion": ordered_suggestion,
        "ordered_ranking": ordered_ranking,
        "ranking_locked": True,
        "excluded_tail_numbers": final_excluded_numbers,
        "excluded_tail_reasons": excluded_tail_reasons,
        "candidate_details": _build_candidate_details(ordered_suggestion, final_excluded_numbers, frequency_map),
        "base_is_cold": int(focus_number) in final_excluded_set,
        "base_cold_rank": base_cold_rank,
        "cold_numbers_considered": list(final_excluded_numbers),
        "cold_wait_recommended_spins": wait_recommended_spins,
        "protected_excluded_numbers": list(final_excluded_numbers),
        "protected_original_excluded_numbers": list(original_excluded_numbers),
        "protected_guard_numbers": guard_numbers,
        "protected_guard_details": {str(number): details for number, details in guard_details.items()},
        "protected_wait_triggered": bool(current_matches),
        "protected_wait_matches": current_matches,
        "protected_wait_recommended_spins": wait_recommended_spins,
        "protected_wait_reason": wait_reason,
        "protected_trigger_numbers": trigger_numbers,
        "protected_reference_window": len(history_slice),
        "protected_frequency_map": {str(number): int(count) for number, count in frequency_map.items()},
        "protected_swap_enabled": bool(protected_swap_enabled),
        "protected_swap_applied": bool(protected_swap_applied),
        "protected_swap_details": protected_swap_details,
        "protected_swap_summary": protected_swap_summary,
        "protected_swap_blocked_by_distance": bool(protected_swap_blocked_by_distance),
        "protected_swap_blocked_replaced_number": protected_swap_blocked_replaced_number,
        "protected_swap_blocked_candidate": protected_swap_blocked_candidate,
    }
