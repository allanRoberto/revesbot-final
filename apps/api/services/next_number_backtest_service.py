from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List

from api.core.db import history_coll
from api.services.next_number_ranking_service import (
    DEFAULT_ROULETTE_ID,
    NUMBER_MAX,
    NUMBER_MIN,
    get_latest_next_number_rankings,
)


DEFAULT_BACKTEST_LIMIT = 1000
DEFAULT_ATTEMPTS = 3
DEFAULT_BET_SIZE = 12
INVERTED_WINDOW = 3
INVERTED_ACTION_BET = "bet"
INVERTED_ACTION_CANCEL = "cancel"
INVERTED_ACTION_DELAY = "delay"
INVERTED_ACTIONS = {
    INVERTED_ACTION_BET,
    INVERTED_ACTION_CANCEL,
    INVERTED_ACTION_DELAY,
}
DEFAULT_INVERTED_ACTION = INVERTED_ACTION_BET
DEFAULT_INVERTED_DELAY_SPINS = 0
DEFAULT_HOT_NUMBERS_ONLY = False
DEFAULT_HOT_NUMBERS_COUNT = 12
DEFAULT_HOT_NUMBERS_WINDOW = 1000
DEFAULT_INCLUDE_HOT_COMPARISON = False
MAX_BACKTEST_LIMIT = 50_000
MAX_ATTEMPTS = 100
MAX_BET_SIZE = 37
MAX_INVERTED_DELAY_SPINS = 100
MAX_HOT_NUMBERS_COUNT = 37
MAX_HOT_NUMBERS_WINDOW = 50_000


def _clamp_int(raw: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _coerce_bool(raw: Any, default: bool = False) -> bool:
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "sim", "on"}:
        return True
    if value in {"0", "false", "no", "nao", "não", "off"}:
        return False
    return default


def _coerce_number(raw: Any) -> int | None:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if NUMBER_MIN <= value <= NUMBER_MAX:
        return value
    return None


def _safe_percentage(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round((int(numerator) / int(denominator)) * 100.0, 4)


def _normalize_inverted_action(raw: Any) -> str:
    action = str(raw or DEFAULT_INVERTED_ACTION).strip().lower()
    if action not in INVERTED_ACTIONS:
        valid_actions = ", ".join(sorted(INVERTED_ACTIONS))
        raise ValueError(f"Acao de inversao invalida: {action}. Use uma destas: {valid_actions}.")
    return action


def _normalize_inverted_rules(raw_rules: Dict[Any, Dict[str, Any]] | None) -> Dict[str, Dict[str, Any]]:
    rules = raw_rules or {}
    normalized: Dict[str, Dict[str, Any]] = {}

    for count in range(0, INVERTED_WINDOW + 1):
        raw_rule = rules.get(count) or rules.get(str(count)) or {}
        action = _normalize_inverted_action(raw_rule.get("action"))
        delay_spins = _clamp_int(
            raw_rule.get("delay_spins"),
            DEFAULT_INVERTED_DELAY_SPINS,
            0,
            MAX_INVERTED_DELAY_SPINS,
        )
        if action != INVERTED_ACTION_DELAY:
            delay_spins = 0

        normalized[str(count)] = {
            "action": action,
            "delay_spins": delay_spins,
        }

    return normalized


def _max_rule_delay(inverted_rules: Dict[str, Dict[str, Any]]) -> int:
    return max(
        (
            int(rule.get("delay_spins") or 0)
            for rule in inverted_rules.values()
            if rule.get("action") == INVERTED_ACTION_DELAY
        ),
        default=0,
    )


def _ranking_numbers_for_base(snapshot: Dict[str, Any], base_number: int, bet_size: int) -> List[int]:
    number_payload = (snapshot.get("numbers") or {}).get(str(base_number)) or {}
    ranking = number_payload.get("ranking") or []
    numbers: List[int] = []
    for item in ranking:
        value = _coerce_number((item or {}).get("number"))
        if value is None:
            continue
        numbers.append(value)
        if len(numbers) >= bet_size:
            break
    return numbers


def _hot_numbers_from_counts(counts: Dict[int, int], hot_numbers_count: int) -> List[Dict[str, Any]]:
    ordered = sorted(
        (
            {"number": number, "count": count}
            for number, count in counts.items()
            if int(count) > 0
        ),
        key=lambda item: (-int(item["count"]), int(item["number"])),
    )
    rows: List[Dict[str, Any]] = []
    for position, item in enumerate(ordered[:hot_numbers_count], start=1):
        rows.append(
            {
                "position": position,
                "number": int(item["number"]),
                "count": int(item["count"]),
            }
        )
    return rows


def _add_hot_count(counts: Dict[int, int], value: Any) -> None:
    number = _coerce_number(value)
    if number is not None:
        counts[int(number)] += 1


def _remove_hot_count(counts: Dict[int, int], value: Any) -> None:
    number = _coerce_number(value)
    if number is None:
        return
    current = int(counts.get(int(number), 0))
    if current <= 1:
        counts.pop(int(number), None)
    else:
        counts[int(number)] = current - 1


def _comparison_summary(result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "hot_numbers_only": bool((result.get("config") or {}).get("hot_numbers_only")),
        "hot_numbers_count": int((result.get("config") or {}).get("hot_numbers_count") or 0),
        "hot_numbers_window": int((result.get("config") or {}).get("hot_numbers_window") or 0),
        "signals_total": int(result.get("signals_total") or 0),
        "entries_total": int(result.get("entries_total") or 0),
        "entries_canceled": int(result.get("entries_canceled") or 0),
        "entries_canceled_by_hot_filter": int(result.get("entries_canceled_by_hot_filter") or 0),
        "entries_hit": int(result.get("entries_hit") or 0),
        "entries_missed": int(result.get("entries_missed") or 0),
        "hit_rate": float(result.get("hit_rate") or 0.0),
    }


def _build_attempt_stats(total_entries: int, hits_by_attempt: Dict[int, int], attempts: int) -> List[Dict[str, Any]]:
    cumulative = 0
    rows: List[Dict[str, Any]] = []
    for attempt in range(1, attempts + 1):
        hits = int(hits_by_attempt.get(attempt, 0))
        cumulative += hits
        rows.append(
            {
                "attempt": attempt,
                "hits": hits,
                "hit_rate": _safe_percentage(hits, total_entries),
                "cumulative_hits": cumulative,
                "cumulative_hit_rate": _safe_percentage(cumulative, total_entries),
            }
        )
    return rows


def _build_group_stats(entries: Iterable[Dict[str, Any]], attempts: int) -> Dict[str, Any]:
    entry_list = list(entries)
    executed_entries = [item for item in entry_list if item.get("executed")]
    total_signals = len(entry_list)
    total_entries = len(executed_entries)
    hits = sum(1 for item in executed_entries if item.get("hit"))
    hits_by_attempt: Dict[int, int] = defaultdict(int)
    for item in executed_entries:
        attempt = item.get("hit_attempt")
        if attempt is not None:
            hits_by_attempt[int(attempt)] += 1
    return {
        "signals": total_signals,
        "entries": total_entries,
        "canceled": total_signals - total_entries,
        "hits": hits,
        "misses": total_entries - hits,
        "hit_rate": _safe_percentage(hits, total_entries),
        "attempts": _build_attempt_stats(total_entries, hits_by_attempt, attempts),
    }


def run_next_number_backtest_from_history(
    *,
    snapshot: Dict[str, Any],
    history_docs_chrono: List[Dict[str, Any]],
    limit: int = DEFAULT_BACKTEST_LIMIT,
    attempts: int = DEFAULT_ATTEMPTS,
    bet_size: int = DEFAULT_BET_SIZE,
    inverted_rules: Dict[Any, Dict[str, Any]] | None = None,
    hot_numbers_only: Any = DEFAULT_HOT_NUMBERS_ONLY,
    hot_numbers_count: int = DEFAULT_HOT_NUMBERS_COUNT,
    hot_numbers_window: int = DEFAULT_HOT_NUMBERS_WINDOW,
    include_hot_comparison: Any = DEFAULT_INCLUDE_HOT_COMPARISON,
) -> Dict[str, Any]:
    safe_limit = _clamp_int(limit, DEFAULT_BACKTEST_LIMIT, 1, MAX_BACKTEST_LIMIT)
    safe_attempts = _clamp_int(attempts, DEFAULT_ATTEMPTS, 1, MAX_ATTEMPTS)
    safe_bet_size = _clamp_int(bet_size, DEFAULT_BET_SIZE, 1, MAX_BET_SIZE)
    safe_inverted_rules = _normalize_inverted_rules(inverted_rules)
    safe_max_rule_delay = _max_rule_delay(safe_inverted_rules)
    safe_hot_numbers_only = _coerce_bool(hot_numbers_only, DEFAULT_HOT_NUMBERS_ONLY)
    safe_hot_numbers_count = _clamp_int(
        hot_numbers_count,
        DEFAULT_HOT_NUMBERS_COUNT,
        1,
        MAX_HOT_NUMBERS_COUNT,
    )
    safe_hot_numbers_window = _clamp_int(
        hot_numbers_window,
        DEFAULT_HOT_NUMBERS_WINDOW,
        1,
        MAX_HOT_NUMBERS_WINDOW,
    )
    safe_include_hot_comparison = _coerce_bool(
        include_hot_comparison,
        DEFAULT_INCLUDE_HOT_COMPARISON,
    )
    track_hot_numbers = safe_hot_numbers_only or safe_include_hot_comparison

    docs = [
        doc
        for doc in history_docs_chrono
        if _coerce_number((doc or {}).get("value")) is not None
    ]
    max_anchor_index = len(docs) - safe_attempts - safe_max_rule_delay - 1
    if max_anchor_index < INVERTED_WINDOW:
        return {
            "available": False,
            "reason": "Historico insuficiente para simular com os parametros informados.",
            "config": {
                "limit": safe_limit,
                "attempts": safe_attempts,
                "bet_size": safe_bet_size,
                "inverted_window": INVERTED_WINDOW,
                "inverted_rules": safe_inverted_rules,
                "hot_numbers_only": safe_hot_numbers_only,
                "hot_numbers_count": safe_hot_numbers_count,
                "hot_numbers_window": safe_hot_numbers_window,
                "include_hot_comparison": safe_include_hot_comparison,
            },
            "signals_total": 0,
            "entries_total": 0,
            "entries": [],
        }

    start_index = max(INVERTED_WINDOW, max_anchor_index - safe_limit + 1)
    candidate_indexes = list(range(start_index, max_anchor_index + 1))
    entries: List[Dict[str, Any]] = []
    hits_by_attempt: Dict[int, int] = defaultdict(int)
    attempts_needed_for_all = 0
    unresolved_for_all = 0
    full_hit_resolved_count = 0
    canceled_by_rule_count = 0
    canceled_during_delay_count = 0
    canceled_by_hot_filter_count = 0
    delayed_signals_count = 0
    delayed_entries_count = 0
    immediate_entries_count = 0
    hot_counts: Dict[int, int] = defaultdict(int)
    hot_window_start_index = max(0, start_index - safe_hot_numbers_window)
    for previous_doc in docs[hot_window_start_index:start_index]:
        _add_hot_count(hot_counts, previous_doc.get("value"))

    for index in candidate_indexes:
        doc = docs[index]
        base_number = int(doc["value"])
        bet_numbers = _ranking_numbers_for_base(snapshot, base_number, safe_bet_size)
        bet_set = set(bet_numbers)
        previous_numbers = [
            int(prev_doc["value"])
            for prev_doc in docs[index - INVERTED_WINDOW:index]
            if _coerce_number(prev_doc.get("value")) is not None
        ]
        inverted_numbers = [number for number in previous_numbers if number in bet_set]
        inverted_match_count = len(inverted_numbers)
        inverted_rule = safe_inverted_rules[str(inverted_match_count)]
        inverted_action = str(inverted_rule["action"])
        inverted_delay_spins = int(inverted_rule.get("delay_spins") or 0)
        hot_ranking = (
            _hot_numbers_from_counts(hot_counts, safe_hot_numbers_count)
            if track_hot_numbers
            else []
        )
        hot_number_rank = None
        hot_number_count = None
        if track_hot_numbers:
            for hot_item in hot_ranking:
                if int(hot_item["number"]) == base_number:
                    hot_number_rank = int(hot_item["position"])
                    hot_number_count = int(hot_item["count"])
                    break
        is_hot_number = hot_number_rank is not None if track_hot_numbers else None

        wait_numbers: List[int] = []
        wait_cancel_number = None
        wait_cancel_spin = None
        entry_start_index = index
        entry_status = "executed"
        executed = True
        was_delayed = False

        if safe_hot_numbers_only and not is_hot_number:
            canceled_by_hot_filter_count += 1
            entry_status = "canceled_by_hot_filter"
            executed = False
        elif inverted_action == INVERTED_ACTION_CANCEL:
            canceled_by_rule_count += 1
            entry_status = "canceled_by_rule"
            executed = False
        elif inverted_action == INVERTED_ACTION_DELAY:
            was_delayed = inverted_delay_spins > 0
            if was_delayed:
                delayed_signals_count += 1
            wait_docs = docs[index + 1:index + 1 + inverted_delay_spins]
            wait_numbers = [
                int(wait_doc["value"])
                for wait_doc in wait_docs
                if _coerce_number(wait_doc.get("value")) is not None
            ]
            for wait_spin, wait_number in enumerate(wait_numbers, start=1):
                if wait_number in bet_set:
                    wait_cancel_number = wait_number
                    wait_cancel_spin = wait_spin
                    break
            if wait_cancel_number is not None:
                canceled_during_delay_count += 1
                entry_status = "canceled_during_delay"
                executed = False
            else:
                entry_start_index = index + inverted_delay_spins
                if was_delayed:
                    delayed_entries_count += 1

        if executed and not was_delayed:
            immediate_entries_count += 1

        future_numbers: List[int] = []
        hit_attempt = None
        hit_number = None

        full_hit_attempt = None
        full_hit_number = None

        if executed:
            future_numbers = [
                int(future_doc["value"])
                for future_doc in docs[entry_start_index + 1:entry_start_index + 1 + safe_attempts]
                if _coerce_number(future_doc.get("value")) is not None
            ]
            for attempt_number, future_number in enumerate(future_numbers, start=1):
                if future_number in bet_set:
                    hit_attempt = attempt_number
                    hit_number = future_number
                    hits_by_attempt[attempt_number] += 1
                    break

            for attempt_number, future_doc in enumerate(docs[entry_start_index + 1:], start=1):
                future_number = _coerce_number(future_doc.get("value"))
                if future_number is not None and future_number in bet_set:
                    full_hit_attempt = attempt_number
                    full_hit_number = future_number
                    break
            if full_hit_attempt is None:
                unresolved_for_all += 1
            else:
                full_hit_resolved_count += 1
                attempts_needed_for_all = max(attempts_needed_for_all, int(full_hit_attempt))

        entries.append(
            {
                "history_index": index,
                "entry_start_index": entry_start_index if executed else None,
                "history_id": str(doc.get("_id")) if doc.get("_id") is not None else None,
                "timestamp_utc": doc.get("timestamp"),
                "base_number": base_number,
                "bet_numbers": bet_numbers,
                "previous_numbers": previous_numbers,
                "inverted_match_count": inverted_match_count,
                "inverted_match_numbers": inverted_numbers,
                "has_inverted_paid_bet": len(inverted_numbers) > 0,
                "hot_numbers_only": safe_hot_numbers_only,
                "hot_numbers_count": safe_hot_numbers_count,
                "hot_numbers_window": safe_hot_numbers_window,
                "hot_numbers": hot_ranking,
                "is_hot_number": is_hot_number,
                "hot_number_rank": hot_number_rank,
                "hot_number_count": hot_number_count,
                "inverted_rule_action": inverted_action,
                "inverted_rule_delay_spins": inverted_delay_spins,
                "wait_numbers": wait_numbers,
                "wait_cancel_number": wait_cancel_number,
                "wait_cancel_spin": wait_cancel_spin,
                "entry_status": entry_status,
                "executed": executed,
                "was_delayed": was_delayed and executed,
                "future_numbers": future_numbers,
                "hit": executed and hit_attempt is not None,
                "hit_attempt": hit_attempt,
                "hit_number": hit_number,
                "full_hit_attempt": full_hit_attempt,
                "full_hit_number": full_hit_number,
            }
        )
        _add_hot_count(hot_counts, base_number)
        stale_hot_index = index - safe_hot_numbers_window
        if stale_hot_index >= 0:
            _remove_hot_count(hot_counts, docs[stale_hot_index].get("value"))

    signals_total = len(entries)
    executed_entries = [entry for entry in entries if entry["executed"]]
    total_entries = len(executed_entries)
    total_hits = sum(1 for entry in executed_entries if entry["hit"])
    misses = total_entries - total_hits
    canceled_total = (
        canceled_by_hot_filter_count
        + canceled_by_rule_count
        + canceled_during_delay_count
    )

    inverted_entries = [entry for entry in entries if entry["has_inverted_paid_bet"]]
    non_inverted_entries = [entry for entry in entries if not entry["has_inverted_paid_bet"]]
    inverted_distribution = {}
    for count in range(0, INVERTED_WINDOW + 1):
        group = [entry for entry in entries if int(entry["inverted_match_count"]) == count]
        inverted_distribution[str(count)] = _build_group_stats(group, safe_attempts)

    result = {
        "available": True,
        "source": "next_number_rankings_current_snapshot",
        "roulette_id": snapshot.get("roulette_id") or DEFAULT_ROULETTE_ID,
        "snapshot_updated_at_utc": snapshot.get("updated_at_utc"),
        "snapshot_history_count": int(snapshot.get("history_count") or 0),
        "config": {
            "limit": safe_limit,
            "attempts": safe_attempts,
            "bet_size": safe_bet_size,
            "inverted_window": INVERTED_WINDOW,
            "inverted_rules": safe_inverted_rules,
            "hot_numbers_only": safe_hot_numbers_only,
            "hot_numbers_count": safe_hot_numbers_count,
            "hot_numbers_window": safe_hot_numbers_window,
            "include_hot_comparison": safe_include_hot_comparison,
        },
        "history_loaded": len(docs),
        "signals_total": signals_total,
        "entries_total": total_entries,
        "entries_hit": total_hits,
        "entries_missed": misses,
        "entries_immediate": immediate_entries_count,
        "entries_delayed": delayed_entries_count,
        "entries_canceled": canceled_total,
        "entries_canceled_by_hot_filter": canceled_by_hot_filter_count,
        "entries_canceled_by_rule": canceled_by_rule_count,
        "entries_canceled_during_delay": canceled_during_delay_count,
        "signals_delayed": delayed_signals_count,
        "hit_rate": _safe_percentage(total_hits, total_entries),
        "attempts": _build_attempt_stats(total_entries, hits_by_attempt, safe_attempts),
        "attempts_needed_for_all": attempts_needed_for_all if unresolved_for_all == 0 else None,
        "attempts_needed_for_resolved": attempts_needed_for_all,
        "full_hit_resolved_count": full_hit_resolved_count,
        "unresolved_for_all_count": unresolved_for_all,
        "inverted": _build_group_stats(inverted_entries, safe_attempts),
        "without_inverted": _build_group_stats(non_inverted_entries, safe_attempts),
        "inverted_match_distribution": inverted_distribution,
        "entries_preview": list(reversed(entries[-100:])),
        "entries_preview_count": min(100, len(entries)),
        "has_more_entries": len(entries) > 100,
    }

    if safe_include_hot_comparison:
        if safe_hot_numbers_only:
            with_hot_result = result
            without_hot_result = run_next_number_backtest_from_history(
                snapshot=snapshot,
                history_docs_chrono=docs,
                limit=safe_limit,
                attempts=safe_attempts,
                bet_size=safe_bet_size,
                inverted_rules=safe_inverted_rules,
                hot_numbers_only=False,
                hot_numbers_count=safe_hot_numbers_count,
                hot_numbers_window=safe_hot_numbers_window,
                include_hot_comparison=False,
            )
        else:
            without_hot_result = result
            with_hot_result = run_next_number_backtest_from_history(
                snapshot=snapshot,
                history_docs_chrono=docs,
                limit=safe_limit,
                attempts=safe_attempts,
                bet_size=safe_bet_size,
                inverted_rules=safe_inverted_rules,
                hot_numbers_only=True,
                hot_numbers_count=safe_hot_numbers_count,
                hot_numbers_window=safe_hot_numbers_window,
                include_hot_comparison=False,
            )

        without_summary = _comparison_summary(without_hot_result)
        with_summary = _comparison_summary(with_hot_result)
        result["hot_comparison"] = {
            "without_hot_filter": without_summary,
            "with_hot_filter": with_summary,
            "hit_rate_delta": round(
                float(with_summary["hit_rate"]) - float(without_summary["hit_rate"]),
                4,
            ),
            "entries_delta": int(with_summary["entries_total"]) - int(without_summary["entries_total"]),
        }

    return result


async def run_next_number_backtest(
    roulette_id: str = DEFAULT_ROULETTE_ID,
    *,
    limit: int = DEFAULT_BACKTEST_LIMIT,
    attempts: int = DEFAULT_ATTEMPTS,
    bet_size: int = DEFAULT_BET_SIZE,
    inverted_rules: Dict[Any, Dict[str, Any]] | None = None,
    hot_numbers_only: Any = DEFAULT_HOT_NUMBERS_ONLY,
    hot_numbers_count: int = DEFAULT_HOT_NUMBERS_COUNT,
    hot_numbers_window: int = DEFAULT_HOT_NUMBERS_WINDOW,
    include_hot_comparison: Any = DEFAULT_INCLUDE_HOT_COMPARISON,
) -> Dict[str, Any]:
    safe_limit = _clamp_int(limit, DEFAULT_BACKTEST_LIMIT, 1, MAX_BACKTEST_LIMIT)
    safe_attempts = _clamp_int(attempts, DEFAULT_ATTEMPTS, 1, MAX_ATTEMPTS)
    safe_bet_size = _clamp_int(bet_size, DEFAULT_BET_SIZE, 1, MAX_BET_SIZE)
    safe_inverted_rules = _normalize_inverted_rules(inverted_rules)
    safe_max_rule_delay = _max_rule_delay(safe_inverted_rules)
    safe_hot_numbers_only = _coerce_bool(hot_numbers_only, DEFAULT_HOT_NUMBERS_ONLY)
    safe_hot_numbers_count = _clamp_int(
        hot_numbers_count,
        DEFAULT_HOT_NUMBERS_COUNT,
        1,
        MAX_HOT_NUMBERS_COUNT,
    )
    safe_hot_numbers_window = _clamp_int(
        hot_numbers_window,
        DEFAULT_HOT_NUMBERS_WINDOW,
        1,
        MAX_HOT_NUMBERS_WINDOW,
    )
    safe_include_hot_comparison = _coerce_bool(
        include_hot_comparison,
        DEFAULT_INCLUDE_HOT_COMPARISON,
    )
    safe_roulette_id = str(roulette_id or "").strip() or DEFAULT_ROULETTE_ID

    snapshot = await get_latest_next_number_rankings(safe_roulette_id)
    extra_history = (
        safe_hot_numbers_window
        if safe_hot_numbers_only or safe_include_hot_comparison
        else INVERTED_WINDOW
    )
    fetch_limit = safe_limit + safe_attempts + safe_max_rule_delay + extra_history
    cursor = (
        history_coll
        .find(
            {"roulette_id": safe_roulette_id},
            {"roulette_id": 1, "value": 1, "timestamp": 1},
        )
        .sort([("timestamp", -1), ("_id", -1)])
        .limit(fetch_limit)
    )
    docs_desc = await cursor.to_list(length=fetch_limit)
    docs_chrono = list(reversed(docs_desc))
    return run_next_number_backtest_from_history(
        snapshot=snapshot,
        history_docs_chrono=docs_chrono,
        limit=safe_limit,
        attempts=safe_attempts,
        bet_size=safe_bet_size,
        inverted_rules=safe_inverted_rules,
        hot_numbers_only=safe_hot_numbers_only,
        hot_numbers_count=safe_hot_numbers_count,
        hot_numbers_window=safe_hot_numbers_window,
        include_hot_comparison=safe_include_hot_comparison,
    )
