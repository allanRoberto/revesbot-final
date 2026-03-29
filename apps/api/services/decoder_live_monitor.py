from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List


def build_signal_candidate(
    analysis: Dict[str, Any],
    *,
    include_secondary: bool = False,
    max_numbers: int = 12,
    min_confidence: int = 55,
    min_matched_episodes: int = 12,
    require_threshold_mode: bool = False,
) -> Dict[str, Any]:
    suggestion = analysis.get("suggestion") or {}
    summary = analysis.get("summary") or {}
    primary = [int(number) for number in (suggestion.get("primary_numbers") or [])]
    secondary = [int(number) for number in (suggestion.get("secondary_numbers") or [])]
    requested_count = max(1, int(max_numbers or 1))

    ranked_numbers: List[int] = []
    for candidate in (analysis.get("top_candidates") or []):
        number = candidate.get("number")
        if number is None:
            continue
        coerced = int(number)
        if coerced not in ranked_numbers:
            ranked_numbers.append(coerced)

    fallback_numbers = list(primary)
    if include_secondary:
        for number in secondary:
            if number not in fallback_numbers:
                fallback_numbers.append(number)

    ordered_pool = ranked_numbers or fallback_numbers
    numbers = ordered_pool[:requested_count]

    confidence_score = int((suggestion.get("confidence") or {}).get("score") or 0)
    matched_episodes = int(summary.get("matched_episodes") or 0)
    selection_mode = str(summary.get("selection_mode") or "none")

    reasons: List[str] = []
    if not suggestion.get("available"):
        reasons.append("Sugestão indisponível.")
    if not numbers:
        reasons.append("Nenhum número sugerido pelo decoder.")
    if confidence_score < min_confidence:
        reasons.append(f"Confiança {confidence_score} abaixo do mínimo {min_confidence}.")
    if matched_episodes < min_matched_episodes:
        reasons.append(
            f"Episódios parecidos {matched_episodes} abaixo do mínimo {min_matched_episodes}."
        )
    if require_threshold_mode and selection_mode != "threshold":
        reasons.append("Modo de seleção não está em threshold.")

    emit = not reasons
    avg_similarity = 0.0
    similar_episodes = analysis.get("similar_episodes") or []
    if similar_episodes:
        avg_similarity = sum(float(item.get("similarity") or 0.0) for item in similar_episodes) / len(similar_episodes)

    return {
        "emit": emit,
        "reason": "Sinal apto para monitoramento." if emit else " ".join(reasons),
        "numbers": numbers,
        "primary_numbers": primary,
        "secondary_numbers": secondary,
        "confidence_score": confidence_score,
        "confidence_label": (suggestion.get("confidence") or {}).get("label") or "Muito baixa",
        "matched_episodes": matched_episodes,
        "selection_mode": selection_mode,
        "future_horizon": int(summary.get("future_horizon") or 0),
        "avg_similarity": round(avg_similarity, 4),
        "regimes": list((analysis.get("current_state") or {}).get("active_regimes") or []),
        "number_count_requested": requested_count,
        "number_count_used": len(numbers),
    }


def open_live_signal(
    analysis: Dict[str, Any],
    decision: Dict[str, Any],
    *,
    roulette_id: str,
    emitted_at: str | None = None,
) -> Dict[str, Any]:
    return {
        "signal_id": f"decoder-{roulette_id}-{emitted_at or datetime.utcnow().isoformat()}",
        "roulette_id": roulette_id,
        "emitted_at": emitted_at or datetime.utcnow().isoformat(),
        "status": "active",
        "attempts": 0,
        "max_attempts": int(decision.get("future_horizon") or 0),
        "numbers": list(decision.get("numbers") or []),
        "primary_numbers": list(decision.get("primary_numbers") or []),
        "secondary_numbers": list(decision.get("secondary_numbers") or []),
        "confidence_score": int(decision.get("confidence_score") or 0),
        "confidence_label": decision.get("confidence_label") or "Muito baixa",
        "matched_episodes": int(decision.get("matched_episodes") or 0),
        "selection_mode": decision.get("selection_mode") or "none",
        "avg_similarity": float(decision.get("avg_similarity") or 0.0),
        "regimes": list(decision.get("regimes") or []),
        "state_numbers": list((analysis.get("current_state") or {}).get("numbers") or []),
        "analysis_snapshot": {
            "summary": deepcopy(analysis.get("summary") or {}),
            "suggestion": deepcopy(analysis.get("suggestion") or {}),
        },
    }


def resolve_live_signal(signal: Dict[str, Any], *, number: int) -> Dict[str, Any]:
    updated = deepcopy(signal)
    updated["attempts"] = int(updated.get("attempts") or 0) + 1
    updated["last_number"] = int(number)

    if int(number) in [int(item) for item in (updated.get("numbers") or [])]:
        updated["status"] = "win"
        updated["hit_number"] = int(number)
        updated["hit_attempt"] = updated["attempts"]
        updated["resolved"] = True
        return updated

    if updated["attempts"] >= int(updated.get("max_attempts") or 0):
        updated["status"] = "loss"
        updated["resolved"] = True
        return updated

    updated["status"] = "active"
    updated["resolved"] = False
    return updated
