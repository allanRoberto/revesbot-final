from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

from api.services.next_number_backtest_service import (
    DEFAULT_ATTEMPTS,
    DEFAULT_BACKTEST_LIMIT,
    DEFAULT_BET_SIZE,
    DEFAULT_HOT_NUMBERS_COUNT,
    DEFAULT_HOT_NUMBERS_ONLY,
    DEFAULT_HOT_NUMBERS_WINDOW,
    DEFAULT_INCLUDE_HOT_COMPARISON,
    DEFAULT_INVERTED_ACTION,
    DEFAULT_INVERTED_DELAY_SPINS,
    MAX_ATTEMPTS,
    MAX_BACKTEST_LIMIT,
    MAX_BET_SIZE,
    MAX_HOT_NUMBERS_COUNT,
    MAX_HOT_NUMBERS_WINDOW,
    MAX_INVERTED_DELAY_SPINS,
    run_next_number_backtest,
)
from api.services.next_number_ranking_service import (
    DEFAULT_ROULETTE_ID,
    get_latest_next_number_rankings,
    get_next_number_ranking_for_number,
)


router = APIRouter()


@router.get("/api/next-number-rankings/{roulette_id}/latest")
async def get_next_number_rankings_latest_route(
    roulette_id: str,
) -> Dict[str, Any]:
    try:
        return await get_latest_next_number_rankings(roulette_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha ao consultar ranking de puxadas: {exc}")


@router.get("/api/next-number-rankings/{roulette_id}/numbers/{base_number}")
async def get_next_number_ranking_number_route(
    roulette_id: str,
    base_number: int,
) -> Dict[str, Any]:
    try:
        return await get_next_number_ranking_for_number(
            roulette_id=roulette_id,
            base_number=base_number,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha ao consultar ranking do numero: {exc}")


@router.get("/api/next-number-rankings/{roulette_id}/backtest")
async def get_next_number_backtest_route(
    roulette_id: str,
    limit: int = Query(default=DEFAULT_BACKTEST_LIMIT, ge=1, le=MAX_BACKTEST_LIMIT),
    attempts: int = Query(default=DEFAULT_ATTEMPTS, ge=1, le=MAX_ATTEMPTS),
    bet_size: int = Query(default=DEFAULT_BET_SIZE, ge=1, le=MAX_BET_SIZE),
    inverted_0_action: str = Query(default=DEFAULT_INVERTED_ACTION),
    inverted_0_delay: int = Query(default=DEFAULT_INVERTED_DELAY_SPINS, ge=0, le=MAX_INVERTED_DELAY_SPINS),
    inverted_1_action: str = Query(default=DEFAULT_INVERTED_ACTION),
    inverted_1_delay: int = Query(default=DEFAULT_INVERTED_DELAY_SPINS, ge=0, le=MAX_INVERTED_DELAY_SPINS),
    inverted_2_action: str = Query(default=DEFAULT_INVERTED_ACTION),
    inverted_2_delay: int = Query(default=DEFAULT_INVERTED_DELAY_SPINS, ge=0, le=MAX_INVERTED_DELAY_SPINS),
    inverted_3_action: str = Query(default=DEFAULT_INVERTED_ACTION),
    inverted_3_delay: int = Query(default=DEFAULT_INVERTED_DELAY_SPINS, ge=0, le=MAX_INVERTED_DELAY_SPINS),
    hot_numbers_only: bool = Query(default=DEFAULT_HOT_NUMBERS_ONLY),
    hot_numbers_count: int = Query(default=DEFAULT_HOT_NUMBERS_COUNT, ge=1, le=MAX_HOT_NUMBERS_COUNT),
    hot_numbers_window: int = Query(default=DEFAULT_HOT_NUMBERS_WINDOW, ge=1, le=MAX_HOT_NUMBERS_WINDOW),
    include_hot_comparison: bool = Query(default=DEFAULT_INCLUDE_HOT_COMPARISON),
) -> Dict[str, Any]:
    try:
        return await run_next_number_backtest(
            roulette_id=roulette_id,
            limit=limit,
            attempts=attempts,
            bet_size=bet_size,
            inverted_rules={
                "0": {"action": inverted_0_action, "delay_spins": inverted_0_delay},
                "1": {"action": inverted_1_action, "delay_spins": inverted_1_delay},
                "2": {"action": inverted_2_action, "delay_spins": inverted_2_delay},
                "3": {"action": inverted_3_action, "delay_spins": inverted_3_delay},
            },
            hot_numbers_only=hot_numbers_only,
            hot_numbers_count=hot_numbers_count,
            hot_numbers_window=hot_numbers_window,
            include_hot_comparison=include_hot_comparison,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha ao rodar backtest de puxadas: {exc}")


@router.get("/api/next-number-rankings/latest")
async def get_default_next_number_rankings_latest_route(
) -> Dict[str, Any]:
    return await get_next_number_rankings_latest_route(DEFAULT_ROULETTE_ID)
