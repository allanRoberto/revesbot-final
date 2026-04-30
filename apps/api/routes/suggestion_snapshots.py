from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from api.services.suggestion_snapshot_service import (
    build_suggestion_snapshot_rank_timeline,
    get_or_create_global_suggestion_snapshot_config,
    resolve_latest_suggestion_snapshot,
    resolve_suggestion_snapshot_by_history_id,
    resolve_suggestion_snapshot_by_index,
)


router = APIRouter()


@router.get("/api/suggestion-snapshots/config")
async def get_global_suggestion_snapshot_config_route():
    config = await get_or_create_global_suggestion_snapshot_config()
    return {
        "available": True,
        "config": config,
    }


@router.get("/api/suggestion-snapshots/{roulette_id}/latest")
async def get_latest_suggestion_snapshot_route(
    roulette_id: str,
    take: int = Query(default=37, ge=1, le=37),
):
    try:
        return await resolve_latest_suggestion_snapshot(
            roulette_id=roulette_id,
            take=take,
            source="api_latest",
            create_if_missing=False,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha ao resolver snapshot da sugestão: {exc}")


@router.get("/api/suggestion-snapshots/{roulette_id}/by-index")
async def get_suggestion_snapshot_by_index_route(
    roulette_id: str,
    from_index: int = Query(default=0, ge=0),
    take: int = Query(default=37, ge=1, le=37),
):
    try:
        return await resolve_suggestion_snapshot_by_index(
            roulette_id=roulette_id,
            from_index=from_index,
            take=take,
            source="api_on_demand",
            create_if_missing=False,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha ao resolver snapshot da sugestão: {exc}")


@router.get("/api/suggestion-snapshots/{roulette_id}/by-history-id")
async def get_suggestion_snapshot_by_history_id_route(
    roulette_id: str,
    history_id: str = Query(..., min_length=1),
    take: int = Query(default=37, ge=1, le=37),
):
    try:
        return await resolve_suggestion_snapshot_by_history_id(
            roulette_id=roulette_id,
            history_id=history_id,
            take=take,
            source="api_on_demand",
            create_if_missing=False,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha ao resolver snapshot da sugestão: {exc}")


@router.get("/api/suggestion-snapshots/performance/rank-timeline")
async def get_suggestion_snapshot_rank_timeline_route(
    roulette_id: str = Query(..., min_length=1),
    limit: int = Query(default=200, ge=20, le=2000),
    include_all_configs: bool = Query(default=False),
):
    try:
        return await build_suggestion_snapshot_rank_timeline(
            roulette_id=roulette_id,
            limit=limit,
            include_all_configs=include_all_configs,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha ao montar timeline das sugestões: {exc}")
