from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.services import decoder_lab
from api.services import decoder_live_monitor


router = APIRouter()


class DecoderLabRequest(BaseModel):
    roulette_id: str
    state_numbers: List[int] = Field(default_factory=list)
    context_numbers: List[int] = Field(default_factory=list)
    history_entries: List[Dict[str, Any]] = Field(default_factory=list)
    state_window: int = 6
    future_horizon: int = 5
    ignore_last_occurrence: bool = True
    days_back: int = 30
    max_records: int = 5000
    validation_ratio: float = 0.25
    min_support: int = 3
    top_k: int = 12
    episode_limit: int = 80
    similarity_threshold: float = 0.54
    live_min_confidence: int = 55
    live_min_matched_episodes: int = 12
    live_number_count: int = 12
    live_include_secondary: bool = False
    live_require_threshold_mode: bool = False


async def _run_decoder_lab_analysis(payload: DecoderLabRequest) -> Dict[str, Any]:
    state_numbers = payload.state_numbers or payload.context_numbers
    if payload.history_entries:
        rows = list(payload.history_entries)
    else:
        rows = await decoder_lab.load_decoder_lab_rows(
            roulette_id=payload.roulette_id,
            days_back=payload.days_back,
            max_records=payload.max_records,
        )

    analysis = decoder_lab.build_decoder_lab_analysis(
        rows,
        roulette_id=payload.roulette_id,
        state_numbers=state_numbers,
        state_window=payload.state_window,
        future_horizon=payload.future_horizon,
        ignore_last_occurrence=payload.ignore_last_occurrence,
        validation_ratio=payload.validation_ratio,
        min_support=payload.min_support,
        top_k=payload.top_k,
        episode_limit=payload.episode_limit,
        similarity_threshold=payload.similarity_threshold,
    )
    analysis["live_signal_candidate"] = decoder_live_monitor.build_signal_candidate(
        analysis,
        include_secondary=payload.live_include_secondary,
        max_numbers=payload.live_number_count,
        min_confidence=payload.live_min_confidence,
        min_matched_episodes=payload.live_min_matched_episodes,
        require_threshold_mode=payload.live_require_threshold_mode,
    )
    return analysis


@router.post("/api/decoder-lab/analyze")
async def analyze_decoder_lab(payload: DecoderLabRequest) -> Dict[str, Any]:
    try:
        return await _run_decoder_lab_analysis(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
