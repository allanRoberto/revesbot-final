from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from api.services.suggestion_snapshot_service import (
    build_suggestion_snapshot_rank_timeline,
    get_or_create_global_suggestion_snapshot_config,
    resolve_latest_suggestion_snapshot,
    resolve_suggestion_snapshot_by_history_id,
    resolve_suggestion_snapshot_by_index,
)
from api.services.suggestion_rank_strategy_learning import (
    build_rank_strategy_dataset,
    simulate_rank_strategy_regime_walkforward,
    simulate_rank_strategy_walkforward,
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


@router.get("/api/suggestion-snapshots/performance/strategy-dataset")
async def get_rank_strategy_dataset_route(
    roulette_id: str = Query(..., min_length=1),
    limit: int = Query(default=1000, ge=100, le=5000),
    lookback: int = Query(default=6, ge=3, le=12),
    top_target: int = Query(default=12, ge=1, le=37),
    include_all_configs: bool = Query(default=False),
):
    try:
        return await build_rank_strategy_dataset(
            roulette_id=roulette_id,
            limit=limit,
            lookback=lookback,
            top_target=top_target,
            include_all_configs=include_all_configs,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha ao montar dataset da estratégia: {exc}")


@router.get("/api/suggestion-snapshots/performance/strategy-simulator")
async def get_rank_strategy_simulator_route(
    roulette_id: str = Query(..., min_length=1),
    limit: int = Query(default=1000, ge=100, le=5000),
    lookback: int = Query(default=6, ge=3, le=12),
    top_target: int = Query(default=12, ge=1, le=37),
    include_all_configs: bool = Query(default=False),
    k_neighbors: int = Query(default=15, ge=1, le=100),
    min_train_size: int = Query(default=80, ge=30, le=500),
    sample_predictions: int = Query(default=25, ge=1, le=200),
    confidence_margin_to_second: float = Query(default=3.0, ge=0.0, le=100.0),
    confidence_margin_vs_normal: float = Query(default=1.0, ge=0.0, le=100.0),
    confidence_share_min: float = Query(default=0.29, ge=0.0, le=1.0),
):
    try:
        return await simulate_rank_strategy_walkforward(
            roulette_id=roulette_id,
            limit=limit,
            lookback=lookback,
            top_target=top_target,
            include_all_configs=include_all_configs,
            k_neighbors=k_neighbors,
            min_train_size=min_train_size,
            sample_predictions=sample_predictions,
            confidence_margin_to_second=confidence_margin_to_second,
            confidence_margin_vs_normal=confidence_margin_vs_normal,
            confidence_share_min=confidence_share_min,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha ao simular estratégia por dados: {exc}")


@router.get("/api/suggestion-snapshots/performance/strategy-regime-simulator")
async def get_rank_strategy_regime_simulator_route(
    roulette_id: str = Query(..., min_length=1),
    limit: int = Query(default=1000, ge=100, le=5000),
    lookback: int = Query(default=6, ge=3, le=12),
    top_target: int = Query(default=12, ge=1, le=37),
    include_all_configs: bool = Query(default=False),
    min_train_size: int = Query(default=80, ge=30, le=500),
    sample_predictions: int = Query(default=25, ge=1, le=200),
    regime_min_support: int = Query(default=8, ge=1, le=200),
    confidence_margin_to_second: float = Query(default=2.0, ge=0.0, le=100.0),
    confidence_margin_vs_normal: float = Query(default=0.5, ge=0.0, le=100.0),
    confidence_share_min: float = Query(default=0.24, ge=0.0, le=1.0),
):
    try:
        return await simulate_rank_strategy_regime_walkforward(
            roulette_id=roulette_id,
            limit=limit,
            lookback=lookback,
            top_target=top_target,
            include_all_configs=include_all_configs,
            min_train_size=min_train_size,
            sample_predictions=sample_predictions,
            regime_min_support=regime_min_support,
            confidence_margin_to_second=confidence_margin_to_second,
            confidence_margin_vs_normal=confidence_margin_vs_normal,
            confidence_share_min=confidence_share_min,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha ao simular estratégia por regimes: {exc}")
