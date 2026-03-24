from __future__ import annotations

from typing import Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.routes.patterns import FinalSuggestionRequest, _compute_final_suggestion
from api.services.assertiveness_replay import fetch_history_desc, run_assertiveness_replay


router = APIRouter()


class AssertivenessReplayRequest(BaseModel):
    roulette_id: str
    history_limit: int = 1200
    entries_limit: int = 300
    bet_size: int = 8
    max_attempts: int = 3
    min_history_size: int = 50
    min_confidence: int = 0
    chip_values: List[float] = Field(default_factory=lambda: [1.0, 1.0, 1.0])
    base_weight: float = 0.5
    optimized_weight: float = 0.5
    siege_window: int = 6
    siege_min_occurrences: int = 3
    siege_min_streak: int = 2
    siege_veto_relief: float = 0.4
    block_bets_enabled: bool = False
    inversion_enabled: bool = True
    inversion_context_window: int = 15
    inversion_penalty_factor: float = 0.3


@router.post("/api/assertiveness/replay")
async def replay_assertiveness(payload: AssertivenessReplayRequest) -> Dict:
    try:
        history_desc = await fetch_history_desc(payload.roulette_id, payload.history_limit)

        async def suggestion_provider(context_desc: List[int]) -> Dict:
            request_payload = FinalSuggestionRequest(
                history=context_desc,
                focus_number=context_desc[0] if context_desc else None,
                from_index=0,
                max_numbers=payload.bet_size,
                optimized_max_numbers=37,
                base_weight=payload.base_weight,
                optimized_weight=payload.optimized_weight,
                runtime_overrides={},
                siege_window=payload.siege_window,
                siege_min_occurrences=payload.siege_min_occurrences,
                siege_min_streak=payload.siege_min_streak,
                siege_veto_relief=payload.siege_veto_relief,
                block_bets_enabled=payload.block_bets_enabled,
                inversion_enabled=payload.inversion_enabled,
                inversion_context_window=payload.inversion_context_window,
                inversion_penalty_factor=payload.inversion_penalty_factor,
            )
            return await _compute_final_suggestion(request_payload)

        result = await run_assertiveness_replay(
            roulette_id=payload.roulette_id,
            history_desc=history_desc,
            suggestion_provider=suggestion_provider,
            min_history_size=payload.min_history_size,
            entries_limit=payload.entries_limit,
            max_attempts=payload.max_attempts,
            min_confidence=payload.min_confidence,
            chip_values=payload.chip_values,
        )
        result["config"] = payload.model_dump()
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
