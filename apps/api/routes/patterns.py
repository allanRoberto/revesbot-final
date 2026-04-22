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
from api.services.pattern_score_training_service import pattern_score_training_service
from api.services.pattern_weight_profiles import pattern_weight_profiles
from api.services.final_suggestion_signal_policy import final_suggestion_signal_policy
from api.services.final_suggestion_entry_intelligence import final_suggestion_entry_intelligence
from api.services.final_suggestion_protection import build_protected_coverage_suggestion
from api.services.simple_suggestion_entry_shadow import simple_suggestion_entry_shadow
from api.patterns.final_suggestion import (
    _compact_final_list_into_blocks,
    analyze_wheel_temperature,
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
    weight_profile_weights: Dict[str, float] = Field(default_factory=dict)
    entry_policy_enabled: bool = True
    entry_policy_overlap_window: int = 3
    entry_policy_high_confidence_cutoff: int = 60
    final_gate_require_optimized: bool = True
    final_gate_use_confidence_v2: bool = True
    final_gate_min_confidence: int = 40
    protected_mode_enabled: bool = False
    protected_suggestion_size: int = 35
    protected_recent_anchor_count: int = 3
    protected_swap_enabled: bool = False
    cold_count: int = 18


class ActiveSignalRequest(BaseModel):
    suggestion: List[int] = Field(default_factory=list)
    confidence_score: int = 0
    suggestion_size: int = 0
    policy_score: float | None = None
    block_compaction_applied: bool = False
    protected_mode_enabled: bool = False
    protected_suggestion_size: int | None = None
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
    weight_profile_weights: Dict[str, float] = Field(default_factory=dict)
    entry_policy_enabled: bool = True
    entry_policy_overlap_window: int = 3
    entry_policy_high_confidence_cutoff: int = 60
    final_gate_require_optimized: bool = True
    final_gate_use_confidence_v2: bool = True
    final_gate_min_confidence: int = 40
    protected_mode_enabled: bool = False
    protected_suggestion_size: int = 35
    protected_recent_anchor_count: int = 3
    protected_swap_enabled: bool = False
    cold_count: int = 18
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


class PatternScoreTrainingRunRequest(BaseModel):
    roulette_id: str
    history_limit: int = 1000
    max_attempts: int = 3
    timeline_window: int = 80


class PatternScoreTrainingSaveRequest(BaseModel):
    job_id: str
    name: str


def _event_from_result(
    *,
    source: str,
    roulette_id: str | None,
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
        "roulette_id": str(roulette_id or "").strip() or None,
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


@router.post("/api/patterns/score-training/run")
async def run_pattern_score_training(payload: PatternScoreTrainingRunRequest):
    try:
        roulette_id = str(payload.roulette_id or "").strip()
        if not roulette_id:
            raise HTTPException(status_code=400, detail="roulette_id obrigatorio")

        history_limit = max(50, min(50000, int(payload.history_limit)))
        max_attempts = max(1, min(3, int(payload.max_attempts)))
        timeline_window = max(10, min(200, int(payload.timeline_window)))
        history = await _load_history_for_training(roulette_id, history_limit)
        job = pattern_training_jobs.create_job(
            params={
                "mode": "score-training",
                "roulette_id": roulette_id,
                "history_limit": history_limit,
                "max_attempts": max_attempts,
                "timeline_window": timeline_window,
            }
        )

        def _worker() -> Dict[str, Any]:
            return pattern_score_training_service.run_training(
                roulette_id=roulette_id,
                history=history,
                history_limit=history_limit,
                max_attempts=max_attempts,
                timeline_window=timeline_window,
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


@router.get("/api/patterns/score-training/jobs/{job_id}")
async def get_pattern_score_training_job(job_id: str):
    try:
        job = pattern_training_jobs.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Treino nao encontrado")
        return job
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/patterns/score-training/save")
async def save_pattern_score_training(payload: PatternScoreTrainingSaveRequest):
    try:
        job_id = str(payload.job_id or "").strip()
        if not job_id:
            raise HTTPException(status_code=400, detail="job_id obrigatorio")

        job = pattern_training_jobs.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Treino nao encontrado")
        if str(job.get("status", "")).lower() != "completed":
            raise HTTPException(status_code=400, detail="Treino ainda nao foi concluido")

        result = job.get("result", {})
        if not isinstance(result, dict) or not bool(result.get("available", False)):
            raise HTTPException(status_code=400, detail="Treino sem resultado valido para salvar")

        profile_material = pattern_score_training_service.build_profile_material(result=result)
        profile_config = {
            **dict(result.get("config", {}) or {}),
            **dict(profile_material.get("config", {}) or {}),
        }
        profile_summary = {
            **dict(result.get("summary", {}) or {}),
            "training_mode": "score-training",
            "score_mode": "size_adjusted",
        }
        profile = pattern_weight_profiles.save_profile(
            name=str(payload.name or "").strip() or "score-training",
            roulette_id=str(result.get("roulette_id", "") or ""),
            history_size=max(
                0,
                int(
                    result.get("config", {}).get("history_size", 0)
                    or result.get("summary", {}).get("history_size", 0)
                    or 0
                ),
            ),
            max_attempts=max(1, int(result.get("config", {}).get("max_attempts", 3) or 3)),
            optimized_max_numbers=37,
            use_adaptive_weights=False,
            config=profile_config,
            summary=profile_summary,
            patterns=list(profile_material.get("patterns", []) or []),
            weights={str(k): float(v) for k, v in dict(profile_material.get("weights", {}) or {}).items()},
            effective_weights={
                str(k): float(v)
                for k, v in dict(profile_material.get("effective_weights", {}) or {}).items()
            },
        )
        return {
            "saved": True,
            "profile": {
                "id": profile.get("id"),
                "name": profile.get("name"),
            },
        }
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


def _merge_effective_profile_weights(
    *,
    saved_profile_weights: Dict[str, float] | None,
    runtime_profile_weights: Dict[str, float] | None,
) -> Dict[str, float]:
    normalized_saved = {
        str(pattern_id).strip(): float(weight)
        for pattern_id, weight in dict(saved_profile_weights or {}).items()
        if str(pattern_id).strip()
    }
    normalized_runtime = {
        str(pattern_id).strip(): float(weight)
        for pattern_id, weight in dict(runtime_profile_weights or {}).items()
        if str(pattern_id).strip()
    }
    if not normalized_saved and not normalized_runtime:
        return {}

    merged: Dict[str, float] = {}
    all_pattern_ids = set(normalized_saved) | set(normalized_runtime)
    for pattern_id in all_pattern_ids:
        merged[pattern_id] = round(
            float(normalized_saved.get(pattern_id, 1.0)) * float(normalized_runtime.get(pattern_id, 1.0)),
            6,
        )
    return merged


def _build_simple_suggestion_from_contributions(
    contributions: Any,
    *,
    focus_number: int,
    from_index: int,
    max_numbers: int,
    block_bets_enabled: bool = False,
    pulled_counts: Dict[int, int] | None = None,
    weight_profile_id: str | None = None,
    weight_profile_weights: Dict[str, float] | None = None,
    known_pattern_ids: List[str] | None = None,
) -> Dict[str, Any]:
    def _canonical_pattern_id(raw_pattern_id: str) -> str:
        raw = str(raw_pattern_id or "").strip()
        if not raw:
            return ""
        if raw in safe_known_pattern_ids:
            return raw
        matches = [pid for pid in safe_known_pattern_ids if raw.startswith(f"{pid}_")]
        if not matches:
            return raw
        matches.sort(key=len, reverse=True)
        return matches[0]

    safe_max_numbers = max(1, min(37, int(max_numbers)))
    safe_block_bets_enabled = bool(block_bets_enabled)
    safe_pulled_counts = {
        int(k): int(v)
        for k, v in dict(pulled_counts or {}).items()
        if 0 <= int(k) <= 36
    }
    safe_profile_id = str(weight_profile_id or "").strip() or None
    safe_profile_weights = {
        str(k): float(v)
        for k, v in dict(weight_profile_weights or {}).items()
        if str(k).strip()
    }
    weighted_ranking_applied = bool(safe_profile_weights)
    safe_known_pattern_ids = [str(pid).strip() for pid in (known_pattern_ids or []) if str(pid).strip()]
    normalized_contributions: List[Dict[str, Any]] = []
    supports_by_number: Dict[int, Dict[str, Dict[str, Any]]] = defaultdict(dict)

    if isinstance(contributions, list):
        for item in contributions:
            if not isinstance(item, dict):
                continue
            pattern_id = str(item.get("pattern_id", "") or "").strip() or "unknown_pattern"
            base_pattern_id = _canonical_pattern_id(pattern_id)
            pattern_name = str(item.get("pattern_name", "") or "").strip() or pattern_id
            applied_weight = float(safe_profile_weights.get(base_pattern_id, 1.0))
            unique_numbers: List[int] = []
            seen_numbers: set[int] = set()
            for raw_number in item.get("numbers", []) or []:
                try:
                    number = int(raw_number)
                except (TypeError, ValueError):
                    continue
                if not (0 <= number <= 36):
                    continue
                if number in seen_numbers:
                    continue
                seen_numbers.add(number)
                unique_numbers.append(number)
                supports_by_number[number][pattern_id] = {
                    "pattern_id": pattern_id,
                    "base_pattern_id": base_pattern_id or pattern_id,
                    "pattern_name": pattern_name,
                    "applied_weight": round(applied_weight, 6),
                }
            if not unique_numbers:
                continue
            normalized_contributions.append(
                {
                    "pattern_id": pattern_id,
                    "base_pattern_id": base_pattern_id or pattern_id,
                    "pattern_name": pattern_name,
                    "applied_weight": round(applied_weight, 6),
                    "numbers": unique_numbers,
                }
            )

    number_details = [
        {
            "number": int(number),
            "support_score": len(patterns_by_id),
            "support_count": len(patterns_by_id),
            "weighted_support_score": round(
                sum(float(item.get("applied_weight", 1.0) or 1.0) for item in patterns_by_id.values()),
                6,
            ),
            "supporting_patterns": sorted(
                patterns_by_id.values(),
                key=lambda item: (str(item.get("pattern_name", "")), str(item.get("pattern_id", ""))),
            ),
        }
        for number, patterns_by_id in supports_by_number.items()
    ]
    number_details.sort(
        key=lambda item: (
            -float(item.get("weighted_support_score", 0.0) or 0.0),
            -int(item["support_score"]),
            int(item["number"]),
        )
    )
    selected_number_details = list(number_details[:safe_max_numbers])
    ranked_list = [int(item["number"]) for item in selected_number_details]
    score_map = {
        int(item["number"]): round(
            float(item.get("weighted_support_score", 0.0) or 0.0)
            + (float(item.get("support_score", 0) or 0) * 0.001),
            6,
        )
        for item in number_details
    }
    block_compaction = {
        "list": list(ranked_list),
        "added": [],
        "removed": [],
        "changed": False,
    }
    if safe_block_bets_enabled and len(ranked_list) > 1:
        block_compaction = _compact_final_list_into_blocks(
            initial_list=ranked_list,
            score_map=dict(score_map),
            pulled_counts=safe_pulled_counts,
            target_size=safe_max_numbers,
        )
        ranked_list = [int(n) for n in block_compaction["list"][:safe_max_numbers]]
        number_details_map = {
            int(item["number"]): item
            for item in number_details
            if isinstance(item, dict) and isinstance(item.get("number"), int)
        }
        selected_number_details = [
            (
                number_details_map[number]
                if number in number_details_map
                else {
                    "number": int(number),
                    "support_score": 0,
                    "support_count": 0,
                    "weighted_support_score": 0.0,
                    "supporting_patterns": [],
                    "added_by_block_compaction": True,
                }
            )
            for number in ranked_list
        ]
    top_support_count = int(selected_number_details[0]["support_score"]) if selected_number_details else 0
    min_support_count = int(selected_number_details[-1]["support_score"]) if selected_number_details else 0
    avg_support_count = (
        round(
            sum(int(item["support_score"]) for item in selected_number_details) / len(selected_number_details),
            2,
        )
        if selected_number_details
        else 0.0
    )
    top_weighted_support_score = (
        round(float(selected_number_details[0].get("weighted_support_score", 0.0) or 0.0), 6)
        if selected_number_details
        else 0.0
    )
    min_weighted_support_score = (
        round(float(selected_number_details[-1].get("weighted_support_score", 0.0) or 0.0), 6)
        if selected_number_details
        else 0.0
    )
    avg_weighted_support_score = (
        round(
            sum(float(item.get("weighted_support_score", 0.0) or 0.0) for item in selected_number_details)
            / len(selected_number_details),
            6,
        )
        if selected_number_details
        else 0.0
    )

    if not ranked_list:
        return {
            "available": False,
            "list": [],
            "suggestion": [],
            "ordered_suggestion": [],
            "focus_number": int(focus_number),
            "from_index": int(from_index),
            "max_numbers": safe_max_numbers,
            "pattern_count": len(normalized_contributions),
            "unique_numbers": 0,
            "number_details": [],
            "selected_number_details": [],
            "top_support_count": 0,
            "min_support_count": 0,
            "avg_support_count": 0.0,
            "top_weighted_support_score": 0.0,
            "min_weighted_support_score": 0.0,
            "avg_weighted_support_score": 0.0,
            "contributions": normalized_contributions,
            "explanation": "Nenhum pattern positivo retornou números para a sugestão simples.",
            "weight_profile": {
                "id": safe_profile_id,
                "weighted_ranking": weighted_ranking_applied,
            } if (safe_profile_id or weighted_ranking_applied) else None,
            "block_bets_enabled": safe_block_bets_enabled,
            "block_compaction": block_compaction,
            "block_compaction_applied": False,
            "block_numbers_added": 0,
            "block_numbers_removed": 0,
            "ranking_locked": True,
        }

    explanation = (
        (
            f"Sugestão simples ponderada por profile: "
            if safe_profile_id
            else (f"Sugestão simples ponderada por pesos dinâmicos: " if weighted_ranking_applied else f"Sugestão simples por contagem de apoio: ")
        )
        + f"{len(normalized_contributions)} pattern(s) positivos e {len(number_details)} número(s) únicos citados."
    )
    if safe_block_bets_enabled and bool(block_compaction["changed"]):
        explanation = (
            f"{explanation} Compactação em blocos aplicada "
            f"(+{len(block_compaction['added'])}/-{len(block_compaction['removed'])})."
        )

    return {
        "available": True,
        "list": ranked_list,
        "suggestion": ranked_list,
        "ordered_suggestion": list(ranked_list),
        "focus_number": int(focus_number),
        "from_index": int(from_index),
        "max_numbers": safe_max_numbers,
        "pattern_count": len(normalized_contributions),
        "unique_numbers": len(number_details),
        "number_details": number_details,
        "selected_number_details": selected_number_details,
        "top_support_count": top_support_count,
        "min_support_count": min_support_count,
        "avg_support_count": avg_support_count,
        "top_weighted_support_score": top_weighted_support_score,
        "min_weighted_support_score": min_weighted_support_score,
        "avg_weighted_support_score": avg_weighted_support_score,
        "contributions": normalized_contributions,
        "explanation": explanation,
        "weight_profile": {
            "id": safe_profile_id,
            "weighted_ranking": weighted_ranking_applied,
        } if (safe_profile_id or weighted_ranking_applied) else None,
        "block_bets_enabled": safe_block_bets_enabled,
        "block_compaction": block_compaction,
        "block_compaction_applied": bool(block_compaction["changed"]),
        "block_numbers_added": len(block_compaction["added"]),
        "block_numbers_removed": len(block_compaction["removed"]),
        "ranking_locked": True,
    }


def _build_protected_policy_decision(
    result: Dict[str, Any],
    *,
    candidate_list: List[int],
    candidate_confidence: int,
    candidate_policy_score: float,
) -> Dict[str, Any]:
    excluded_numbers = [
        int(n) for n in (result.get("protected_excluded_numbers") or []) if 0 <= int(n) <= 36
    ]
    excluded_label = ", ".join(str(number) for number in excluded_numbers) or "n/a"
    wait_triggered = bool(result.get("protected_wait_triggered", False))
    recommended_wait_spins = max(
        0,
        int(result.get("protected_wait_recommended_spins", 0) or 0),
    )
    wait_reason = str(result.get("protected_wait_reason", "") or "").strip()
    swap_applied = bool(result.get("protected_swap_applied", False))
    swap_summary = str(result.get("protected_swap_summary", "") or "").strip()
    base_reason = f"Cobertura protegida ativa. Fora da jogada: {excluded_label}."
    has_candidate = bool(candidate_list)
    action = "enter" if has_candidate else "wait"
    label = "Cobertura protegida" if has_candidate else "Esperar"
    reason = base_reason if has_candidate else "Sem sugestão candidata válida para cobertura protegida."
    wait_spins = 0
    touch_exact = 0
    touch_near = 0

    if has_candidate and wait_triggered and recommended_wait_spins > 0:
        action = "wait"
        label = "Proteção 35 números"
        reason = wait_reason or f"Zona protegida tocada. Aguarde {recommended_wait_spins} giros."
        wait_spins = recommended_wait_spins
        touch_exact = 1
        touch_near = 1
    elif has_candidate and swap_applied:
        label = "Aposta salva"
        reason = swap_summary or f"Aposta salva por troca dos frios excluidos. Fora da jogada: {excluded_label}."

    return {
        "action": action,
        "label": label,
        "reason": reason,
        "score": round(float(candidate_policy_score), 4),
        "score_delta": round(float(candidate_policy_score), 4),
        "confidence_delta": int(candidate_confidence),
        "overlap_ratio": 0.0,
        "saved_steps_estimate": 0,
        "recommended_wait_spins": wait_spins,
        "entry_overlap_unique": 0,
        "entry_overlap_hits": 0,
        "entry_overlap_group": "0",
        "entry_confidence_segment": "protected",
        "touch_exact": touch_exact,
        "touch_near": touch_near,
        "touch_close": 0,
        "last_distance": 99,
        "recent_regions": [],
        "alternating_regions": False,
        "region_alignment": 0.0,
        "relation_score": 0.0,
        "wait_spins": 0,
        "max_wait_allowed": wait_spins,
        "decay_penalty": 0.0,
        "alert_mode": False,
        "rescue_mode": False,
        "protected_wait": action == "wait",
        "protected_mode_enabled": True,
        "protected_excluded_numbers": excluded_numbers,
        "protected_swap_applied": swap_applied,
        "protected_swap_summary": swap_summary,
    }


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
        simple_payload: Dict[str, Any] = {
            "available": False,
            "list": [],
            "suggestion": [],
            "ordered_suggestion": [],
            "focus_number": None,
            "from_index": 0,
            "max_numbers": max(1, min(37, int(payload.max_numbers))),
            "pattern_count": 0,
            "unique_numbers": 0,
            "number_details": [],
            "selected_number_details": [],
            "top_support_count": 0,
            "min_support_count": 0,
            "avg_support_count": 0.0,
            "top_weighted_support_score": 0.0,
            "min_weighted_support_score": 0.0,
            "avg_weighted_support_score": 0.0,
            "contributions": [],
            "explanation": "Historico insuficiente para avaliacao simples.",
            "weight_profile": None,
            "block_bets_enabled": bool(payload.block_bets_enabled),
            "block_compaction": {"list": [], "added": [], "removed": [], "changed": False},
            "block_compaction_applied": False,
            "block_numbers_added": 0,
            "block_numbers_removed": 0,
            "ranking_locked": True,
            "entry_shadow": simple_suggestion_entry_shadow.unavailable(
                "Historico insuficiente para avaliacao simples.",
                suggestion_size=0,
            ),
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
            "simple_payload": simple_payload,
            "simple_suggestion": [],
            "simple_available": False,
            "simple_explanation": simple_payload["explanation"],
            "simple_number_details": [],
            "simple_pattern_count": 0,
            "simple_unique_numbers": 0,
            "simple_entry_shadow": simple_payload["entry_shadow"],
        }

    from_index = max(0, min(int(payload.from_index), len(normalized_history) - 1))
    focus_number = payload.focus_number
    if focus_number is None:
        focus_number = normalized_history[from_index]
    if not (0 <= int(focus_number) <= 36):
        focus_number = normalized_history[from_index]
    focus_number = int(focus_number)

    target_size = max(1, min(37, int(payload.max_numbers)))
    protected_mode_enabled = bool(payload.protected_mode_enabled)
    protected_suggestion_size = max(26, min(35, int(payload.protected_suggestion_size)))
    if protected_mode_enabled:
        protected_suggestion_size = 35
    protected_recent_anchor_count = max(1, min(5, int(payload.protected_recent_anchor_count)))
    protected_swap_enabled = False
    cold_count = max(1, min(36, int(payload.cold_count)))
    effective_target_size = protected_suggestion_size if protected_mode_enabled else target_size
    optimized_max_numbers = max(1, min(37, int(payload.optimized_max_numbers)))
    final_base_weight, final_optimized_weight = normalize_weights(payload.base_weight, payload.optimized_weight)

    siege_window = max(2, min(20, int(payload.siege_window)))
    siege_min_occurrences = max(1, min(10, int(payload.siege_min_occurrences)))
    siege_min_streak = max(1, min(10, int(payload.siege_min_streak)))
    siege_veto_relief = max(0.0, min(1.0, float(payload.siege_veto_relief)))
    inversion_enabled = bool(payload.inversion_enabled)
    inversion_context_window = max(1, min(50, int(payload.inversion_context_window)))
    inversion_penalty_factor = max(0.0, min(1.0, float(payload.inversion_penalty_factor)))
    entry_policy_enabled = bool(payload.entry_policy_enabled)
    entry_policy_overlap_window = max(1, min(10, int(payload.entry_policy_overlap_window)))
    entry_policy_high_confidence_cutoff = max(0, min(100, int(payload.entry_policy_high_confidence_cutoff)))
    final_gate_require_optimized = bool(payload.final_gate_require_optimized)
    final_gate_use_confidence_v2 = bool(payload.final_gate_use_confidence_v2)
    final_gate_min_confidence = max(0, min(100, int(payload.final_gate_min_confidence)))

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
    saved_profile_weights = selected_profile.get("weights", {}) if isinstance(selected_profile, dict) else {}
    runtime_profile_weights = {
        str(pattern_id).strip(): float(weight)
        for pattern_id, weight in dict(payload.weight_profile_weights or {}).items()
        if str(pattern_id).strip()
    }
    effective_profile_weights = _merge_effective_profile_weights(
        saved_profile_weights=saved_profile_weights if isinstance(saved_profile_weights, dict) else {},
        runtime_profile_weights=runtime_profile_weights,
    )
    dynamic_weighting_meta = {
        "runtime_weight_count": len(runtime_profile_weights),
        "runtime_weights_applied": bool(runtime_profile_weights),
        "effective_weight_count": len(effective_profile_weights),
        "top_runtime_weights": [
            {"pattern_id": pattern_id, "weight": weight}
            for pattern_id, weight in sorted(
                runtime_profile_weights.items(),
                key=lambda item: (-abs(float(item[1]) - 1.0), -float(item[1]), item[0]),
            )[:12]
        ],
    }

    base_list_for_engine = sorted(base_list_ranked)
    optimized_result = pattern_engine.evaluate(
        history=normalized_history,
        base_suggestion=base_list_for_engine,
        focus_number=focus_number,
        from_index=from_index,
        max_numbers=optimized_max_numbers,
        runtime_overrides=runtime_overrides,
        weight_profile_id=selected_profile_id,
        weight_profile_weights=effective_profile_weights,
    )

    opt_list_sorted = _parse_optimized_suggestion_sorted(optimized_result)
    opt_confidence = int(optimized_result.get("confidence", {}).get("score", 0) or 0)
    opt_confidence_v2 = int(
        optimized_result.get("confidence_breakdown", {}).get("calibrated_confidence_v2", 0)
        or 0
    )
    opt_confidence_effective = opt_confidence_v2 if (final_gate_use_confidence_v2 and opt_confidence_v2 > 0) else opt_confidence
    opt_confidence_source = "confidence_v2_shadow" if (final_gate_use_confidence_v2 and opt_confidence_v2 > 0) else "optimized_confidence"
    number_details = optimized_result.get("number_details", [])
    opt_list_ranked = _build_ranked_optimized_list(number_details, opt_list_sorted)

    final_result = build_final_suggestion(
        base_list=base_list_ranked,
        optimized_list=opt_list_ranked,
        optimized_confidence=opt_confidence,
        optimized_confidence_effective=opt_confidence_effective,
        number_details=number_details if isinstance(number_details, list) else [],
        base_confidence_score=base_confidence_score,
        max_size=effective_target_size,
        history_arr=normalized_history,
        from_index=from_index,
        pulled_counts=pulled_counts,
        base_weight=final_base_weight,
        optimized_weight=final_optimized_weight,
        block_bets_enabled=bool(payload.block_bets_enabled),
        inversion_enabled=inversion_enabled,
        inversion_context_window=inversion_context_window,
        inversion_penalty_factor=inversion_penalty_factor,
        assertiveness_compaction_enabled=not protected_mode_enabled,
    )

    wheel_temperature = analyze_wheel_temperature(
        normalized_history,
        from_index=from_index,
        window=50,
        cold_count=cold_count,
    )
    cold_ranking = [int(n) for n in wheel_temperature.get("cold_ranking", []) if 0 <= int(n) <= 36]
    base_is_cold = focus_number in set(wheel_temperature.get("cold_numbers", set()))
    base_cold_rank = (cold_ranking.index(focus_number) + 1) if focus_number in cold_ranking else None

    candidate_list = list(final_result.get("list", []) if isinstance(final_result, dict) else [])
    candidate_protections = list(final_result.get("protections", []) if isinstance(final_result, dict) else [])
    candidate_confidence_obj = dict(final_result.get("confidence", {}) if isinstance(final_result, dict) else {})
    candidate_confidence_score = int(candidate_confidence_obj.get("score", 0) or 0)
    protection_result: Dict[str, Any] | None = None
    protected_excluded_numbers: List[int] = []
    protected_guard_numbers: List[int] = []
    protected_guard_details: Dict[str, Any] = {}
    protected_wait_triggered = False
    protected_wait_matches: List[Dict[str, Any]] = []
    protected_wait_recommended_spins = 0
    protected_wait_reason = ""
    protected_original_excluded_numbers: List[int] = []
    protected_swap_applied = False
    protected_swap_summary = ""
    protected_swap_details: List[Dict[str, Any]] = []
    cold_count_effective = cold_count
    if protected_mode_enabled:
        protection_result = build_protected_coverage_suggestion(
            history_arr=normalized_history,
            from_index=from_index,
            focus_number=focus_number,
            base_list=base_list_ranked,
            candidate_list=candidate_list,
            protections=candidate_protections,
            number_details=number_details if isinstance(number_details, list) else [],
            target_size=protected_suggestion_size,
            cold_count=cold_count,
            recent_anchor_count=protected_recent_anchor_count,
            protected_swap_enabled=protected_swap_enabled,
        )
        candidate_list = list(protection_result.get("ordered_suggestion", candidate_list))
        protected_excluded_numbers = [int(n) for n in protection_result.get("protected_excluded_numbers", []) if 0 <= int(n) <= 36]
        protected_original_excluded_numbers = [int(n) for n in protection_result.get("protected_original_excluded_numbers", []) if 0 <= int(n) <= 36]
        protected_guard_numbers = [int(n) for n in protection_result.get("protected_guard_numbers", []) if 0 <= int(n) <= 36]
        protected_guard_details = dict(protection_result.get("protected_guard_details", {}))
        protected_wait_triggered = bool(protection_result.get("protected_wait_triggered", False))
        protected_wait_matches = [
            item
            for item in protection_result.get("protected_wait_matches", [])
            if isinstance(item, dict)
        ]
        protected_wait_recommended_spins = int(protection_result.get("protected_wait_recommended_spins", 0) or 0)
        protected_wait_reason = str(protection_result.get("protected_wait_reason", "") or "").strip()
        protected_swap_applied = bool(protection_result.get("protected_swap_applied", False))
        protected_swap_summary = str(protection_result.get("protected_swap_summary", "") or "").strip()
        protected_swap_details = [
            item for item in protection_result.get("protected_swap_details", []) if isinstance(item, dict)
        ]
        # Mecanismo de espera/troca desativado: mantemos só os frios excluídos da cobertura.
        protected_wait_triggered = False
        protected_wait_matches = []
        protected_wait_recommended_spins = 0
        protected_wait_reason = ""
        protected_swap_applied = False
        protected_swap_summary = ""
        protected_swap_details = []
        base_is_cold = bool(protection_result.get("base_is_cold", base_is_cold))
        base_cold_rank = protection_result.get("base_cold_rank", base_cold_rank)
        cold_ranking = [int(n) for n in protection_result.get("cold_numbers_considered", []) if 0 <= int(n) <= 36]
        cold_count_effective = len(cold_ranking)
    candidate_policy_score = float(candidate_confidence_score - (len(candidate_list) * 1.5))
    if bool(final_result.get("breakdown", {}).get("block_compaction_applied")):
        candidate_policy_score += 3.0
    if protected_mode_enabled:
        entry_policy = _build_protected_policy_decision(
            {
                **final_result,
                "protected_wait_triggered": protected_wait_triggered,
                "protected_wait_recommended_spins": protected_wait_recommended_spins,
                "protected_wait_reason": protected_wait_reason,
                "protected_excluded_numbers": protected_excluded_numbers,
            },
            candidate_list=candidate_list,
            candidate_confidence=candidate_confidence_score,
            candidate_policy_score=candidate_policy_score,
        )
    else:
        entry_policy = final_suggestion_entry_intelligence.recommend(
            active_signal=None,
            candidate_signal={
                "suggestion": candidate_list,
                "confidence_score": candidate_confidence_score,
                "suggestion_size": len(candidate_list),
                "policy_score": round(candidate_policy_score, 4),
                "block_compaction_applied": bool(final_result.get("breakdown", {}).get("block_compaction_applied")),
            },
            history=normalized_history,
            from_index=from_index,
            overlap_window=entry_policy_overlap_window,
            high_confidence_cutoff=entry_policy_high_confidence_cutoff,
        )
    optimized_supported = bool(optimized_result.get("available", False)) and bool(opt_list_ranked)
    gate_reasons: List[str] = []
    if not protected_mode_enabled:
        if final_gate_require_optimized and not optimized_supported:
            filter_reason = str(optimized_result.get("filter_reason", "") or "").strip()
            if filter_reason:
                gate_reasons.append(f"Motor otimizado bloqueou o sinal: {filter_reason}")
            else:
                gate_reasons.append("Motor otimizado sem suporte suficiente para emitir a sugestão final.")
        if candidate_confidence_score < final_gate_min_confidence:
            gate_reasons.append(
                f"Confidence final abaixo do mínimo ({candidate_confidence_score}<{final_gate_min_confidence})."
            )
        if entry_policy_enabled and str(entry_policy.get("action", "")).lower() == "wait":
            wait_spins = max(0, int(entry_policy.get("recommended_wait_spins", 0) or 0))
            if wait_spins > 0:
                gate_reasons.append(f"Política de entrada recomendou esperar {wait_spins} giro(s).")
            else:
                gate_reasons.append("Política de entrada recomendou aguardar antes de emitir.")
    emission_gate_passed = bool(candidate_list) if protected_mode_enabled else bool(final_result.get("available", False)) and not gate_reasons
    final_list = candidate_list if emission_gate_passed else []
    final_protections = candidate_protections if emission_gate_passed else []
    emission_gate = {
        "passed": emission_gate_passed,
        "reasons": gate_reasons,
        "require_optimized_support": final_gate_require_optimized,
        "optimized_supported": optimized_supported,
        "optimized_available": bool(optimized_result.get("available", False)),
        "min_confidence": final_gate_min_confidence,
        "candidate_confidence": candidate_confidence_score,
        "entry_policy_enabled": entry_policy_enabled,
        "entry_policy_action": str(entry_policy.get("action", "")),
        "entry_policy_wait_spins": int(entry_policy.get("recommended_wait_spins", 0) or 0),
        "used_confidence_v2": bool(final_gate_use_confidence_v2 and opt_confidence_v2 > 0),
    }
    explanation = str(final_result.get("explanation", "") or "").strip()
    if protected_mode_enabled:
        explanation = (
            f"{explanation} Cobertura protegida ativa: {len(candidate_list)} numero(s), removendo os frios {protected_excluded_numbers} pelas ultimas 50 jogadas."
        ).strip()
        if protected_swap_applied and protected_swap_summary:
            explanation = f"{explanation} {protected_swap_summary}".strip()
    if gate_reasons:
        explanation = f"{explanation} Emissão bloqueada: {' '.join(gate_reasons)}".strip()
    optimized_payload = {
        "available": bool(optimized_result.get("available", False)),
        "suggestion": opt_list_sorted,
        "explanation": optimized_result.get("explanation", ""),
        "confidence": optimized_result.get("confidence", {"score": 0, "label": "Baixa"}),
        "confidence_breakdown": optimized_result.get("confidence_breakdown", {}),
        "confidence_v2_score": opt_confidence_v2,
        "confidence_effective_score": opt_confidence_effective,
        "confidence_effective_source": opt_confidence_source,
        "contributions": optimized_result.get("contributions", []),
        "negative_contributions": optimized_result.get("negative_contributions", []),
        "pending_patterns": optimized_result.get("pending_patterns", []),
        "number_details": number_details if isinstance(number_details, list) else [],
        "adaptive_weights": optimized_result.get("adaptive_weights", []),
        "weight_profile": {
            "id": selected_profile.get("id"),
            "name": selected_profile.get("name"),
            "runtime_weight_count": len(runtime_profile_weights),
            "effective_weight_count": len(effective_profile_weights),
        } if isinstance(selected_profile, dict) else (
            {
                "id": None,
                "name": None,
                "runtime_weight_count": len(runtime_profile_weights),
                "effective_weight_count": len(effective_profile_weights),
            }
            if runtime_profile_weights
            else None
        ),
        "dynamic_weighting": dynamic_weighting_meta,
    }
    simple_payload = _build_simple_suggestion_from_contributions(
        optimized_result.get("contributions", []),
        focus_number=focus_number,
        from_index=from_index,
        max_numbers=effective_target_size,
        block_bets_enabled=bool(payload.block_bets_enabled),
        pulled_counts=pulled_counts,
        weight_profile_id=selected_profile_id,
        weight_profile_weights=effective_profile_weights,
        known_pattern_ids=[definition.id for definition in pattern_engine._load_patterns()],
    )
    simple_payload["dynamic_weighting"] = dynamic_weighting_meta
    if isinstance(simple_payload.get("weight_profile"), dict):
        simple_payload["weight_profile"].update(dynamic_weighting_meta)
    simple_payload["entry_shadow"] = simple_suggestion_entry_shadow.evaluate(
        simple_payload=simple_payload,
        history=normalized_history,
        from_index=from_index,
        max_attempts=4,
    )
    return {
        **final_result,
        "available": emission_gate_passed,
        "list": final_list,
        "suggestion": final_list,
        "ordered_suggestion": list(final_list),
        "protections": final_protections,
        "focus_number": focus_number,
        "from_index": from_index,
        "block_bets_enabled": bool(payload.block_bets_enabled),
        "optimized_max_numbers": optimized_max_numbers,
        "base_weight": final_base_weight,
        "optimized_weight": final_optimized_weight,
        "block_bets_enabled": bool(payload.block_bets_enabled),
        "entry_policy_enabled": entry_policy_enabled,
        "entry_policy": entry_policy,
        "emission_gate": emission_gate,
        "candidate_available": bool(final_result.get("available", False)),
        "candidate_list": candidate_list,
        "candidate_suggestion": candidate_list,
        "candidate_ordered_suggestion": list(candidate_list),
        "candidate_protections": candidate_protections,
        "candidate_confidence": candidate_confidence_obj,
        "candidate_explanation": final_result.get("explanation", ""),
        "confidence": candidate_confidence_obj,
        "explanation": explanation,
        "ranking_locked": bool(protected_mode_enabled),
        "protected_mode_enabled": protected_mode_enabled,
        "protected_suggestion_size": protected_suggestion_size if protected_mode_enabled else None,
        "protected_recent_anchor_count": protected_recent_anchor_count if protected_mode_enabled else None,
        "protected_swap_enabled": protected_swap_enabled if protected_mode_enabled else False,
        "protected_swap_applied": protected_swap_applied if protected_mode_enabled else False,
        "protected_swap_summary": protected_swap_summary if protected_mode_enabled else "",
        "protected_swap_details": protected_swap_details if protected_mode_enabled else [],
        "protected_excluded_numbers": protected_excluded_numbers if protected_mode_enabled else [],
        "protected_original_excluded_numbers": protected_original_excluded_numbers if protected_mode_enabled else [],
        "protected_guard_numbers": protected_guard_numbers if protected_mode_enabled else [],
        "protected_guard_details": protected_guard_details if protected_mode_enabled else {},
        "protected_wait_triggered": bool(protected_wait_triggered) if protected_mode_enabled else False,
        "protected_wait_matches": protected_wait_matches if protected_mode_enabled else [],
        "protected_wait_recommended_spins": protected_wait_recommended_spins if protected_mode_enabled else 0,
        "protected_wait_reason": protected_wait_reason if protected_mode_enabled else "",
        "excluded_tail_numbers": list(protection_result.get("excluded_tail_numbers", [])) if isinstance(protection_result, dict) else [],
        "excluded_tail_reasons": list(protection_result.get("excluded_tail_reasons", [])) if isinstance(protection_result, dict) else [],
        "protection_candidate_details": dict(protection_result.get("candidate_details", {})) if isinstance(protection_result, dict) else {},
        "base_is_cold": bool(base_is_cold),
        "base_cold_rank": base_cold_rank,
        "cold_numbers_considered": cold_ranking,
        "cold_count_requested": cold_count_effective,
        "cold_wait_recommended_spins": protected_wait_recommended_spins if protected_mode_enabled else (2 if base_is_cold else 0),
        # Mantém payload de resposta compatível com ordem antiga.
        "base_suggestion": base_list_for_engine,
        "base_confidence": base_confidence_score,
        "base_bucket": bucket,
        "base_pulled_counts": pulled_counts,
        "optimized_payload": optimized_payload,
        "optimized_suggestion": opt_list_sorted,
        "optimized_confidence": opt_confidence,
        "optimized_confidence_v2": opt_confidence_v2,
        "optimized_confidence_effective": opt_confidence_effective,
        "optimized_confidence_source": opt_confidence_source,
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
        "simple_payload": simple_payload,
        "simple_suggestion": simple_payload.get("list", []),
        "simple_available": bool(simple_payload.get("available", False)),
        "simple_explanation": simple_payload.get("explanation", ""),
        "simple_number_details": simple_payload.get("number_details", []),
        "simple_pattern_count": int(simple_payload.get("pattern_count", 0) or 0),
        "simple_unique_numbers": int(simple_payload.get("unique_numbers", 0) or 0),
        "simple_entry_shadow": simple_payload.get("entry_shadow", {}),
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

        runtime_overrides: Dict[str, Dict[str, Any]] = {
            str(key): dict(value)
            for key, value in dict(payload.runtime_overrides or {}).items()
            if isinstance(value, dict)
        }

        result = pattern_engine.evaluate(
            history=payload.history,
            base_suggestion=payload.base_suggestion,
            focus_number=payload.focus_number,
            legacy_confidence_score=payload.legacy_confidence_score,
            from_index=max(0, payload.from_index),
            max_numbers=max(1, min(37, payload.max_numbers)),
            runtime_overrides=runtime_overrides,
        )
        if payload.log_event:
            event = _event_from_result(
                source="optimized_suggestion",
                roulette_id=None,
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
                roulette_id=None,
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
                roulette_id=None,
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
                roulette_id=None,
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


@router.post("/api/patterns/simple-suggestion")
async def get_simple_suggestion(payload: FinalSuggestionRequest):
    """
    Retorna uma sugestao simples baseada apenas na contagem de apoio dos patterns.

    Regra:
    - sem weight_profile_id: cada pattern positivo que citar um numero soma 1 ponto para esse numero
    - com weight_profile_id: cada pattern positivo soma o multiplicador salvo no profile
    - com block_bets_enabled: reaplica a compactacao em blocos do final-suggestion sobre o ranking simples
    - confidence e score final do motor nao entram no ranking
    """
    try:
        result = await _compute_final_suggestion(payload)
        simple_payload = result.get("simple_payload", {})
        if isinstance(simple_payload, dict):
            return simple_payload
        return {
            "available": False,
            "list": [],
            "suggestion": [],
            "ordered_suggestion": [],
            "focus_number": payload.focus_number,
            "from_index": max(0, int(payload.from_index)),
            "max_numbers": max(1, min(37, int(payload.max_numbers))),
            "pattern_count": 0,
            "unique_numbers": 0,
            "number_details": [],
            "selected_number_details": [],
            "top_support_count": 0,
            "min_support_count": 0,
            "avg_support_count": 0.0,
            "top_weighted_support_score": 0.0,
            "min_weighted_support_score": 0.0,
            "avg_weighted_support_score": 0.0,
            "contributions": [],
            "explanation": "Sugestao simples indisponivel.",
            "weight_profile": None,
            "block_bets_enabled": bool(payload.block_bets_enabled),
            "block_compaction": {"list": [], "added": [], "removed": [], "changed": False},
            "block_compaction_applied": False,
            "block_numbers_added": 0,
            "block_numbers_removed": 0,
            "ranking_locked": True,
            "entry_shadow": simple_suggestion_entry_shadow.unavailable(
                "Sugestao simples indisponivel.",
                suggestion_size=0,
            ),
        }
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
            weight_profile_weights=payload.weight_profile_weights,
            entry_policy_enabled=payload.entry_policy_enabled,
            entry_policy_overlap_window=payload.entry_policy_overlap_window,
            entry_policy_high_confidence_cutoff=payload.entry_policy_high_confidence_cutoff,
            final_gate_require_optimized=payload.final_gate_require_optimized,
            final_gate_use_confidence_v2=payload.final_gate_use_confidence_v2,
            final_gate_min_confidence=payload.final_gate_min_confidence,
            protected_mode_enabled=payload.protected_mode_enabled,
            protected_suggestion_size=payload.protected_suggestion_size,
            protected_recent_anchor_count=payload.protected_recent_anchor_count,
            protected_swap_enabled=payload.protected_swap_enabled,
            cold_count=payload.cold_count,
        )
        result = await _compute_final_suggestion(suggestion_payload)
        candidate_list = [int(n) for n in (result.get("candidate_suggestion") or result.get("candidate_list") or []) if 0 <= int(n) <= 36]
        candidate_confidence = int(result.get("candidate_confidence", {}).get("score", 0) or result.get("confidence", {}).get("score", 0) or 0)
        candidate_policy_score = candidate_confidence - (len(candidate_list) * 1.5)
        if bool(result.get("breakdown", {}).get("block_compaction_applied")):
            candidate_policy_score += 3.0

        if bool(result.get("protected_mode_enabled", False)):
            live_decision = _build_protected_policy_decision(
                result,
                candidate_list=candidate_list,
                candidate_confidence=candidate_confidence,
                candidate_policy_score=candidate_policy_score,
            )
        else:
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
                from_index=payload.from_index,
                overlap_window=payload.entry_policy_overlap_window,
                high_confidence_cutoff=payload.entry_policy_high_confidence_cutoff,
            )
        return {
            "available": bool(result.get("available", False)),
            "decision": live_decision,
            "candidate_signal": {
                "focus_number": int(result.get("focus_number", payload.focus_number or 0) or 0),
                "suggestion": candidate_list,
                "confidence": result.get("candidate_confidence", result.get("confidence", {"score": 0, "label": "Baixa"})),
                "confidence_v2_score": int(
                    result.get("optimized_payload", {}).get("confidence_breakdown", {}).get("calibrated_confidence_v2", 0)
                    or result.get("optimized_breakdown", {}).get("calibrated_confidence_v2", 0)
                    or 0
                ),
                "suggestion_size": len(candidate_list),
                "policy_score": round(float(candidate_policy_score), 4),
                "block_compaction_applied": bool(result.get("breakdown", {}).get("block_compaction_applied")),
                "block_bets_enabled": bool(result.get("blockBetsEnabled", payload.block_bets_enabled)),
                "ranking_locked": bool(result.get("ranking_locked", False)),
                "protected_mode_enabled": bool(result.get("protected_mode_enabled", False)),
                "protected_suggestion_size": result.get("protected_suggestion_size"),
                "protected_swap_enabled": bool(result.get("protected_swap_enabled", False)),
                "protected_swap_applied": bool(result.get("protected_swap_applied", False)),
                "protected_swap_summary": str(result.get("protected_swap_summary", "") or ""),
                "protected_swap_details": list(result.get("protected_swap_details", []) or []),
                "protected_excluded_numbers": list(result.get("protected_excluded_numbers", []) or []),
                "protected_original_excluded_numbers": list(result.get("protected_original_excluded_numbers", []) or []),
                "protected_guard_numbers": list(result.get("protected_guard_numbers", []) or []),
                "protected_guard_details": dict(result.get("protected_guard_details", {}) or {}),
                "protected_wait_triggered": bool(result.get("protected_wait_triggered", False)),
                "protected_wait_recommended_spins": int(result.get("protected_wait_recommended_spins", 0) or 0),
                "protected_wait_reason": str(result.get("protected_wait_reason", "") or ""),
                "base_is_cold": bool(result.get("base_is_cold", False)),
                "cold_wait_recommended_spins": int(result.get("cold_wait_recommended_spins", 0) or 0),
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
