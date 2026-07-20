from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from api.services.orbit_trigger_service import orbit_trigger_service


router = APIRouter(prefix="/api/orbit-triggers", tags=["orbit-triggers"])


def _roulette_ids(value: str) -> tuple[str, ...]:
    ids = tuple(
        dict.fromkeys(item.strip() for item in str(value).split(",") if item.strip())
    )
    if not ids:
        raise HTTPException(status_code=400, detail="informe ao menos uma roulette_id")
    return ids


@router.get("/catalog")
async def trigger_catalog(
    roulette_ids: str = Query(min_length=1),
):
    return await orbit_trigger_service.catalog(_roulette_ids(roulette_ids))


@router.get("/{strategy_slug}")
async def trigger_detail(
    strategy_slug: str,
    roulette_ids: str = Query(min_length=1),
    history_limit: int = Query(default=20, ge=1, le=50),
):
    try:
        return await orbit_trigger_service.detail(
            strategy_slug,
            _roulette_ids(roulette_ids),
            history_limit=history_limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
