from __future__ import annotations

import asyncio
from collections import defaultdict
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.core.db import history_coll
from api.patterns.engine import pattern_engine
from api.services.pattern_telemetry import pattern_telemetry
from api.services.pattern_correlation import correlation_matrix
from api.services.backtesting import backtest_engine
from api.services.suggestion_filter import suggestion_filter
from api.services.pattern_decay import pattern_decay
from api.services.pattern_training_service import pattern_training_service
from api.services.pattern_training_jobs import pattern_training_jobs
from api.services.pattern_weight_profiles import pattern_weight_profiles
from api.services.final_suggestion_signal_policy import final_suggestion_signal_policy
from api.services.final_suggestion_entry_intelligence import final_suggestion_entry_intelligence
from api.patterns.final_suggestion import (
    build_base_suggestion,
    build_final_suggestion,
    build_focus_context,
    build_runtime_overrides,
    compute_confidence,
    normalize_weights,
)


router = APIRouter()


class OptimizedSuggestionRequest(BaseModel):
    history: List[int] = Field(default_factory=list)
    base_suggestion: List[int] = Field(default_factory=list)
    legacy_confidence_score: float | None = None
    focus_number: int | None = None
    from_index: int = 0
    max_numbers: int = 18
    log_event: bool = True
    runtime_overrides: Dict[str, Dict[str, float | int | bool]] = Field(default_factory=dict)


class PatternBacktestRequest(BaseModel):
    history: List[int] = Field(default_factory=list)
    max_numbers: int = 18
    max_attempts: int = 12
    max_entries: int = 500
    persist_events: bool = True
    use_adaptive_weights: bool = False


class ApplyMultipliersRequest(BaseModel):
    history: List[int] = Field(default_factory=list)
    max_numbers: int = 18
    max_attempts: int = 12
    max_entries: int = 500
    use_adaptive_weights: bool = False
    min_signals: int = 20
    blend: float = 0.7
    dry_run: bool = False


class AutoTuneRequest(BaseModel):
    history: List[int] = Field(default_factory=list)
    min_history_size: int = 500
    dry_run: bool = False


class FinalSuggestionRequest(BaseModel):
    history: List[int] = Field(default_factory=list)
    focus_number: int | None = None
    from_index: int = 0
    max_numbers: int = 12
    optimized_max_numbers: int = 37
    base_weight: float = 0.4
    optimized_weight: float = 0.6
    runtime_overrides: Dict[str, Dict[str, float | int | bool]] = Field(default_factory=dict)
    siege_window: int = 6
    siege_min_occurrences: int = 3
    siege_min_streak: int = 2
    siege_veto_relief: float = 0.4
    block_bets_enabled: bool = False
    inversion_enabled: bool = True
    inversion_context_window: int = 15
    inversion_penalty_factor: float = 0.3
    weight_profile_id: str | None = None


class ActiveSignalRequest(BaseModel):
    suggestion: List[int] = Field(default_factory=list)
    confidence_score: int = 0
    suggestion_size: int = 0
    policy_score: float | None = None
    block_compaction_applied: bool = False
    attempts_used: int = 0
    max_attempts: int = 1
    wait_spins: int = 0


class FinalSuggestionPolicyRequest(BaseModel):
    history: List[int] = Field(default_factory=list)
    focus_number: int | None = None
    from_index: int = 0
    max_numbers: int = 12
    optimized_max_numbers: int = 37
    base_weight: float = 0.4
    optimized_weight: float = 0.6
    runtime_overrides: Dict[str, Dict[str, float | int | bool]] = Field(default_factory=dict)
    siege_window: int = 6
    siege_min_occurrences: int = 3
    siege_min_streak: int = 2
    siege_veto_relief: float = 0.4
    block_bets_enabled: bool = False
    inversion_enabled: bool = True
    inversion_context_window: int = 15
    inversion_penalty_factor: float = 0.3
    weight_profile_id: str | None = None
    max_attempts: int = 4
    policy_observation_window: int = 2
    policy_switch_min_hold_spins: int = 1
    policy_switch_min_score_delta: float = 6.0
    policy_switch_min_confidence_delta: int = 4
    active_signal: ActiveSignalRequest | None = None


class PatternTrainingRunRequest(BaseModel):
    roulette_id: str
    history_limit: int = 1000
    max_attempts: int = 4
    optimized_max_numbers: int = 18
    use_adaptive_weights: bool = False
    base_weight: float = 0.5
    optimized_weight: float = 0.5
    block_bets_enabled: bool = True
    inversion_enabled: bool = False
    inversion_context_window: int = 15
    inversion_penalty_factor: float = 0.3
    siege_window: int = 6
    siege_min_occurrences: int = 3
    siege_min_streak: int = 2
    siege_veto_relief: float = 0.4
    min_sample: int = 20
    full_sample: int = 120
    prior_strength: float = 24.0
    weight_floor: float = 0.75
    weight_ceil: float = 1.30
    lift_alpha: float = 0.85
    recent_window: int = 30
    recent_decay_start: int = 2
    recent_decay_per_miss: float = 0.05
    recent_decay_cap: float = 0.25
    policy_observation_window: int = 2
    policy_pressure_window: int = 3
    policy_min_block_touches: int = 1
    policy_min_near_touches: int = 2
    policy_confirm_window: int = 2
    policy_switch_window: int = 3
    policy_switch_min_score_delta: float = 6.0
    policy_switch_min_confidence_delta: int = 4
    policy_switch_min_hold_spins: int = 1


class PatternTrainingSaveRequest(BaseModel):
    name: str
    roulette_id: str
    history_size: int
    max_attempts: int
    optimized_max_numbers: int
    use_adaptive_weights: bool = False
    config: Dict[str, Any] = Field(default_factory=dict)
    summary: Dict[str, Any] = Field(default_factory=dict)
    patterns: List[Dict[str, Any]] = Field(default_factory=list)
    weights: Dict[str, float] = Field(default_factory=dict)
    effective_weights: Dict[str, float] = Field(default_factory=dict)
def _event_from_result(
    *,
    source: str,
    focus_number: int | None,
    from_index: int,
    history: List[int],
    result: Dict,
    max_attempts: int = 12,
) -> Dict:
    progress = pattern_telemetry.evaluate_progress(
        suggestion_list=[int(n) for n in (result.get("suggestion") or []) if str(n).isdigit()],
        history=[int(n) for n in history if str(n).isdigit()],
        from_index=max(0, int(from_index)),
        max_attempts=max(1, int(max_attempts)),
    )
    return {
        "source": source,
        "focus_number": int(focus_number) if isinstance(focus_number, int) else None,
        "from_index": max(0, int(from_index)),
        "confidence": result.get("confidence", {}),
        "progress": progress,
        "suggestion_size": len(result.get("suggestion", []) or []),
        "active_patterns": [
            {
                "pattern_id": c.get("pattern_id"),
                "pattern_name": c.get("pattern_name"),
            }
            for c in (result.get("contributions") or [])
            if isinstance(c, dict)
        ],
    }


def _load_pattern_definition_files() -> Dict[str, Path]:
    base = getattr(pattern_engine, "_patterns_dir", None)
    patterns_dir = Path(base) if base else (Path(__file__).resolve().parent.parent / "patterns" / "definitions")
    mapping: Dict[str, Path] = {}
    for path in sorted(patterns_dir.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        pid = str(raw.get("id", "")).strip()
        if pid:
            mapping[pid] = path
    return mapping


async def _load_history_for_training(roulette_id: str, history_limit: int) -> List[int]:
    safe_limit = max(50, min(50000, int(history_limit)))
    cursor = (
        history_coll
        .find({"roulette_id": roulette_id})
        .sort("timestamp", -1)
        .limit(safe_limit)
    )
    docs = await cursor.to_list(length=safe_limit)
    return [int(doc["value"]) for doc in docs if 0 <= int(doc["value"]) <= 36]


@router.get("/api/patterns/training/profiles")
async def list_pattern_training_profiles():
    try:
        return {
            "profiles": pattern_weight_profiles.list_profiles(),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/patterns/training/profiles/{profile_id}")
async def get_pattern_training_profile(profile_id: str):
    try:
        profile = pattern_weight_profiles.load_profile(profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Perfil nao encontrado")
        return profile
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/patterns/training/run")
async def run_pattern_training(payload: PatternTrainingRunRequest):
    try:
        roulette_id = str(payload.roulette_id or "").strip()
        if not roulette_id:
            raise HTTPException(status_code=400, detail="roulette_id obrigatorio")

        history = await _load_history_for_training(roulette_id, payload.history_limit)
        job = pattern_training_jobs.create_job(
            params={
                "roulette_id": roulette_id,
                "history_limit": max(50, min(50000, int(payload.history_limit))),
                "max_attempts": max(1, min(50, int(payload.max_attempts))),
                "optimized_max_numbers": max(1, min(37, int(payload.optimized_max_numbers))),
                "use_adaptive_weights": bool(payload.use_adaptive_weights),
                "block_bets_enabled": bool(payload.block_bets_enabled),
            }
        )

        def _worker() -> Dict[str, Any]:
            return pattern_training_service.run_training(
                roulette_id=roulette_id,
                history=history,
                max_attempts=max(1, min(50, int(payload.max_attempts))),
                optimized_max_numbers=max(1, min(37, int(payload.optimized_max_numbers))),
                use_adaptive_weights=bool(payload.use_adaptive_weights),
                base_weight=max(0.0, min(1.0, float(payload.base_weight))),
                optimized_weight=max(0.0, min(1.0, float(payload.optimized_weight))),
                block_bets_enabled=bool(payload.block_bets_enabled),
                inversion_enabled=bool(payload.inversion_enabled),
                inversion_context_window=max(1, min(50, int(payload.inversion_context_window))),
                inversion_penalty_factor=max(0.0, min(1.0, float(payload.inversion_penalty_factor))),
                siege_window=max(2, min(20, int(payload.siege_window))),
                siege_min_occurrences=max(1, min(10, int(payload.siege_min_occurrences))),
                siege_min_streak=max(1, min(10, int(payload.siege_min_streak))),
                siege_veto_relief=max(0.0, min(1.0, float(payload.siege_veto_relief))),
                min_sample=max(1, int(payload.min_sample)),
                full_sample=max(int(payload.min_sample) + 1, int(payload.full_sample)),
                prior_strength=max(1.0, float(payload.prior_strength)),
                weight_floor=max(0.1, min(3.0, float(payload.weight_floor))),
                weight_ceil=max(0.1, min(5.0, float(payload.weight_ceil))),
                lift_alpha=max(0.0, min(2.0, float(payload.lift_alpha))),
                recent_window=max(1, int(payload.recent_window)),
                recent_decay_start=max(0, int(payload.recent_decay_start)),
                recent_decay_per_miss=max(0.0, min(1.0, float(payload.recent_decay_per_miss))),
                recent_decay_cap=max(0.0, min(1.0, float(payload.recent_decay_cap))),
                policy_observation_window=max(1, min(10, int(payload.policy_observation_window))),
                policy_pressure_window=max(1, min(10, int(payload.policy_pressure_window))),
                policy_min_block_touches=max(1, min(10, int(payload.policy_min_block_touches))),
                policy_min_near_touches=max(1, min(10, int(payload.policy_min_near_touches))),
                policy_confirm_window=max(1, min(10, int(payload.policy_confirm_window))),
                policy_switch_window=max(1, min(10, int(payload.policy_switch_window))),
                policy_switch_min_score_delta=max(0.0, min(50.0, float(payload.policy_switch_min_score_delta))),
                policy_switch_min_confidence_delta=max(0, min(50, int(payload.policy_switch_min_confidence_delta))),
                policy_switch_min_hold_spins=max(1, min(10, int(payload.policy_switch_min_hold_spins))),
                progress_callback=lambda info: pattern_training_jobs.update_progress(job["job_id"], info),
            )

        asyncio.create_task(
            pattern_training_jobs.run_in_background(
                job_id=job["job_id"],
                worker=_worker,
            )
        )

        return {
            "accepted": True,
            "job_id": job["job_id"],
            "status": job["status"],
            "progress": job["progress"],
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/patterns/training/jobs/{job_id}")
async def get_pattern_training_job(job_id: str):
    try:
        job = pattern_training_jobs.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Treino nao encontrado")
        return job
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/patterns/training/save")
async def save_pattern_training_profile(payload: PatternTrainingSaveRequest):
    try:
        profile = pattern_weight_profiles.save_profile(
            name=str(payload.name or "").strip() or "perfil-treinado",
            roulette_id=str(payload.roulette_id or "").strip(),
            history_size=max(0, int(payload.history_size)),
            max_attempts=max(1, int(payload.max_attempts)),
            optimized_max_numbers=max(1, min(37, int(payload.optimized_max_numbers))),
            use_adaptive_weights=bool(payload.use_adaptive_weights),
            config=dict(payload.config or {}),
            summary=dict(payload.summary or {}),
            patterns=list(payload.patterns or []),
            weights={str(k): float(v) for k, v in dict(payload.weights or {}).items()},
            effective_weights={str(k): float(v) for k, v in dict(payload.effective_weights or {}).items()},
        )
        return {
            "saved": True,
            "profile": {
                "id": profile.get("id"),
                "name": profile.get("name"),
            },
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


def _parse_optimized_suggestion_sorted(optimized_result: Dict[str, Any]) -> List[int]:
    """
    Mantém compatibilidade com o comportamento legado:
    lista otimizada em ordem numérica.
    """
    parsed: List[int] = []
    for raw_n in optimized_result.get("suggestion", []) or []:
        try:
            n = int(raw_n)
        except (TypeError, ValueError):
            continue
        if 0 <= n <= 36:
            parsed.append(n)
    return parsed


def _build_ranked_optimized_list(number_details: Any, fallback: List[int]) -> List[int]:
    """
    Extrai ordem por score (net_score) a partir de number_details.
    Usa apenas números selecionados pelo engine.
    """
    if not isinstance(number_details, list):
        return list(fallback)

    ranked: List[int] = []
    for item in number_details:
        if not isinstance(item, dict):
            continue
        if not bool(item.get("selected", False)):
            continue
        try:
            n = int(item.get("number"))
        except (TypeError, ValueError):
            continue
        if 0 <= n <= 36:
            ranked.append(n)

    if ranked:
        return ranked
    return list(fallback)


async def _compute_final_suggestion(
    payload: FinalSuggestionRequest,
) -> Dict[str, Any]:
    normalized_history = [int(n) for n in payload.history if 0 <= int(n) <= 36]
    if len(normalized_history) < 2:
        optimized_payload: Dict[str, Any] = {
            "available": False,
            "suggestion": [],
            "explanation": "Historico insuficiente para avaliacao otimizada.",
            "confidence": {"score": 0, "label": "Baixa"},
            "confidence_breakdown": pattern_engine._empty_confidence_breakdown(),
            "contributions": [],
            "negative_contributions": [],
            "pending_patterns": [],
            "number_details": [],
            "adaptive_weights": [],
        }
        return {
            "available": False,
            "list": [],
            "suggestion": [],
            "focus_number": None,
            "from_index": 0,
            "confidence": {"score": 0, "label": "Baixa"},
            "explanation": "Sem dados suficientes para fusao.",
            "breakdown": {"base_weight": 0.4, "optimized_weight": 0.6, "overlap_ratio": 0, "intersection_bonus": 0},
            "optimized_payload": optimized_payload,
            "optimized_suggestion": [],
            "optimized_confidence": 0,
            "optimized_confidence_obj": {"score": 0, "label": "Baixa"},
            "optimized_available": False,
            "optimized_explanation": optimized_payload["explanation"],
            "optimized_breakdown": optimized_payload["confidence_breakdown"],
            "optimized_contributions": [],
            "optimized_negative_contributions": [],
            "optimized_pending_patterns": [],
            "optimized_number_details": [],
            "optimized_adaptive_weights": [],
        }

    from_index = max(0, min(int(payload.from_index), len(normalized_history) - 1))
    focus_number = payload.focus_number
    if focus_number is None:
        focus_number = normalized_history[from_index]
    if not (0 <= int(focus_number) <= 36):
        focus_number = normalized_history[from_index]
    focus_number = int(focus_number)

    target_size = max(1, min(37, int(payload.max_numbers)))
    optimized_max_numbers = max(1, min(37, int(payload.optimized_max_numbers)))
    final_base_weight, final_optimized_weight = normalize_weights(payload.base_weight, payload.optimized_weight)

    siege_window = max(2, min(20, int(payload.siege_window)))
    siege_min_occurrences = max(1, min(10, int(payload.siege_min_occurrences)))
    siege_min_streak = max(1, min(10, int(payload.siege_min_streak)))
    siege_veto_relief = max(0.0, min(1.0, float(payload.siege_veto_relief)))
    inversion_enabled = bool(payload.inversion_enabled)
    inversion_context_window = max(1, min(50, int(payload.inversion_context_window)))
    inversion_penalty_factor = max(0.0, min(1.0, float(payload.inversion_penalty_factor)))

    focus_context = build_focus_context(
        history=normalized_history,
        focus_number=focus_number,
        from_index=from_index,
    )
    pulled_counts = focus_context["pulled_counts"]
    bucket = focus_context["bucket"]
    pulled_total = len(focus_context["pulled"])

    base_confidence = compute_confidence(bucket, pulled_total)
    base_confidence_score = int(base_confidence.get("score", 0) or 0)

    base_list_ranked = build_base_suggestion(
        bucket=bucket,
        pulled_counts=pulled_counts,
        total_pulled=pulled_total,
        source_arr=normalized_history,
        from_index=from_index,
        siege_window=siege_window,
        siege_min_occurrences=siege_min_occurrences,
        siege_min_streak=siege_min_streak,
        siege_veto_relief=siege_veto_relief,
        preserve_ranking=True,
    )

    runtime_overrides = build_runtime_overrides(
        runtime_overrides=payload.runtime_overrides,
        siege_window=siege_window,
        siege_min_occurrences=siege_min_occurrences,
        siege_min_streak=siege_min_streak,
    )
    selected_profile_id = str(payload.weight_profile_id or "").strip() or None
    selected_profile = pattern_weight_profiles.load_profile(selected_profile_id) if selected_profile_id else None
    profile_weights = selected_profile.get("weights", {}) if isinstance(selected_profile, dict) else {}

    base_list_for_engine = sorted(base_list_ranked)
    optimized_result = pattern_engine.evaluate(
        history=normalized_history,
        base_suggestion=base_list_for_engine,
        focus_number=focus_number,
        from_index=from_index,
        max_numbers=optimized_max_numbers,
        runtime_overrides=runtime_overrides,
        weight_profile_id=selected_profile_id,
        weight_profile_weights=profile_weights if isinstance(profile_weights, dict) else {},
    )

    opt_list_sorted = _parse_optimized_suggestion_sorted(optimized_result)
    opt_confidence = int(optimized_result.get("confidence", {}).get("score", 0) or 0)
    number_details = optimized_result.get("number_details", [])
    opt_list_ranked = _build_ranked_optimized_list(number_details, opt_list_sorted)

    final_result = build_final_suggestion(
        base_list=base_list_ranked,
        optimized_list=opt_list_ranked,
        optimized_confidence=opt_confidence,
        number_details=number_details if isinstance(number_details, list) else [],
        base_confidence_score=base_confidence_score,
        max_size=target_size,
        history_arr=normalized_history,
        from_index=from_index,
        pulled_counts=pulled_counts,
        base_weight=final_base_weight,
        optimized_weight=final_optimized_weight,
        block_bets_enabled=bool(payload.block_bets_enabled),
        inversion_enabled=inversion_enabled,
        inversion_context_window=inversion_context_window,
        inversion_penalty_factor=inversion_penalty_factor,
    )

    final_list = final_result.get("list", []) if isinstance(final_result, dict) else []
    optimized_payload = {
        "available": bool(optimized_result.get("available", False)),
        "suggestion": opt_list_sorted,
        "explanation": optimized_result.get("explanation", ""),
        "confidence": optimized_result.get("confidence", {"score": 0, "label": "Baixa"}),
        "confidence_breakdown": optimized_result.get("confidence_breakdown", {}),
        "contributions": optimized_result.get("contributions", []),
        "negative_contributions": optimized_result.get("negative_contributions", []),
        "pending_patterns": optimized_result.get("pending_patterns", []),
        "number_details": number_details if isinstance(number_details, list) else [],
        "adaptive_weights": optimized_result.get("adaptive_weights", []),
        "weight_profile": {
            "id": selected_profile.get("id"),
            "name": selected_profile.get("name"),
        } if isinstance(selected_profile, dict) else None,
    }
    return {
        **final_result,
        "suggestion": final_list,
        "focus_number": focus_number,
        "from_index": from_index,
        "block_bets_enabled": bool(payload.block_bets_enabled),
        "optimized_max_numbers": optimized_max_numbers,
        "base_weight": final_base_weight,
        "optimized_weight": final_optimized_weight,
        "block_bets_enabled": bool(payload.block_bets_enabled),
        # Mantém payload de resposta compatível com ordem antiga.
        "base_suggestion": base_list_for_engine,
        "base_confidence": base_confidence_score,
        "base_bucket": bucket,
        "base_pulled_counts": pulled_counts,
        "optimized_payload": optimized_payload,
        "optimized_suggestion": opt_list_sorted,
        "optimized_confidence": opt_confidence,
        "optimized_confidence_obj": optimized_result.get("confidence", {"score": 0, "label": "Baixa"}),
        "optimized_available": bool(optimized_result.get("available", False)),
        "optimized_explanation": optimized_result.get("explanation", ""),
        "optimized_breakdown": optimized_result.get("confidence_breakdown", {}),
        "optimized_contributions": optimized_result.get("contributions", []),
        "optimized_negative_contributions": optimized_result.get("negative_contributions", []),
        "optimized_pending_patterns": optimized_result.get("pending_patterns", []),
        "optimized_number_details": number_details if isinstance(number_details, list) else [],
        "optimized_adaptive_weights": optimized_result.get("adaptive_weights", []),
        "optimized_weight_profile": optimized_payload.get("weight_profile"),
    }


@router.post("/api/patterns/optimized-suggestion")
async def get_optimized_suggestion(payload: OptimizedSuggestionRequest):
    try:
        if not payload.history:
            return {
                "engine_version": "v1",
                "available": False,
                "suggestion": [],
                "explanation": "Historico vazio.",
                "contributions": [],
                "confidence": {"score": 0, "label": "Baixa"},
                "confidence_breakdown": pattern_engine._empty_confidence_breakdown(),
                "negative_contributions": [],
                "pending_patterns": [],
                "number_details": [],
                "adaptive_weights": [],
            }

        result = pattern_engine.evaluate(
            history=payload.history,
            base_suggestion=payload.base_suggestion,
            focus_number=payload.focus_number,
            legacy_confidence_score=payload.legacy_confidence_score,
            from_index=max(0, payload.from_index),
            max_numbers=max(1, min(37, payload.max_numbers)),
            runtime_overrides=payload.runtime_overrides,
        )
        if payload.log_event:
            event = _event_from_result(
                source="optimized_suggestion",
                focus_number=payload.focus_number,
                from_index=payload.from_index,
                history=payload.history,
                result=result,
                max_attempts=12,
            )
            pattern_telemetry.append_event(event)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/patterns/metrics/backtest")
async def backtest_pattern_metrics(payload: PatternBacktestRequest):
    try:
        normalized_history = [int(n) for n in payload.history if 0 <= int(n) <= 36]
        if len(normalized_history) < 2:
            return {
                "engine_version": "v1",
                "available": False,
                "summary": {"totals": {"events": 0, "hits": 0, "misses": 0, "pending": 0, "unavailable": 0}, "patterns": []},
                "confidence_calibration": [],
                "events_generated": 0,
            }

        limit = max(2, min(len(normalized_history), max(2, int(payload.max_entries))))
        events: List[Dict] = []
        for idx in range(1, limit):
            focus = normalized_history[idx]
            result = pattern_engine.evaluate(
                history=normalized_history,
                base_suggestion=[],
                focus_number=focus,
                from_index=idx,
                max_numbers=max(1, min(37, int(payload.max_numbers))),
                use_adaptive_weights=bool(payload.use_adaptive_weights),
            )
            event = _event_from_result(
                source="backtest",
                focus_number=focus,
                from_index=idx,
                history=normalized_history,
                result=result,
                max_attempts=max(1, min(100, int(payload.max_attempts))),
            )
            events.append(event)
            if payload.persist_events:
                pattern_telemetry.append_event(event)

        summary = pattern_telemetry.summarize_events(events)
        bins: Dict[int, Dict[str, int]] = defaultdict(lambda: {"signals": 0, "hits": 0})
        for event in events:
            conf = event.get("confidence", {}) if isinstance(event.get("confidence"), dict) else {}
            score = int(conf.get("score", 0) or 0)
            bucket = max(0, min(100, (score // 10) * 10))
            bins[bucket]["signals"] += 1
            progress = event.get("progress", {}) if isinstance(event.get("progress"), dict) else {}
            if str(progress.get("status")) == "hit":
                bins[bucket]["hits"] += 1

        calibration = []
        for bucket in sorted(bins.keys()):
            signals = max(1, bins[bucket]["signals"])
            hits = bins[bucket]["hits"]
            calibration.append(
                {
                    "bucket_start": bucket,
                    "bucket_end": min(100, bucket + 9),
                    "signals": int(bins[bucket]["signals"]),
                    "hits": int(hits),
                    "hit_rate": round(hits / signals, 4),
                }
            )

        return {
            "engine_version": "v1",
            "available": True,
            "summary": summary,
            "confidence_calibration": calibration,
            "events_generated": len(events),
            "persisted": bool(payload.persist_events),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/patterns/metrics/events")
async def get_pattern_events(limit: int = 500):
    try:
        safe_limit = max(1, min(5000, int(limit)))
        events = pattern_telemetry.read_events(limit=safe_limit)
        summary = pattern_telemetry.summarize_events(events)
        return {
            "engine_version": "v1",
            "events_count": len(events),
            "summary": summary,
            "events": events[-100:],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/patterns/metrics/apply-multipliers")
async def apply_pattern_multipliers(payload: ApplyMultipliersRequest):
    try:
        normalized_history = [int(n) for n in payload.history if 0 <= int(n) <= 36]
        if len(normalized_history) < 2:
            return {
                "engine_version": "v1",
                "available": False,
                "updated": [],
                "skipped": [],
                "message": "Historico insuficiente para aplicar multiplicadores.",
            }

        # Reuse same backtest pipeline used by metrics endpoint
        limit = max(2, min(len(normalized_history), max(2, int(payload.max_entries))))
        events: List[Dict] = []
        for idx in range(1, limit):
            focus = normalized_history[idx]
            result = pattern_engine.evaluate(
                history=normalized_history,
                base_suggestion=[],
                focus_number=focus,
                from_index=idx,
                max_numbers=max(1, min(37, int(payload.max_numbers))),
                use_adaptive_weights=bool(payload.use_adaptive_weights),
            )
            event = _event_from_result(
                source="backtest_apply",
                focus_number=focus,
                from_index=idx,
                history=normalized_history,
                result=result,
                max_attempts=max(1, min(100, int(payload.max_attempts))),
            )
            events.append(event)

        summary = pattern_telemetry.summarize_events(events)
        pattern_rows = summary.get("patterns", []) if isinstance(summary, dict) else []
        by_pattern = {str(row.get("pattern_id")): row for row in pattern_rows if isinstance(row, dict)}
        definition_files = _load_pattern_definition_files()
        updated: List[Dict] = []
        skipped: List[Dict] = []
        blend = max(0.0, min(1.0, float(payload.blend)))
        min_signals = max(1, int(payload.min_signals))

        for pattern_id, path in definition_files.items():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                skipped.append({"pattern_id": pattern_id, "reason": "definicao invalida"})
                continue

            row = by_pattern.get(pattern_id)
            if not row:
                skipped.append({"pattern_id": pattern_id, "reason": "sem metrica"})
                continue

            signals = int(row.get("signals", 0) or 0)
            if signals < min_signals:
                skipped.append({"pattern_id": pattern_id, "reason": f"amostra baixa ({signals}<{min_signals})"})
                continue

            if str(raw.get("kind", "positive")).lower() != "positive":
                skipped.append({"pattern_id": pattern_id, "reason": "padrao negativo nao ajustado"})
                continue

            if str(raw.get("id", "")) == "legacy_base_suggestion":
                skipped.append({"pattern_id": pattern_id, "reason": "legacy fixo"})
                continue

            old_weight = float(raw.get("weight", 1.0))
            rec_multiplier = float(row.get("recommended_multiplier", 1.0))
            applied_multiplier = (1.0 - blend) + (rec_multiplier * blend)
            new_weight = round(max(0.1, min(5.0, old_weight * applied_multiplier)), 4)

            updated_item = {
                "pattern_id": pattern_id,
                "signals": signals,
                "hit_rate": row.get("hit_rate", 0),
                "recommended_multiplier": rec_multiplier,
                "old_weight": old_weight,
                "new_weight": new_weight,
            }
            updated.append(updated_item)

            if not payload.dry_run:
                raw["weight"] = new_weight
                params = raw.get("params", {})
                if not isinstance(params, dict):
                    params = {}
                params["last_auto_tune"] = {
                    "signals": signals,
                    "hit_rate": row.get("hit_rate", 0),
                    "recommended_multiplier": rec_multiplier,
                    "applied_multiplier": round(applied_multiplier, 4),
                }
                raw["params"] = params
                path.write_text(json.dumps(raw, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

        return {
            "engine_version": "v1",
            "available": True,
            "dry_run": bool(payload.dry_run),
            "updated": updated,
            "skipped": skipped,
            "summary": summary,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/patterns/metrics/auto-tune")
async def auto_tune_patterns(payload: AutoTuneRequest):
    """
    Endpoint simplificado para auto-tuning dos padroes.
    Ideal para ser chamado via cronjob com dados historicos.

    Exemplo de uso com curl:
    curl -X POST http://localhost:8000/api/patterns/metrics/auto-tune \
      -H "Content-Type: application/json" \
      -d '{"history": [1,2,3,...], "dry_run": false}'
    """
    try:
        normalized_history = [int(n) for n in payload.history if 0 <= int(n) <= 36]
        min_size = max(100, int(payload.min_history_size))

        if len(normalized_history) < min_size:
            return {
                "engine_version": "v1",
                "available": False,
                "message": f"Historico insuficiente. Minimo: {min_size}, recebido: {len(normalized_history)}",
                "updated": [],
                "skipped": [],
            }

        # Executa backtest
        events: List[Dict] = []
        limit = min(len(normalized_history), 500)
        for idx in range(1, limit):
            focus = normalized_history[idx]
            result = pattern_engine.evaluate(
                history=normalized_history,
                base_suggestion=[],
                focus_number=focus,
                from_index=idx,
                max_numbers=18,
                use_adaptive_weights=False,
            )
            event = _event_from_result(
                source="auto_tune",
                focus_number=focus,
                from_index=idx,
                history=normalized_history,
                result=result,
                max_attempts=12,
            )
            events.append(event)

        summary = pattern_telemetry.summarize_events(events)
        pattern_rows = summary.get("patterns", []) if isinstance(summary, dict) else []
        by_pattern = {str(row.get("pattern_id")): row for row in pattern_rows if isinstance(row, dict)}
        definition_files = _load_pattern_definition_files()
        updated: List[Dict] = []
        skipped: List[Dict] = []

        for pattern_id, path in definition_files.items():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                skipped.append({"pattern_id": pattern_id, "reason": "definicao invalida"})
                continue

            row = by_pattern.get(pattern_id)
            if not row:
                skipped.append({"pattern_id": pattern_id, "reason": "sem metrica"})
                continue

            signals = int(row.get("signals", 0) or 0)
            if signals < 20:
                skipped.append({"pattern_id": pattern_id, "reason": f"amostra baixa ({signals}<20)"})
                continue

            if str(raw.get("kind", "positive")).lower() != "positive":
                skipped.append({"pattern_id": pattern_id, "reason": "padrao negativo"})
                continue

            if str(raw.get("id", "")) == "legacy_base_suggestion":
                skipped.append({"pattern_id": pattern_id, "reason": "legacy fixo"})
                continue

            old_weight = float(raw.get("weight", 1.0))
            rec_multiplier = float(row.get("recommended_multiplier", 1.0))
            applied_multiplier = 0.3 + (rec_multiplier * 0.7)  # blend fixo de 0.7
            new_weight = round(max(0.1, min(5.0, old_weight * applied_multiplier)), 4)

            updated_item = {
                "pattern_id": pattern_id,
                "signals": signals,
                "hit_rate": row.get("hit_rate", 0),
                "old_weight": old_weight,
                "new_weight": new_weight,
            }
            updated.append(updated_item)

            if not payload.dry_run:
                raw["weight"] = new_weight
                params = raw.get("params", {})
                if not isinstance(params, dict):
                    params = {}
                params["last_auto_tune"] = {
                    "signals": signals,
                    "hit_rate": row.get("hit_rate", 0),
                    "recommended_multiplier": rec_multiplier,
                }
                raw["params"] = params
                path.write_text(json.dumps(raw, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

        total_events = len(events)
        total_hits = sum(1 for e in events if e.get("progress", {}).get("status") == "hit")
        overall_hit_rate = round(total_hits / total_events, 4) if total_events > 0 else 0

        return {
            "engine_version": "v1",
            "available": True,
            "dry_run": bool(payload.dry_run),
            "history_size": len(normalized_history),
            "events_analyzed": total_events,
            "overall_hit_rate": overall_hit_rate,
            "updated": updated,
            "skipped": skipped,
            "message": "Auto-tune executado com sucesso." if not payload.dry_run else "Dry-run: nenhuma alteracao aplicada.",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/patterns/final-suggestion")
async def get_final_suggestion(payload: FinalSuggestionRequest):
    """
    Retorna a sugestao final fundida (base + otimizada) para um unico numero.

    IMPORTANTE: Esta implementacao replica EXATAMENTE a logica do frontend (api.html)
    para garantir que os resultados sejam identicos.

    Fluxo:
    1. Calcula sugestao base (pulled numbers + padroes dominantes)
    2. Calcula sugestao otimizada (PatternEngine)
    3. Faz fusao usando o mesmo algoritmo do frontend buildFinalSuggestion()
    """
    try:
        return await _compute_final_suggestion(payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/patterns/final-suggestion/policy")
async def get_final_suggestion_policy(payload: FinalSuggestionPolicyRequest):
    try:
        suggestion_payload = FinalSuggestionRequest(
            history=payload.history,
            focus_number=payload.focus_number,
            from_index=payload.from_index,
            max_numbers=payload.max_numbers,
            optimized_max_numbers=payload.optimized_max_numbers,
            base_weight=payload.base_weight,
            optimized_weight=payload.optimized_weight,
            runtime_overrides=payload.runtime_overrides,
            siege_window=payload.siege_window,
            siege_min_occurrences=payload.siege_min_occurrences,
            siege_min_streak=payload.siege_min_streak,
            siege_veto_relief=payload.siege_veto_relief,
            block_bets_enabled=payload.block_bets_enabled,
            inversion_enabled=payload.inversion_enabled,
            inversion_context_window=payload.inversion_context_window,
            inversion_penalty_factor=payload.inversion_penalty_factor,
            weight_profile_id=payload.weight_profile_id,
        )
        result = await _compute_final_suggestion(suggestion_payload)
        candidate_list = [int(n) for n in (result.get("suggestion") or []) if 0 <= int(n) <= 36]
        candidate_confidence = int(result.get("confidence", {}).get("score", 0) or 0)
        candidate_policy_score = candidate_confidence - (len(candidate_list) * 1.5)
        if bool(result.get("breakdown", {}).get("block_compaction_applied")):
            candidate_policy_score += 3.0

        live_decision = final_suggestion_entry_intelligence.recommend(
            active_signal=(
                payload.active_signal.model_dump()
                if (payload.active_signal and hasattr(payload.active_signal, "model_dump"))
                else payload.active_signal.dict()
                if payload.active_signal
                else None
            ),
            candidate_signal={
                "suggestion": candidate_list,
                "confidence_score": candidate_confidence,
                "suggestion_size": len(candidate_list),
                "policy_score": candidate_policy_score,
                "block_compaction_applied": bool(result.get("breakdown", {}).get("block_compaction_applied")),
            },
            history=payload.history,
        )
        return {
            "available": bool(result.get("available", False)),
            "decision": live_decision,
            "candidate_signal": {
                "focus_number": int(result.get("focus_number", payload.focus_number or 0) or 0),
                "suggestion": candidate_list,
                "confidence": result.get("confidence", {"score": 0, "label": "Baixa"}),
                "confidence_v2_score": int(
                    result.get("optimized_payload", {}).get("confidence_breakdown", {}).get("calibrated_confidence_v2", 0)
                    or result.get("optimized_breakdown", {}).get("calibrated_confidence_v2", 0)
                    or 0
                ),
                "suggestion_size": len(candidate_list),
                "policy_score": round(float(candidate_policy_score), 4),
                "block_compaction_applied": bool(result.get("breakdown", {}).get("block_compaction_applied")),
                "block_bets_enabled": bool(result.get("blockBetsEnabled", payload.block_bets_enabled)),
            },
            "result": result,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ============================================================================
# Correlation Matrix Endpoints
# ============================================================================

@router.get("/api/patterns/correlation-matrix")
async def get_correlation_matrix():
    """
    Retorna a matriz de correlacao entre padroes.
    Mostra quais padroes funcionam bem juntos.
    """
    try:
        return correlation_matrix.get_matrix_summary()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/patterns/correlation/{pattern_id}/partners")
async def get_pattern_partners(pattern_id: str, top_n: int = 5):
    """
    Retorna os padroes com melhor correlacao com o padrao especificado.
    """
    try:
        partners = correlation_matrix.get_best_partners(pattern_id, top_n=max(1, min(20, top_n)))
        return {
            "pattern_id": pattern_id,
            "partners": partners,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/patterns/correlation/clear")
async def clear_correlation_matrix():
    """Limpa a matriz de correlacao."""
    try:
        correlation_matrix.clear()
        return {"cleared": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ============================================================================
# Backtesting Endpoints
# ============================================================================

class FullBacktestRequest(BaseModel):
    history: List[int] = Field(default_factory=list)
    gale_levels: List[int] = Field(default=[1, 2, 3, 5, 12])
    max_entries: int = 500
    min_confidence: int = 0


@router.post("/api/patterns/backtest/full")
async def run_full_backtest(payload: FullBacktestRequest):
    """
    Executa backtest completo com breakdown por nivel de gale.
    """
    try:
        normalized_history = [int(n) for n in payload.history if 0 <= int(n) <= 36]
        if len(normalized_history) < 15:
            return {
                "available": False,
                "error": "Historico insuficiente (minimo 15 numeros)",
            }

        result = backtest_engine.run_backtest(
            history=normalized_history,
            pattern_engine=pattern_engine,
            gale_levels=payload.gale_levels,
            max_entries=max(10, min(1000, payload.max_entries)),
            min_confidence=max(0, min(100, payload.min_confidence)),
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/patterns/backtest/report/{pattern_id}")
async def get_pattern_backtest_report(pattern_id: str):
    """
    Retorna relatorio detalhado de backtest para um padrao especifico.
    """
    try:
        return backtest_engine.get_pattern_report(pattern_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ============================================================================
# Suggestion Filter Endpoints
# ============================================================================

@router.get("/api/patterns/filters/config")
async def get_filter_config():
    """Retorna configuracao atual dos filtros de qualidade."""
    try:
        return suggestion_filter.get_filter_config()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


class UpdateFilterRequest(BaseModel):
    filter_name: str
    enabled: Optional[bool] = None
    threshold: Optional[float] = None


@router.post("/api/patterns/filters/update")
async def update_filter(payload: UpdateFilterRequest):
    """Atualiza configuracao de um filtro especifico."""
    try:
        return suggestion_filter.update_filter(
            filter_name=payload.filter_name,
            enabled=payload.enabled,
            threshold=payload.threshold,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/patterns/filters/disable-all")
async def disable_all_filters():
    """Desabilita todos os filtros."""
    try:
        suggestion_filter.disable_all()
        return {"disabled": True, "config": suggestion_filter.get_filter_config()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/patterns/filters/enable-all")
async def enable_all_filters():
    """Habilita todos os filtros."""
    try:
        suggestion_filter.enable_all()
        return {"enabled": True, "config": suggestion_filter.get_filter_config()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/patterns/filters/reset")
async def reset_filters():
    """Restaura filtros para valores padrao."""
    try:
        suggestion_filter.reset_to_defaults()
        return {"reset": True, "config": suggestion_filter.get_filter_config()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ============================================================================
# Pattern Decay Endpoints
# ============================================================================

@router.get("/api/patterns/decay/status")
async def get_decay_status():
    """Retorna estado atual de decay de todos os padroes."""
    try:
        return pattern_decay.get_decay_report()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/patterns/decay/{pattern_id}")
async def get_pattern_decay_state(pattern_id: str):
    """Retorna estado de decay de um padrao especifico."""
    try:
        return pattern_decay.get_pattern_state(pattern_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/patterns/decay/reset/{pattern_id}")
async def reset_pattern_decay(pattern_id: str):
    """Reset manual do decay de um padrao."""
    try:
        return pattern_decay.reset_pattern(pattern_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/patterns/decay/reset-all")
async def reset_all_decay():
    """Reset de decay de todos os padroes."""
    try:
        return pattern_decay.reset_all()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


class DecayConfigRequest(BaseModel):
    decay_start_misses: Optional[int] = None
    decay_per_miss: Optional[float] = None
    max_decay: Optional[float] = None
    disable_threshold: Optional[int] = None
    recovery_hits_needed: Optional[int] = None
    recovery_per_hit: Optional[float] = None


@router.post("/api/patterns/decay/configure")
async def configure_decay(payload: DecayConfigRequest):
    """Atualiza configuracao do sistema de decay."""
    try:
        return pattern_decay.configure(
            decay_start_misses=payload.decay_start_misses,
            decay_per_miss=payload.decay_per_miss,
            max_decay=payload.max_decay,
            disable_threshold=payload.disable_threshold,
            recovery_hits_needed=payload.recovery_hits_needed,
            recovery_per_hit=payload.recovery_per_hit,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/patterns/decay/disabled")
async def get_disabled_patterns():
    """Retorna lista de padroes desabilitados por decay."""
    try:
        disabled = pattern_decay.get_disabled_patterns()
        return {
            "disabled_count": len(disabled),
            "pattern_ids": disabled,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ============================================================================
# Training Endpoint
# ============================================================================

class RecordResultRequest(BaseModel):
    active_patterns: List[str]
    hit: bool
    suggested_numbers: List[int] = Field(default_factory=list)
    actual_number: Optional[int] = None


@router.post("/api/patterns/record-result")
async def record_signal_result(payload: RecordResultRequest):
    """
    Registra resultado de um sinal para atualizar correlacao e decay.
    Usado para treinar o sistema com dados historicos.
    """
    try:
        pattern_engine.record_signal_result(
            active_patterns=payload.active_patterns,
            hit=payload.hit,
            suggested_numbers=payload.suggested_numbers,
            actual_number=payload.actual_number,
        )
        return {
            "recorded": True,
            "hit": payload.hit,
            "patterns_count": len(payload.active_patterns),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


class TrainFromHistoryRequest(BaseModel):
    history: List[int] = Field(default_factory=list)
    max_entries: int = 500
    max_attempts: int = 3
    max_numbers: int = 12
    clear_previous: bool = True


@router.post("/api/patterns/train")
async def train_from_history(payload: TrainFromHistoryRequest):
    """
    Treina o sistema com dados historicos.
    Processa o historico e registra hits/misses para correlacao e decay.
    """
    try:
        history = [int(n) for n in payload.history if 0 <= int(n) <= 36]

        if len(history) < 50:
            return {
                "success": False,
                "error": "Historico muito curto (minimo 50 numeros)",
            }

        # Limpar dados anteriores se solicitado
        if payload.clear_previous:
            correlation_matrix.clear()
            pattern_decay.reset_all()

        hits = 0
        misses = 0
        total = 0

        limit = min(payload.max_entries, len(history) - 50)

        for i in range(50, 50 + limit):
            result = pattern_engine.evaluate(
                history=history,
                from_index=i,
                max_numbers=payload.max_numbers,
                use_adaptive_weights=False,
            )

            if not result.get('available'):
                continue

            suggestion = set(result.get('suggestion', []))
            active_patterns = [
                c.get('pattern_id')
                for c in result.get('contributions', [])
                if c.get('pattern_id')
            ]

            if not active_patterns or len(active_patterns) < 2:
                continue

            # Verificar hit
            hit = False
            hit_number = None
            for step in range(1, payload.max_attempts + 1):
                if i - step >= 0:
                    actual = history[i - step]
                    if actual in suggestion:
                        hit = True
                        hit_number = actual
                        break

            # Registrar resultado
            pattern_engine.record_signal_result(
                active_patterns=active_patterns,
                hit=hit,
                suggested_numbers=list(suggestion),
                actual_number=hit_number,
            )

            total += 1
            if hit:
                hits += 1
            else:
                misses += 1

        # Salvar dados
        correlation_matrix.save()
        pattern_decay.save()

        hit_rate = (hits / total * 100) if total > 0 else 0

        return {
            "success": True,
            "total_signals": total,
            "hits": hits,
            "misses": misses,
            "hit_rate": round(hit_rate, 2),
            "correlation_pairs": len(correlation_matrix._matrix),
            "decay_patterns": len(pattern_decay._states),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
