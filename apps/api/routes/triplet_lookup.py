from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query

from api.services.triplet_lookup_service import lookup_triplet_ranking


router = APIRouter()


@router.get("/api/triplet-lookup")
async def triplet_lookup_route(
    a: int = Query(..., ge=0, le=36, description="1o numero da sequencia"),
    b: int = Query(..., ge=0, le=36, description="2o numero da sequencia"),
    c: int = Query(..., ge=0, le=36, description="3o numero da sequencia"),
    positions: int = Query(default=1, ge=1, le=3, description="Quantas rodadas seguintes combinar no ranking (1, 2 ou 3)"),
    roulette_id: Optional[str] = Query(default=None, description="Filtrar por roleta especifica. Omita para todas."),
) -> Dict[str, Any]:
    try:
        return await lookup_triplet_ranking(
            a=a,
            b=b,
            c=c,
            positions=positions,
            roulette_id=roulette_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha ao consultar trigrama: {exc}")
