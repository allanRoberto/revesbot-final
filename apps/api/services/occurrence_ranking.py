from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List


DEFAULT_HISTORY_LIMIT = 2000
DEFAULT_WINDOW_BEFORE = 5
DEFAULT_WINDOW_AFTER = 3
DEFAULT_RANKING_SIZE = 18
DEFAULT_ATTEMPTS_WINDOW = 10
DEFAULT_INVERT_CHECK_WINDOW = 0
MAX_HISTORY_LIMIT = 50_000
MAX_ATTEMPTS_WINDOW = 100
MAX_INVERT_CHECK_WINDOW = 100


def _coerce_history_value(raw: Any) -> int | None:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if 0 <= value <= 36:
        return value
    return None


def _clamp_int(raw: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def normalize_history_desc(history: Iterable[Any], history_limit: int = DEFAULT_HISTORY_LIMIT) -> List[int]:
    safe_limit = _clamp_int(history_limit, DEFAULT_HISTORY_LIMIT, 1, MAX_HISTORY_LIMIT)
    normalized: List[int] = []
    for raw in history:
        value = _coerce_history_value(raw)
        if value is None:
            continue
        normalized.append(value)
        if len(normalized) >= safe_limit:
            break
    return normalized


def _resolve_focus_number(history_desc: List[int], focus_number: Any, from_index: int) -> int | None:
    normalized_focus = _coerce_history_value(focus_number)
    if normalized_focus is not None:
        return normalized_focus
    if not history_desc:
        return None
    safe_from_index = _clamp_int(from_index, 0, 0, len(history_desc) - 1)
    return int(history_desc[safe_from_index])


def build_occurrence_ranking(
    history_desc: List[int],
    *,
    focus_number: Any = None,
    from_index: int = 0,
    history_limit: int = DEFAULT_HISTORY_LIMIT,
    window_before: int = DEFAULT_WINDOW_BEFORE,
    window_after: int = DEFAULT_WINDOW_AFTER,
    ranking_size: int = DEFAULT_RANKING_SIZE,
) -> Dict[str, Any]:
    source_arr = normalize_history_desc(history_desc, history_limit=history_limit)
    if not source_arr:
        return {
            "available": False,
            "source": "tooltip_occurrences_v1",
            "history_size": 0,
            "focus_number": None,
            "from_index": 0,
            "occurrence_count": 0,
            "occurrences": [],
            "window_before": _clamp_int(window_before, DEFAULT_WINDOW_BEFORE, 0, 100),
            "window_after": _clamp_int(window_after, DEFAULT_WINDOW_AFTER, 0, 100),
            "ranking_size": _clamp_int(ranking_size, DEFAULT_RANKING_SIZE, 1, 37),
            "pulled_total": 0,
            "pulled_counts": {},
            "top_pulled": [],
            "ranking": [],
            "ranking_details": [],
            "occurrence_windows": [],
            "explanation": "Historico insuficiente para calcular ocorrencias.",
        }

    safe_from_index = _clamp_int(from_index, 0, 0, len(source_arr) - 1)
    safe_window_before = _clamp_int(window_before, DEFAULT_WINDOW_BEFORE, 0, 100)
    safe_window_after = _clamp_int(window_after, DEFAULT_WINDOW_AFTER, 0, 100)
    safe_ranking_size = _clamp_int(ranking_size, DEFAULT_RANKING_SIZE, 1, 37)
    resolved_focus_number = _resolve_focus_number(source_arr, focus_number, safe_from_index)

    if resolved_focus_number is None:
        return {
            "available": False,
            "source": "tooltip_occurrences_v1",
            "history_size": len(source_arr),
            "focus_number": None,
            "from_index": safe_from_index,
            "occurrence_count": 0,
            "occurrences": [],
            "window_before": safe_window_before,
            "window_after": safe_window_after,
            "ranking_size": safe_ranking_size,
            "pulled_total": 0,
            "pulled_counts": {},
            "top_pulled": [],
            "ranking": [],
            "ranking_details": [],
            "occurrence_windows": [],
            "explanation": "Numero foco invalido para a analise de ocorrencias.",
        }

    occurrences: List[int] = []
    for idx in range(safe_from_index, len(source_arr)):
        if int(source_arr[idx]) == int(resolved_focus_number):
            occurrences.append(idx)

    pulled_numbers: List[int] = []
    occurrence_windows: List[Dict[str, Any]] = []
    for occurrence_index in occurrences:
        start = max(safe_from_index, occurrence_index - safe_window_before)
        end = min(len(source_arr) - 1, occurrence_index + safe_window_after)
        window_numbers: List[Dict[str, Any]] = []
        for pos in range(start, end + 1):
            if pos == occurrence_index:
                continue
            value = int(source_arr[pos])
            pulled_numbers.append(value)
            window_numbers.append(
                {
                    "history_index": pos,
                    "number": value,
                    "relative_index": pos - occurrence_index,
                }
            )
        occurrence_windows.append(
            {
                "occurrence_index": occurrence_index,
                "window_start": start,
                "window_end": end,
                "numbers": window_numbers,
            }
        )

    pulled_counter = Counter(int(number) for number in pulled_numbers)
    sorted_pulled = sorted(
        pulled_counter.items(),
        key=lambda item: (-int(item[1]), int(item[0])),
    )
    top_pulled = [
        {"number": int(number), "count": int(count)}
        for number, count in sorted_pulled[:safe_ranking_size]
    ]
    ranking = [int(item["number"]) for item in top_pulled]

    explanation = (
        f"Ranking de ocorrencias do tooltip com janela idx-{safe_window_before} / idx+{safe_window_after} "
        f"e top {safe_ranking_size} numeros."
    )

    return {
        "available": len(ranking) > 0,
        "source": "tooltip_occurrences_v1",
        "history_size": len(source_arr),
        "focus_number": int(resolved_focus_number),
        "from_index": safe_from_index,
        "occurrence_count": len(occurrences),
        "occurrences": occurrences,
        "window_before": safe_window_before,
        "window_after": safe_window_after,
        "ranking_size": safe_ranking_size,
        "pulled_total": len(pulled_numbers),
        "pulled_counts": {str(int(number)): int(count) for number, count in sorted_pulled},
        "top_pulled": top_pulled,
        "ranking": ranking,
        "ranking_details": list(top_pulled),
        "occurrence_windows": occurrence_windows,
        "explanation": explanation,
    }


def evaluate_occurrence_attempts(
    history_desc: List[int],
    *,
    from_index: int,
    ranking: Iterable[Any],
    attempts_window: int = DEFAULT_ATTEMPTS_WINDOW,
) -> Dict[str, Any]:
    normalized_history = [int(number) for number in history_desc if _coerce_history_value(number) is not None]
    if not normalized_history:
        return {
            "status": "unavailable",
            "attempts_window": _clamp_int(attempts_window, DEFAULT_ATTEMPTS_WINDOW, 1, MAX_ATTEMPTS_WINDOW),
            "available_attempts": 0,
            "remaining_attempts": 0,
            "hit_count": 0,
            "hit_attempts": [],
            "first_hit_attempt": None,
            "future_numbers": [],
            "attempts": [],
            "summary": "0/0 acertos",
        }

    safe_from_index = _clamp_int(from_index, 0, 0, len(normalized_history) - 1)
    safe_attempts_window = _clamp_int(
        attempts_window,
        DEFAULT_ATTEMPTS_WINDOW,
        1,
        MAX_ATTEMPTS_WINDOW,
    )
    ranking_list = [
        int(value)
        for value in ranking
        if _coerce_history_value(value) is not None
    ]
    ranking_positions = {
        int(number): index + 1
        for index, number in enumerate(ranking_list)
    }
    ranking_set = set(ranking_positions.keys())

    attempts: List[Dict[str, Any]] = []
    future_numbers: List[int] = []
    hit_attempts: List[int] = []
    hit_numbers: List[int] = []
    first_hit_attempt: int | None = None

    for attempt_number in range(1, safe_attempts_window + 1):
        target_index = safe_from_index - attempt_number
        if target_index < 0:
            break
        number = int(normalized_history[target_index])
        hit = number in ranking_set
        if hit:
            hit_attempts.append(attempt_number)
            hit_numbers.append(number)
            if first_hit_attempt is None:
                first_hit_attempt = attempt_number
        future_numbers.append(number)
        attempts.append(
            {
                "attempt": attempt_number,
                "history_index": target_index,
                "number": number,
                "hit": hit,
                "rank_position": ranking_positions.get(number),
            }
        )

    available_attempts = len(attempts)
    remaining_attempts = max(0, safe_attempts_window - available_attempts)
    hit_count = len(hit_attempts)
    status = "resolved" if remaining_attempts == 0 else "pending"
    summary = (
        f"{hit_count}/{safe_attempts_window} acertos"
        if status == "resolved"
        else f"{hit_count}/{available_attempts} acertos observados ({safe_attempts_window} alvo)"
    )

    return {
        "status": status,
        "attempts_window": safe_attempts_window,
        "available_attempts": available_attempts,
        "remaining_attempts": remaining_attempts,
        "hit_count": hit_count,
        "hit_attempts": hit_attempts,
        "hit_numbers": hit_numbers,
        "first_hit_attempt": first_hit_attempt,
        "future_numbers": future_numbers,
        "attempts": attempts,
        "summary": summary,
    }


def evaluate_inverted_occurrence_hits(
    history_desc: List[int],
    *,
    from_index: int,
    ranking: Iterable[Any],
    invert_check_window: int = DEFAULT_INVERT_CHECK_WINDOW,
) -> Dict[str, Any]:
    normalized_history = [int(number) for number in history_desc if _coerce_history_value(number) is not None]
    safe_invert_check_window = _clamp_int(
        invert_check_window,
        DEFAULT_INVERT_CHECK_WINDOW,
        0,
        MAX_INVERT_CHECK_WINDOW,
    )
    if not normalized_history:
        return {
            "enabled": safe_invert_check_window > 0,
            "invert_check_window": safe_invert_check_window,
            "available_attempts": 0,
            "remaining_attempts": safe_invert_check_window,
            "hit_count": 0,
            "hit_offsets": [],
            "hit_numbers": [],
            "first_hit_offset": None,
            "numbers_checked": [],
            "attempts": [],
            "cancelled": False,
            "summary": (
                "Verificacao invertida desativada."
                if safe_invert_check_window <= 0
                else f"0/{safe_invert_check_window} batidas invertidas observadas"
            ),
        }

    safe_from_index = _clamp_int(from_index, 0, 0, len(normalized_history) - 1)
    ranking_list = [
        int(value)
        for value in ranking
        if _coerce_history_value(value) is not None
    ]
    ranking_positions = {
        int(number): index + 1
        for index, number in enumerate(ranking_list)
    }
    ranking_set = set(ranking_positions.keys())

    attempts: List[Dict[str, Any]] = []
    numbers_checked: List[int] = []
    hit_offsets: List[int] = []
    hit_numbers: List[int] = []
    first_hit_offset: int | None = None

    for offset in range(1, safe_invert_check_window + 1):
        target_index = safe_from_index + offset
        if target_index >= len(normalized_history):
            break
        number = int(normalized_history[target_index])
        hit = number in ranking_set
        if hit:
            hit_offsets.append(offset)
            hit_numbers.append(number)
            if first_hit_offset is None:
                first_hit_offset = offset
        numbers_checked.append(number)
        attempts.append(
            {
                "attempt": offset,
                "history_index": target_index,
                "number": number,
                "hit": hit,
                "rank_position": ranking_positions.get(number),
            }
        )

    available_attempts = len(attempts)
    remaining_attempts = max(0, safe_invert_check_window - available_attempts)
    hit_count = len(hit_offsets)
    cancelled = hit_count > 0
    if safe_invert_check_window <= 0:
        summary = "Verificacao invertida desativada."
    elif cancelled:
        summary = (
            f"Batida invertida detectada: {hit_count}/{available_attempts} hit(s) "
            f"nos {safe_invert_check_window} numero(s) anteriores"
        )
    else:
        summary = f"0/{available_attempts} batidas invertidas observadas ({safe_invert_check_window} alvo)"

    return {
        "enabled": safe_invert_check_window > 0,
        "invert_check_window": safe_invert_check_window,
        "available_attempts": available_attempts,
        "remaining_attempts": remaining_attempts,
        "hit_count": hit_count,
        "hit_offsets": hit_offsets,
        "hit_numbers": hit_numbers,
        "first_hit_offset": first_hit_offset,
        "numbers_checked": numbers_checked,
        "attempts": attempts,
        "cancelled": cancelled,
        "summary": summary,
    }


def build_occurrence_snapshot(
    history_desc: List[int],
    *,
    focus_number: Any = None,
    from_index: int = 0,
    history_limit: int = DEFAULT_HISTORY_LIMIT,
    window_before: int = DEFAULT_WINDOW_BEFORE,
    window_after: int = DEFAULT_WINDOW_AFTER,
    ranking_size: int = DEFAULT_RANKING_SIZE,
    attempts_window: int = DEFAULT_ATTEMPTS_WINDOW,
    invert_check_window: int = DEFAULT_INVERT_CHECK_WINDOW,
) -> Dict[str, Any]:
    normalized_history = normalize_history_desc(history_desc, history_limit=history_limit)
    ranking_payload = build_occurrence_ranking(
        normalized_history,
        focus_number=focus_number,
        from_index=from_index,
        history_limit=history_limit,
        window_before=window_before,
        window_after=window_after,
        ranking_size=ranking_size,
    )
    safe_attempts_window = _clamp_int(
        attempts_window,
        DEFAULT_ATTEMPTS_WINDOW,
        1,
        MAX_ATTEMPTS_WINDOW,
    )
    safe_invert_check_window = _clamp_int(
        invert_check_window,
        DEFAULT_INVERT_CHECK_WINDOW,
        0,
        MAX_INVERT_CHECK_WINDOW,
    )
    inverted_evaluation = evaluate_inverted_occurrence_hits(
        normalized_history,
        from_index=ranking_payload.get("from_index", 0),
        ranking=ranking_payload.get("ranking", []),
        invert_check_window=safe_invert_check_window,
    )
    cancelled_inverted = bool(inverted_evaluation.get("cancelled"))
    if cancelled_inverted:
        evaluation = {
            "status": "cancelled_inverted",
            "attempts_window": safe_attempts_window,
            "available_attempts": 0,
            "remaining_attempts": safe_attempts_window,
            "hit_count": 0,
            "hit_attempts": [],
            "hit_numbers": [],
            "first_hit_attempt": None,
            "future_numbers": [],
            "attempts": [],
            "summary": (
                f"Aposta cancelada por batida invertida. {inverted_evaluation.get('summary') or ''}"
            ).strip(),
        }
    else:
        evaluation = evaluate_occurrence_attempts(
            normalized_history,
            from_index=ranking_payload.get("from_index", 0),
            ranking=ranking_payload.get("ranking", []),
            attempts_window=safe_attempts_window,
        )
    return {
        **ranking_payload,
        "invert_check_window": safe_invert_check_window,
        "counted": not cancelled_inverted,
        "cancelled_reason": "inverted_hit" if cancelled_inverted else None,
        "inverted_evaluation": inverted_evaluation,
        "evaluation": evaluation,
    }


def run_occurrence_replay(
    *,
    roulette_id: str,
    history_desc: List[int],
    history_limit: int = DEFAULT_HISTORY_LIMIT,
    entries_limit: int = 300,
    window_before: int = DEFAULT_WINDOW_BEFORE,
    window_after: int = DEFAULT_WINDOW_AFTER,
    ranking_size: int = DEFAULT_RANKING_SIZE,
    attempts_window: int = DEFAULT_ATTEMPTS_WINDOW,
    invert_check_window: int = DEFAULT_INVERT_CHECK_WINDOW,
    focus_number_filter: Any = None,
) -> Dict[str, Any]:
    source_arr = normalize_history_desc(history_desc, history_limit=history_limit)
    safe_entries_limit = _clamp_int(entries_limit, 300, 1, MAX_HISTORY_LIMIT)
    safe_attempts_window = _clamp_int(
        attempts_window,
        DEFAULT_ATTEMPTS_WINDOW,
        1,
        MAX_ATTEMPTS_WINDOW,
    )
    safe_invert_check_window = _clamp_int(
        invert_check_window,
        DEFAULT_INVERT_CHECK_WINDOW,
        0,
        MAX_INVERT_CHECK_WINDOW,
    )
    resolved_focus_filter = _coerce_history_value(focus_number_filter)

    if len(source_arr) <= safe_attempts_window:
        return {
            "available": False,
            "roulette_id": roulette_id,
            "history_size": len(source_arr),
            "entries_processed": 0,
            "entries_analyzed": 0,
            "eligible_entries": 0,
            "cancelled_inverted_events": 0,
            "error": "Historico insuficiente para replay da analise de ocorrencias.",
            "required_min": safe_attempts_window + 1,
            "config": {
                "history_limit": _clamp_int(history_limit, DEFAULT_HISTORY_LIMIT, 1, MAX_HISTORY_LIMIT),
                "entries_limit": safe_entries_limit,
                "window_before": _clamp_int(window_before, DEFAULT_WINDOW_BEFORE, 0, 100),
                "window_after": _clamp_int(window_after, DEFAULT_WINDOW_AFTER, 0, 100),
                "ranking_size": _clamp_int(ranking_size, DEFAULT_RANKING_SIZE, 1, 37),
                "attempts_window": safe_attempts_window,
                "invert_check_window": safe_invert_check_window,
                "focus_number_filter": resolved_focus_filter,
            },
        }

    eligible_indexes = list(range(safe_attempts_window, len(source_arr)))
    if resolved_focus_filter is not None:
        eligible_indexes = [
            index
            for index in eligible_indexes
            if int(source_arr[index]) == int(resolved_focus_filter)
        ]
    eligible_count = len(eligible_indexes)
    selected_indexes = eligible_indexes[:safe_entries_limit]

    events: List[Dict[str, Any]] = []
    entries_processed = 0
    cancelled_inverted_events = 0
    total_hits = 0
    total_attempts = 0
    events_with_hits = 0
    first_hit_distribution: Dict[str, int] = {}

    for anchor_index in selected_indexes:
        anchor_number = int(source_arr[anchor_index])
        snapshot = build_occurrence_snapshot(
            source_arr,
            focus_number=anchor_number,
            from_index=anchor_index,
            history_limit=len(source_arr),
            window_before=window_before,
            window_after=window_after,
            ranking_size=ranking_size,
            attempts_window=safe_attempts_window,
            invert_check_window=safe_invert_check_window,
        )
        evaluation = snapshot["evaluation"]
        counted = bool(snapshot.get("counted", True))
        hit_count = int(evaluation.get("hit_count", 0) or 0)
        entries_processed += 1
        first_hit_attempt = evaluation.get("first_hit_attempt")
        if counted:
            total_hits += hit_count
            total_attempts += safe_attempts_window
            if hit_count > 0:
                events_with_hits += 1
            if isinstance(first_hit_attempt, int):
                key = str(first_hit_attempt)
                first_hit_distribution[key] = first_hit_distribution.get(key, 0) + 1
        elif str(snapshot.get("cancelled_reason") or "") == "inverted_hit":
            cancelled_inverted_events += 1
        events.append(
            {
                "anchor_number": anchor_number,
                "from_index": int(anchor_index),
                "focus_number": int(snapshot.get("focus_number", anchor_number)),
                "occurrence_count": int(snapshot.get("occurrence_count", 0) or 0),
                "ranking": [int(number) for number in snapshot.get("ranking", [])],
                "ranking_details": list(snapshot.get("ranking_details", [])),
                "pulled_total": int(snapshot.get("pulled_total", 0) or 0),
                "evaluation": evaluation,
                "status": str(evaluation.get("status") or "resolved"),
                "summary": str(evaluation.get("summary") or ""),
                "hit_count": hit_count,
                "hit_attempts": list(evaluation.get("hit_attempts") or []),
                "first_hit_attempt": first_hit_attempt,
                "future_numbers": list(evaluation.get("future_numbers") or []),
                "attempts": list(evaluation.get("attempts") or []),
                "window_before": int(snapshot.get("window_before", 0) or 0),
                "window_after": int(snapshot.get("window_after", 0) or 0),
                "ranking_size": int(snapshot.get("ranking_size", 0) or 0),
                "attempts_window": int(evaluation.get("attempts_window", safe_attempts_window) or safe_attempts_window),
                "invert_check_window": int(snapshot.get("invert_check_window", safe_invert_check_window) or safe_invert_check_window),
                "history_size": int(snapshot.get("history_size", len(source_arr)) or len(source_arr)),
                "source": str(snapshot.get("source") or "tooltip_occurrences_v1"),
                "explanation": str(snapshot.get("explanation") or ""),
                "counted": counted,
                "cancelled_reason": snapshot.get("cancelled_reason"),
                "inverted_evaluation": dict(snapshot.get("inverted_evaluation") or {}),
            }
        )

    entries_analyzed = sum(1 for event in events if bool(event.get("counted", True)))
    aggregate_hit_rate = (total_hits / total_attempts) if total_attempts > 0 else 0.0
    event_hit_rate = (events_with_hits / entries_analyzed) if entries_analyzed > 0 else 0.0
    avg_hits_per_event = (total_hits / entries_analyzed) if entries_analyzed > 0 else 0.0

    return {
        "available": True,
        "roulette_id": roulette_id,
        "history_size": len(source_arr),
        "entries_processed": entries_processed,
        "entries_analyzed": entries_analyzed,
        "eligible_entries": eligible_count,
        "cancelled_inverted_events": cancelled_inverted_events,
        "events_with_hits": events_with_hits,
        "total_hits": total_hits,
        "total_attempts": total_attempts,
        "aggregate_hit_rate": round(aggregate_hit_rate, 6),
        "event_hit_rate": round(event_hit_rate, 6),
        "avg_hits_per_event": round(avg_hits_per_event, 6),
        "first_hit_distribution": first_hit_distribution,
        "events": events,
        "config": {
            "history_limit": _clamp_int(history_limit, DEFAULT_HISTORY_LIMIT, 1, MAX_HISTORY_LIMIT),
            "entries_limit": safe_entries_limit,
            "window_before": _clamp_int(window_before, DEFAULT_WINDOW_BEFORE, 0, 100),
            "window_after": _clamp_int(window_after, DEFAULT_WINDOW_AFTER, 0, 100),
            "ranking_size": _clamp_int(ranking_size, DEFAULT_RANKING_SIZE, 1, 37),
            "attempts_window": safe_attempts_window,
            "invert_check_window": safe_invert_check_window,
            "focus_number_filter": resolved_focus_filter,
        },
    }
