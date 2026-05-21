from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Query

from api.services.pattern_assertiveness_service import (
    build_pattern_assertiveness_report,
    build_pattern_walkforward_report,
)
from api.services.suggestion_snapshot_service import (
    get_or_create_global_suggestion_snapshot_config,
    update_global_suggestion_snapshot_weight_profile,
)


# Plano default sugerido baseado no walk-forward de 21/05: boost dos 4
# padrões com alpha confirmado out-of-sample e zerar os 2 com drag confirmado.
DEFAULT_WALKFORWARD_WEIGHTS = {
    # Consistente positivos (boost ~1.4x — modesto pq lift observado é só ~1.07)
    "legacy_processing_super1": 1.4,
    "high_low_streak_boost": 1.4,
    "finals_pattern_boost": 1.4,
    "sector_alternation_boost": 1.4,
    # Consistente negativos (zerar — esses padrões consistentemente puxam para baixo)
    "legacy_processing_chat_rick_v2": 0.0,
    "alinhamento_boost": 0.0,
}


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


@router.get("/api/pattern-assertiveness/walkforward")
async def get_pattern_walkforward(
    roulette_id: str = Query(..., min_length=1),
    limit: int = Query(default=2000, ge=100, le=5000),
    include_all_configs: bool = Query(default=False),
    train_ratio: float = Query(default=0.5, ge=0.3, le=0.7),
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
        return await build_pattern_walkforward_report(
            roulette_id=roulette_id,
            limit=limit,
            include_all_configs=include_all_configs,
            gale_levels=parsed_levels or None,
            train_ratio=train_ratio,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha no walk-forward de padrões: {exc}")


@router.get("/api/pattern-assertiveness/weights")
async def get_pattern_weights():
    """Retorna o weight_profile_weights ativo + a sugestão default do walk-forward."""
    config = await get_or_create_global_suggestion_snapshot_config()
    return {
        "available": True,
        "active_weights": dict(config.get("weight_profile_weights") or {}),
        "active_profile_id": config.get("weight_profile_id"),
        "recommended_weights": dict(DEFAULT_WALKFORWARD_WEIGHTS),
    }


@router.put("/api/pattern-assertiveness/weights")
async def put_pattern_weights(payload: dict = Body(default_factory=dict)):
    """Aplica pesos por pattern_id no config global de snapshots.

    Body: {"weights": {"<pattern_id>": <multiplicador>, ...}, "profile_id": "opcional"}

    Use {"weights": {}} para resetar (sem boost/penalty).
    Para aplicar a recomendação walk-forward, mande o objeto retornado em GET .../weights.recommended_weights.
    """
    raw_weights = payload.get("weights") if isinstance(payload, dict) else None
    if raw_weights is not None and not isinstance(raw_weights, dict):
        raise HTTPException(status_code=400, detail="`weights` precisa ser um objeto pattern_id→multiplicador.")
    profile_id = payload.get("profile_id") if isinstance(payload, dict) else None
    try:
        updated = await update_global_suggestion_snapshot_weight_profile(
            raw_weights or {},
            weight_profile_id=str(profile_id) if profile_id else None,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha ao atualizar weights: {exc}")
    return {
        "available": True,
        "active_weights": dict(updated.get("weight_profile_weights") or {}),
        "active_profile_id": updated.get("weight_profile_id"),
    }
