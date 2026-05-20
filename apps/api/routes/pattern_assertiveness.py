from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from api.services.pattern_assertiveness_service import (
    build_pattern_assertiveness_report,
)


router = APIRouter()


@router.get("/api/pattern-assertiveness")
async def get_pattern_assertiveness(
    roulette_id: str = Query(..., min_length=1),
    limit: int = Query(default=2000, ge=50, le=5000),
    include_all_configs: bool = Query(default=False),
    gale_levels: str = Query(default="1,2,3,5", min_length=1, max_length=64),
):
    parsed_levels: list[int] = []
    for raw in gale_levels.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            parsed_levels.append(int(raw))
        except ValueError:
            continue
    try:
        return await build_pattern_assertiveness_report(
            roulette_id=roulette_id,
            limit=limit,
            include_all_configs=include_all_configs,
            gale_levels=parsed_levels or None,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha no backtest de padrões: {exc}")
