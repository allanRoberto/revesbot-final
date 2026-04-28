from __future__ import annotations

from typing import Any, Dict, List

from api.services.occurrence_ranking import (
    DEFAULT_HISTORY_LIMIT as DEFAULT_OCCURRENCE_HISTORY_LIMIT,
    DEFAULT_INVERT_CHECK_WINDOW as DEFAULT_OCCURRENCE_INVERT_CHECK_WINDOW,
    DEFAULT_RANKING_SIZE as DEFAULT_OCCURRENCE_RANKING_SIZE,
    DEFAULT_WINDOW_AFTER as DEFAULT_OCCURRENCE_WINDOW_AFTER,
    DEFAULT_WINDOW_BEFORE as DEFAULT_OCCURRENCE_WINDOW_BEFORE,
    MAX_HISTORY_LIMIT as MAX_OCCURRENCE_HISTORY_LIMIT,
    MAX_INVERT_CHECK_WINDOW as MAX_OCCURRENCE_INVERT_CHECK_WINDOW,
    build_occurrence_snapshot,
    normalize_history_desc,
)


DEFAULT_OCCURRENCE_PATTERN_WEIGHT = 0.75
DEFAULT_OCCURRENCE_FUSION_WEIGHT = 0.25
DEFAULT_OCCURRENCE_OVERLAP_BONUS = 0.05
DEFAULT_OCCURRENCE_TAIL_REPLACE_LIMIT = 0
MAX_OCCURRENCE_TAIL_REPLACE_LIMIT = 10


def _safe_int(raw: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _safe_float(raw: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _normalize_weights(pattern_weight: float, occurrence_weight: float) -> tuple[float, float]:
    safe_pattern = max(0.0, float(pattern_weight))
    safe_occurrence = max(0.0, float(occurrence_weight))
    total = safe_pattern + safe_occurrence
    if total <= 0:
        return (DEFAULT_OCCURRENCE_PATTERN_WEIGHT, DEFAULT_OCCURRENCE_FUSION_WEIGHT)
    return (safe_pattern / total, safe_occurrence / total)


def _build_default_fusion_meta(
    *,
    enabled: bool,
    focus_number: int | None,
    from_index: int,
    history_limit: int,
    window_before: int,
    window_after: int,
    ranking_size: int,
    invert_check_window: int,
    pattern_weight: float,
    occurrence_weight: float,
    overlap_bonus: float,
    tail_replace_limit: int,
    base_list: List[int],
) -> Dict[str, Any]:
    return {
        "enabled": enabled,
        "applied": False,
        "mode": "rerank",
        "focus_number": focus_number,
        "from_index": from_index,
        "history_limit": history_limit,
        "window_before": window_before,
        "window_after": window_after,
        "ranking_size": ranking_size,
        "invert_check_window": invert_check_window,
        "pattern_weight": round(pattern_weight, 6),
        "occurrence_weight": round(occurrence_weight, 6),
        "overlap_bonus": round(overlap_bonus, 6),
        "tail_replace_limit": tail_replace_limit,
        "tail_replace_applied": False,
        "tail_replacements": [],
        "occurrence_only_numbers_injected": [],
        "base_list": list(base_list),
        "occurrence_available": False,
        "occurrence_ranking": [],
        "occurrence_ranking_details": [],
        "occurrence_overlap_count": 0,
        "occurrence_overlap_numbers": [],
        "occurrence_inverted_detected": False,
        "occurrence_invert_hit_count": 0,
        "occurrence_invert_hit_offsets": [],
        "top_occurrence_count": 0,
        "reason": "Fusao por ocorrencias indisponivel para este contexto.",
    }


def apply_occurrence_rerank_to_simple_suggestion(
    *,
    simple_payload: Dict[str, Any],
    history: List[int],
    focus_number: int | None,
    from_index: int,
    enabled: bool = True,
    history_limit: int = DEFAULT_OCCURRENCE_HISTORY_LIMIT,
    window_before: int = DEFAULT_OCCURRENCE_WINDOW_BEFORE,
    window_after: int = DEFAULT_OCCURRENCE_WINDOW_AFTER,
    ranking_size: int = DEFAULT_OCCURRENCE_RANKING_SIZE,
    invert_check_window: int = DEFAULT_OCCURRENCE_INVERT_CHECK_WINDOW,
    pattern_weight: float = DEFAULT_OCCURRENCE_PATTERN_WEIGHT,
    occurrence_weight: float = DEFAULT_OCCURRENCE_FUSION_WEIGHT,
    overlap_bonus: float = DEFAULT_OCCURRENCE_OVERLAP_BONUS,
    tail_replace_limit: int = DEFAULT_OCCURRENCE_TAIL_REPLACE_LIMIT,
) -> Dict[str, Any]:
    payload = dict(simple_payload or {})
    base_list = [int(number) for number in (payload.get("list") or []) if 0 <= int(number) <= 36]
    safe_from_index = max(0, int(from_index))
    safe_history_limit = _safe_int(
        max(int(history_limit or DEFAULT_OCCURRENCE_HISTORY_LIMIT), safe_from_index + 1),
        DEFAULT_OCCURRENCE_HISTORY_LIMIT,
        1,
        MAX_OCCURRENCE_HISTORY_LIMIT,
    )
    safe_window_before = _safe_int(window_before, DEFAULT_OCCURRENCE_WINDOW_BEFORE, 0, 100)
    safe_window_after = _safe_int(window_after, DEFAULT_OCCURRENCE_WINDOW_AFTER, 0, 100)
    safe_ranking_size = _safe_int(ranking_size, DEFAULT_OCCURRENCE_RANKING_SIZE, 1, 37)
    safe_invert_check_window = _safe_int(
        invert_check_window,
        DEFAULT_OCCURRENCE_INVERT_CHECK_WINDOW,
        0,
        MAX_OCCURRENCE_INVERT_CHECK_WINDOW,
    )
    normalized_pattern_weight, normalized_occurrence_weight = _normalize_weights(
        _safe_float(pattern_weight, DEFAULT_OCCURRENCE_PATTERN_WEIGHT, 0.0, 1.0),
        _safe_float(occurrence_weight, DEFAULT_OCCURRENCE_FUSION_WEIGHT, 0.0, 1.0),
    )
    safe_overlap_bonus = _safe_float(overlap_bonus, DEFAULT_OCCURRENCE_OVERLAP_BONUS, 0.0, 0.5)
    safe_tail_replace_limit = _safe_int(
        tail_replace_limit,
        DEFAULT_OCCURRENCE_TAIL_REPLACE_LIMIT,
        0,
        MAX_OCCURRENCE_TAIL_REPLACE_LIMIT,
    )

    fusion_meta = _build_default_fusion_meta(
        enabled=bool(enabled),
        focus_number=focus_number,
        from_index=safe_from_index,
        history_limit=safe_history_limit,
        window_before=safe_window_before,
        window_after=safe_window_after,
        ranking_size=safe_ranking_size,
        invert_check_window=safe_invert_check_window,
        pattern_weight=normalized_pattern_weight,
        occurrence_weight=normalized_occurrence_weight,
        overlap_bonus=safe_overlap_bonus,
        tail_replace_limit=safe_tail_replace_limit,
        base_list=base_list,
    )

    payload["pre_fusion_list"] = list(base_list)
    payload["occurrence_fusion"] = fusion_meta
    payload["occurrence_ranking"] = []
    payload["occurrence_ranking_details"] = []
    payload["occurrence_overlap_count"] = 0
    payload["occurrence_overlap_numbers"] = []
    payload["occurrence_inverted_detected"] = False
    payload["occurrence_invert_hit_count"] = 0
    payload["occurrence_invert_hit_offsets"] = []
    payload["occurrence_tail_replace_limit"] = safe_tail_replace_limit
    payload["occurrence_tail_replace_applied"] = False
    payload["occurrence_tail_replacements"] = []
    payload["occurrence_only_numbers_injected"] = []

    if not enabled:
        fusion_meta["reason"] = "Fusao por ocorrencias desativada."
        return payload

    if not payload.get("available") or not base_list:
        fusion_meta["reason"] = "Sugestao simples indisponivel para rerank por ocorrencias."
        return payload

    normalized_history = normalize_history_desc(history, history_limit=safe_history_limit)
    if len(normalized_history) <= safe_from_index:
        fusion_meta["reason"] = "Historico insuficiente para aplicar a fusao por ocorrencias."
        return payload

    occurrence_snapshot = build_occurrence_snapshot(
        normalized_history,
        focus_number=focus_number,
        from_index=safe_from_index,
        history_limit=safe_history_limit,
        window_before=safe_window_before,
        window_after=safe_window_after,
        ranking_size=safe_ranking_size,
        attempts_window=1,
        invert_check_window=safe_invert_check_window,
    )
    if not occurrence_snapshot.get("available"):
        fusion_meta["reason"] = str(occurrence_snapshot.get("explanation") or fusion_meta["reason"])
        return payload

    occurrence_ranking_details = list(occurrence_snapshot.get("ranking_details") or [])
    occurrence_count_map = {
        int(item.get("number")): int(item.get("count", 0) or 0)
        for item in occurrence_ranking_details
        if isinstance(item, dict) and 0 <= int(item.get("number", -1)) <= 36
    }
    top_occurrence_count = max(occurrence_count_map.values()) if occurrence_count_map else 0

    number_details = list(payload.get("number_details") or [])
    selected_number_details = list(payload.get("selected_number_details") or [])
    details_map: Dict[int, Dict[str, Any]] = {}
    for item in number_details + selected_number_details:
        if not isinstance(item, dict):
            continue
        try:
            number = int(item.get("number"))
        except (TypeError, ValueError):
            continue
        if not (0 <= number <= 36):
            continue
        details_map[number] = dict(item)

    weighted_values = [
        float(item.get("weighted_support_score", 0.0) or 0.0)
        for item in number_details
        if isinstance(item, dict)
    ]
    support_values = [
        int(item.get("support_score", 0) or 0)
        for item in number_details
        if isinstance(item, dict)
    ]
    top_weighted_support_score = max(weighted_values) if weighted_values else 0.0
    top_support_score = max(support_values) if support_values else 0

    reranked_details: List[Dict[str, Any]] = []
    overlap_numbers: List[int] = []
    for number in base_list:
        detail = dict(details_map.get(number) or {
            "number": int(number),
            "support_score": 0,
            "support_count": 0,
            "weighted_support_score": 0.0,
            "supporting_patterns": [],
        })
        weighted_support_score = float(detail.get("weighted_support_score", 0.0) or 0.0)
        support_score = int(detail.get("support_score", detail.get("support_count", 0)) or 0)
        if top_weighted_support_score > 0:
            pattern_norm = weighted_support_score / top_weighted_support_score
        elif top_support_score > 0:
            pattern_norm = float(support_score) / float(top_support_score)
        else:
            pattern_norm = 0.0
        occurrence_count = int(occurrence_count_map.get(number, 0) or 0)
        occurrence_norm = (
            float(occurrence_count) / float(top_occurrence_count)
            if top_occurrence_count > 0
            else 0.0
        )
        overlap = occurrence_count > 0
        if overlap:
            overlap_numbers.append(int(number))
        detail["pattern_score_norm"] = round(pattern_norm, 6)
        detail["occurrence_score_norm"] = round(occurrence_norm, 6)
        detail["occurrence_count"] = occurrence_count
        detail["occurrence_overlap"] = overlap
        detail["overlap_bonus"] = round(safe_overlap_bonus if overlap else 0.0, 6)
        detail["fusion_score"] = round(
            (normalized_pattern_weight * pattern_norm)
            + (normalized_occurrence_weight * occurrence_norm)
            + (safe_overlap_bonus if overlap else 0.0),
            6,
        )
        reranked_details.append(detail)

    reranked_details.sort(
        key=lambda item: (
            -float(item.get("fusion_score", 0.0) or 0.0),
            -float(item.get("weighted_support_score", 0.0) or 0.0),
            -int(item.get("support_score", item.get("support_count", 0)) or 0),
            int(item.get("number", 0) or 0),
        )
    )

    fused_list = [int(item["number"]) for item in reranked_details]
    tail_replacements: List[Dict[str, Any]] = []
    occurrence_only_numbers_injected: List[int] = []

    if safe_tail_replace_limit > 0 and top_occurrence_count >= 2:
        occurrence_only_candidates: List[Dict[str, Any]] = []
        occurrence_only_seen: set[int] = set()
        occurrence_strength_threshold = max(2, int(round(top_occurrence_count * 0.55)))
        for item in occurrence_ranking_details:
            if not isinstance(item, dict):
                continue
            try:
                candidate_number = int(item.get("number"))
                candidate_count = int(item.get("count", 0) or 0)
            except (TypeError, ValueError):
                continue
            if not (0 <= candidate_number <= 36):
                continue
            if candidate_number in occurrence_only_seen or candidate_number in fused_list:
                continue
            candidate_norm = (
                float(candidate_count) / float(top_occurrence_count)
                if top_occurrence_count > 0
                else 0.0
            )
            if candidate_count < occurrence_strength_threshold or candidate_norm < 0.55:
                continue
            occurrence_only_seen.add(candidate_number)
            occurrence_only_candidates.append(
                {
                    "number": candidate_number,
                    "count": candidate_count,
                    "occurrence_norm": round(candidate_norm, 6),
                }
            )

        if occurrence_only_candidates and overlap_numbers:
            removable_indexes: List[int] = []
            protected_numbers = set(
                int(detail.get("number"))
                for detail in reranked_details[: max(1, len(reranked_details) // 2)]
                if isinstance(detail, dict)
            )
            for index in range(len(reranked_details) - 1, -1, -1):
                if len(removable_indexes) >= safe_tail_replace_limit:
                    break
                number = int(reranked_details[index].get("number", -1))
                if number in protected_numbers:
                    continue
                removable_indexes.append(index)
            removable_indexes.sort()

            for replace_index, candidate in zip(removable_indexes, occurrence_only_candidates):
                removed_detail = dict(reranked_details[replace_index])
                inserted_number = int(candidate["number"])
                inserted_count = int(candidate["count"])
                inserted_norm = float(candidate["occurrence_norm"])
                inserted_detail = dict(details_map.get(inserted_number) or {})
                inserted_detail.update(
                    {
                        "number": inserted_number,
                        "support_score": int(inserted_detail.get("support_score", inserted_detail.get("support_count", 0)) or 0),
                        "support_count": int(inserted_detail.get("support_count", inserted_detail.get("support_score", 0)) or 0),
                        "weighted_support_score": float(inserted_detail.get("weighted_support_score", 0.0) or 0.0),
                        "supporting_patterns": list(inserted_detail.get("supporting_patterns") or []),
                        "pattern_score_norm": 0.0,
                        "occurrence_score_norm": round(inserted_norm, 6),
                        "occurrence_count": inserted_count,
                        "occurrence_overlap": False,
                        "overlap_bonus": 0.0,
                        "fusion_score": round(normalized_occurrence_weight * inserted_norm, 6),
                        "occurrence_tail_injected": True,
                        "injected_from_occurrence_only": True,
                    }
                )
                removed_number = int(removed_detail.get("number", -1))
                reranked_details[replace_index] = inserted_detail
                fused_list[replace_index] = inserted_number
                tail_replacements.append(
                    {
                        "index": replace_index,
                        "removed_number": removed_number,
                        "inserted_number": inserted_number,
                        "inserted_occurrence_count": inserted_count,
                        "inserted_occurrence_norm": round(inserted_norm, 6),
                    }
                )
                occurrence_only_numbers_injected.append(inserted_number)

    occurrence_inverted_detected = str(occurrence_snapshot.get("cancelled_reason") or "") == "inverted_hit"
    occurrence_invert_hit_offsets = list(
        (occurrence_snapshot.get("inverted_evaluation") or {}).get("hit_offsets") or []
    )
    occurrence_invert_hit_count = int(
        (occurrence_snapshot.get("inverted_evaluation") or {}).get("hit_count", 0) or 0
    )

    fusion_meta.update(
        {
            "applied": fused_list != base_list or True,
            "mode": "rerank_tail_replace" if tail_replacements else "rerank",
            "occurrence_available": True,
            "occurrence_ranking": [int(number) for number in (occurrence_snapshot.get("ranking") or [])],
            "occurrence_ranking_details": occurrence_ranking_details,
            "occurrence_overlap_count": len(overlap_numbers),
            "occurrence_overlap_numbers": overlap_numbers,
            "occurrence_inverted_detected": occurrence_inverted_detected,
            "occurrence_invert_hit_count": occurrence_invert_hit_count,
            "occurrence_invert_hit_offsets": occurrence_invert_hit_offsets,
            "top_occurrence_count": top_occurrence_count,
            "tail_replace_applied": bool(tail_replacements),
            "tail_replacements": tail_replacements,
            "occurrence_only_numbers_injected": occurrence_only_numbers_injected,
            "reason": (
                f"Lista reranqueada por ocorrencias com {len(overlap_numbers)} numero(s) em comum "
                f"com o top {safe_ranking_size}"
                f"{f' e {len(tail_replacements)} troca(s) na cauda' if tail_replacements else ''}."
            ),
        }
    )

    payload["list"] = list(fused_list)
    payload["suggestion"] = list(fused_list)
    payload["ordered_suggestion"] = list(fused_list)
    payload["selected_number_details"] = reranked_details
    payload["occurrence_fusion"] = fusion_meta
    payload["occurrence_ranking"] = list(fusion_meta["occurrence_ranking"])
    payload["occurrence_ranking_details"] = occurrence_ranking_details
    payload["occurrence_overlap_count"] = int(fusion_meta["occurrence_overlap_count"])
    payload["occurrence_overlap_numbers"] = list(overlap_numbers)
    payload["occurrence_inverted_detected"] = occurrence_inverted_detected
    payload["occurrence_invert_hit_count"] = occurrence_invert_hit_count
    payload["occurrence_invert_hit_offsets"] = occurrence_invert_hit_offsets
    payload["occurrence_tail_replace_applied"] = bool(tail_replacements)
    payload["occurrence_tail_replacements"] = list(tail_replacements)
    payload["occurrence_only_numbers_injected"] = list(occurrence_only_numbers_injected)
    payload["explanation"] = (
        f"{str(payload.get('explanation') or '').strip()} "
        f"{fusion_meta['reason']}"
    ).strip()
    return payload
