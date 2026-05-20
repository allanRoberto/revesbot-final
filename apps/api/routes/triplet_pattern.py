from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from pymongo import DESCENDING

from api.core.db import history_coll
from api.services.triplet_pattern_service import validate_triplet_pattern

router = APIRouter()


@router.get("/api/triplet-pattern/last-spins")
async def last_spins(
    roulette_id: str = Query(..., description="Roleta para puxar os ultimos numeros"),
    count: int = Query(9, ge=1, le=50),
) -> Dict[str, Any]:
    docs = await history_coll.find(
        {"roulette_id": roulette_id},
        {"value": 1, "timestamp": 1},
    ).sort("timestamp", DESCENDING).limit(count).to_list(length=count)
    docs.reverse()
    return {
        "roulette_id": roulette_id,
        "numbers": [int(d["value"]) for d in docs],
    }


@router.get("/api/triplet-pattern/validate")
async def validate(
    n1: int = Query(..., ge=0, le=36),
    n2: int = Query(..., ge=0, le=36),
    n3: int = Query(..., ge=0, le=36),
    n4: int = Query(..., ge=0, le=36),
    n5: int = Query(..., ge=0, le=36),
    n6: int = Query(..., ge=0, le=36),
    n7: int = Query(..., ge=0, le=36),
    n8: int = Query(..., ge=0, le=36),
    n9: int = Query(..., ge=0, le=36),
    neighbor_span: int = Query(2, ge=1, le=6, description="Casas vizinhas para cada lado na roda"),
    roulette_id: Optional[str] = Query(None, description="Filtrar Confirmacao 1 por roleta. Omita para todas."),
    post_count: int = Query(20, ge=1, le=50),
) -> Dict[str, Any]:
    numbers = [n1, n2, n3, n4, n5, n6, n7, n8, n9]
    try:
        return await validate_triplet_pattern(
            numbers=numbers,
            neighbor_span=neighbor_span,
            roulette_id=roulette_id,
            post_count=post_count,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha ao validar padrao: {exc}")
