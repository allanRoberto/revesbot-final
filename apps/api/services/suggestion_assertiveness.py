from __future__ import annotations

from typing import Any, Dict, Mapping, Sequence


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, float(value)))


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _confidence_label(score: float | int) -> str:
    safe_score = max(0, min(100, int(round(float(score)))))
    if safe_score >= 75:
        return "Alta"
    if safe_score >= 55:
        return "Media"
    return "Baixa"


def _action_quality(action: str) -> float:
    normalized = str(action or "").strip().lower()
    mapping = {
        "enter": 1.0,
        "switch": 0.88,
        "hold": 0.74,
        "wait": 0.42,
        "skip": 0.12,
    }
    return float(mapping.get(normalized, 0.35))


def evaluate_simple_signal_assertiveness(
    simple_payload: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    payload = dict(simple_payload or {})
    suggestion = [
        int(number)
        for number in (payload.get("list") or payload.get("suggestion") or [])
        if 0 <= int(number) <= 36
    ]
    entry_shadow = payload.get("entry_shadow")
    if not isinstance(entry_shadow, Mapping):
        entry_shadow = {}
    entry_confidence = entry_shadow.get("entry_confidence")
    if not isinstance(entry_confidence, Mapping):
        entry_confidence = {}
    recommendation = entry_shadow.get("recommendation")
    if not isinstance(recommendation, Mapping):
        recommendation = {}
    expected_value = entry_shadow.get("expected_value")
    if not isinstance(expected_value, Mapping):
        expected_value = {}

    top_support_count = _safe_int(payload.get("top_support_count"), 0)
    avg_support_count = _safe_float(payload.get("avg_support_count"), 0.0)
    pattern_count = _safe_int(payload.get("pattern_count"), 0)
    occurrence_overlap_count = _safe_int(payload.get("occurrence_overlap_count"), 0)
    occurrence_inverted_detected = bool(payload.get("occurrence_inverted_detected", False))
    shadow_confidence_score = _safe_int(entry_confidence.get("score"), 0)
    late_hit_risk = _clamp(_safe_float(entry_shadow.get("late_hit_risk"), 1.0), 0.0, 1.0)
    expected_value_units = _safe_float(expected_value.get("net_units"), 0.0)
    shadow_action = str(recommendation.get("action", "") or "").strip().lower()
    available = bool(payload.get("available")) and bool(suggestion)

    support_quality = (
        (min(top_support_count, 8) / 8.0) * 0.45
        + (min(avg_support_count, 6.0) / 6.0) * 0.35
        + (min(pattern_count, 18) / 18.0) * 0.20
    ) * 100.0
    overlap_quality = (min(occurrence_overlap_count, 3) / 3.0) * 100.0
    timing_quality = (1.0 - late_hit_risk) * 100.0
    expected_value_quality = _clamp((expected_value_units + 4.0) / 8.0, 0.0, 1.0) * 100.0
    action_quality = _action_quality(shadow_action) * 100.0

    score = (
        (shadow_confidence_score * 0.34)
        + (support_quality * 0.22)
        + (overlap_quality * 0.14)
        + (timing_quality * 0.15)
        + (expected_value_quality * 0.09)
        + (action_quality * 0.06)
    )
    if occurrence_inverted_detected:
        score -= 6.0
    score = _clamp(score, 0.0, 100.0)
    score_int = int(round(score))

    reasons: list[str] = []
    if top_support_count >= 5:
        reasons.append("topo da simple com apoio estrutural forte")
    elif top_support_count <= 2:
        reasons.append("topo da simple com apoio estrutural fraco")
    if occurrence_overlap_count >= 2:
        reasons.append("overlap relevante com o padrão de ocorrência")
    elif occurrence_overlap_count == 0:
        reasons.append("simple sem confirmação relevante da ocorrência")
    if late_hit_risk <= 0.28:
        reasons.append("risco tardio controlado no entry shadow")
    elif late_hit_risk >= 0.40:
        reasons.append("entry shadow indica risco tardio elevado")
    if expected_value_units > 0:
        reasons.append("valor esperado positivo no entry shadow")
    elif expected_value_units <= -1.5:
        reasons.append("valor esperado fraco para entrada imediata")
    if occurrence_inverted_detected:
        reasons.append("ocorrência veio invertida antes do gatilho")

    if not available:
        action = "skip"
        label = "Bloquear"
        reason = "Simple suggestion indisponível para avaliação de assertividade."
    elif shadow_action == "skip" or score_int < 42:
        action = "skip"
        label = "Bloquear"
        reason = "Sinal simples com qualidade insuficiente para entrada."
    elif shadow_action == "wait" or score_int < 58:
        action = "wait"
        label = "Esperar"
        reason = "Sinal simples pede confirmação adicional antes da aposta."
    else:
        action = "enter"
        label = "Entrar"
        reason = "Sinal simples com apoio estrutural e timing aceitáveis."

    return {
        "enabled": True,
        "available": available,
        "score": score_int,
        "label": _confidence_label(score_int),
        "recommendation": {
            "action": action,
            "label": label,
            "reason": reason,
        },
        "components": {
            "shadow_confidence_score": shadow_confidence_score,
            "support_quality": round(support_quality, 4),
            "occurrence_overlap_quality": round(overlap_quality, 4),
            "timing_quality": round(timing_quality, 4),
            "expected_value_quality": round(expected_value_quality, 4),
            "action_quality": round(action_quality, 4),
            "late_hit_risk": round(late_hit_risk, 6),
            "expected_value_units": round(expected_value_units, 6),
            "top_support_count": top_support_count,
            "avg_support_count": round(avg_support_count, 4),
            "pattern_count": pattern_count,
            "occurrence_overlap_count": occurrence_overlap_count,
            "occurrence_inverted_detected": occurrence_inverted_detected,
            "shadow_action": shadow_action,
            "suggestion_size": len(suggestion),
        },
        "reasons": reasons,
    }


def evaluate_final_signal_assertiveness(
    *,
    enabled: bool,
    min_score: int,
    candidate_list: Sequence[int] | None,
    candidate_confidence: Mapping[str, Any] | None,
    optimized_available: bool,
    optimized_confidence_effective: int,
    simple_payload: Mapping[str, Any] | None,
    entry_policy: Mapping[str, Any] | None,
    protected_mode_enabled: bool = False,
) -> Dict[str, Any]:
    simple_quality = evaluate_simple_signal_assertiveness(simple_payload)
    safe_candidate_confidence = dict(candidate_confidence or {})
    safe_entry_policy = dict(entry_policy or {})
    candidate_numbers = [int(number) for number in (candidate_list or []) if 0 <= int(number) <= 36]
    candidate_confidence_score = _safe_int(safe_candidate_confidence.get("score"), 0)
    optimized_confidence_score = max(0, min(100, int(optimized_confidence_effective or 0)))
    policy_action = str(safe_entry_policy.get("action", "") or "").strip().lower()
    policy_quality = _action_quality(policy_action) * 100.0
    occurrence_overlap_count = _safe_int(simple_quality.get("components", {}).get("occurrence_overlap_count"), 0)
    occurrence_inverted_detected = bool(
        simple_quality.get("components", {}).get("occurrence_inverted_detected", False)
    )
    shadow_action = str(simple_quality.get("components", {}).get("shadow_action", "") or "").strip().lower()

    score = (
        (candidate_confidence_score * 0.36)
        + (optimized_confidence_score * 0.24)
        + (_safe_int(simple_quality.get("score"), 0) * 0.28)
        + (policy_quality * 0.12)
    )
    if occurrence_overlap_count >= 2:
        score += 4.0
    elif occurrence_overlap_count <= 0:
        score -= 4.0
    if occurrence_inverted_detected:
        score -= 4.0
    if shadow_action == "skip":
        score -= 10.0
    elif shadow_action == "wait":
        score -= 5.0
    if not optimized_available:
        score -= 8.0
    if policy_action == "wait":
        score -= 10.0
    score = _clamp(score, 0.0, 100.0)
    score_int = int(round(score))
    safe_min_score = max(0, min(100, int(min_score)))

    if not enabled:
        recommendation_action = "enter"
        blocked = False
        passed = True
        recommendation_reason = "Meta gate de assertividade desativado."
    elif protected_mode_enabled:
        recommendation_action = "enter"
        blocked = False
        passed = True
        recommendation_reason = "Modo protegido mantém a emissão sem bloquear por assertividade."
    elif not candidate_numbers:
        recommendation_action = "skip"
        blocked = True
        passed = False
        recommendation_reason = "Sem lista candidata válida para emissão."
    elif shadow_action == "skip" and score_int < max(35, safe_min_score - 5):
        recommendation_action = "skip"
        blocked = True
        passed = False
        recommendation_reason = "Entry shadow e qualidade final convergem para bloquear a entrada."
    elif policy_action == "wait" or shadow_action == "wait" or score_int < safe_min_score:
        recommendation_action = "wait"
        blocked = True
        passed = False
        recommendation_reason = "Qualidade final abaixo do corte operacional ou política pedindo espera."
    else:
        recommendation_action = "enter"
        blocked = False
        passed = True
        recommendation_reason = "Qualidade final suficiente para emissão imediata."

    reasons: list[str] = []
    if candidate_confidence_score >= 60:
        reasons.append("confidence final da fusão em faixa operacional")
    elif candidate_confidence_score < 40:
        reasons.append("confidence final da fusão ainda baixa")
    if optimized_confidence_score >= 65:
        reasons.append("motor otimizado confirmou o contexto")
    elif optimized_confidence_score < 45:
        reasons.append("motor otimizado sem força suficiente")
    reasons.extend(simple_quality.get("reasons", []))
    if policy_action == "wait":
        wait_spins = _safe_int(safe_entry_policy.get("recommended_wait_spins"), 0)
        reasons.append(
            f"política de entrada pediu espera de {wait_spins} giro(s)" if wait_spins > 0
            else "política de entrada pediu espera"
        )

    return {
        "enabled": bool(enabled),
        "passed": bool(passed),
        "blocked": bool(blocked),
        "protected_mode_bypass": bool(protected_mode_enabled),
        "min_score": safe_min_score,
        "score": score_int,
        "label": _confidence_label(score_int),
        "recommendation": {
            "action": recommendation_action,
            "label": "Entrar" if recommendation_action == "enter" else ("Esperar" if recommendation_action == "wait" else "Bloquear"),
            "reason": recommendation_reason,
        },
        "components": {
            "candidate_confidence_score": candidate_confidence_score,
            "optimized_confidence_score": optimized_confidence_score,
            "simple_quality_score": _safe_int(simple_quality.get("score"), 0),
            "policy_quality": round(policy_quality, 4),
            "policy_action": policy_action,
            "occurrence_overlap_count": occurrence_overlap_count,
            "occurrence_inverted_detected": occurrence_inverted_detected,
            "shadow_action": shadow_action,
            "candidate_size": len(candidate_numbers),
        },
        "simple_quality": simple_quality,
        "reasons": reasons,
    }
