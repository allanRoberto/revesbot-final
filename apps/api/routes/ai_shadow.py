from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.services import ai_shadow


router = APIRouter()


class AIShadowAnalyzeRequest(BaseModel):
    roulette_id: str
    history_entries: List[Dict[str, Any]] = Field(default_factory=list)
    state_numbers: List[int] = Field(default_factory=list)
    state_window: int = 6
    future_horizon: int = 5
    ignore_last_occurrence: bool = True
    days_back: int = 30
    max_records: int = 5000
    validation_ratio: float = 0.25
    min_support: int = 3
    decoder_top_k: int = 18
    shadow_top_k: int = 12
    episode_limit: int = 80
    similarity_threshold: float = 0.54
    min_confidence: int = 56
    min_matched_episodes: int = 12


class AIShadowFeedbackRequest(BaseModel):
    roulette_id: str
    signal_id: str
    numbers: List[int] = Field(default_factory=list)
    feature_map: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    status: str
    hit_number: int | None = None
    confidence_score: int = 0
    matched_episodes: int = 0
    avg_probability: float = 0.0
    attempts: int = 0
    max_attempts: int = 0


async def _run_ai_shadow_analysis(payload: AIShadowAnalyzeRequest) -> Dict[str, Any]:
    if payload.history_entries:
        rows = list(payload.history_entries)
    else:
        rows = await ai_shadow.load_ai_shadow_rows(
            roulette_id=payload.roulette_id,
            days_back=payload.days_back,
            max_records=payload.max_records,
        )
    return ai_shadow.build_ai_shadow_analysis(
        rows,
        roulette_id=payload.roulette_id,
        state_numbers=payload.state_numbers,
        state_window=payload.state_window,
        future_horizon=payload.future_horizon,
        ignore_last_occurrence=payload.ignore_last_occurrence,
        validation_ratio=payload.validation_ratio,
        min_support=payload.min_support,
        decoder_top_k=payload.decoder_top_k,
        top_k=payload.shadow_top_k,
        episode_limit=payload.episode_limit,
        similarity_threshold=payload.similarity_threshold,
        min_confidence=payload.min_confidence,
        min_matched_episodes=payload.min_matched_episodes,
    )


@router.post("/api/ai-shadow/analyze")
async def analyze_ai_shadow(payload: AIShadowAnalyzeRequest) -> Dict[str, Any]:
    try:
        return await _run_ai_shadow_analysis(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/api/ai-shadow/feedback")
async def ai_shadow_feedback(payload: AIShadowFeedbackRequest) -> Dict[str, Any]:
    try:
        profile = ai_shadow.apply_ai_shadow_feedback(
            roulette_id=payload.roulette_id,
            signal_id=payload.signal_id,
            feature_map=payload.feature_map,
            candidate_numbers=payload.numbers,
            status=payload.status,
            hit_number=payload.hit_number,
            confidence_score=payload.confidence_score,
            matched_episodes=payload.matched_episodes,
            avg_similarity=payload.avg_probability,
            attempts=payload.attempts,
            max_attempts=payload.max_attempts,
        )
        return {"ok": True, "profile": profile}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
