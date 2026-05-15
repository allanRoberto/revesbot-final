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
    prev_positions: int = Query(default=0, ge=0, le=3, description="Quantas rodadas anteriores combinar no ranking (0, 1, 2 ou 3)"),
    roulette_id: Optional[str] = Query(default=None, description="Filtrar por roleta especifica. Omita para todas."),
    window_value: Optional[float] = Query(default=None, gt=0, description="Janela de tempo para a busca. Omita para usar todo o historico."),
    window_unit: str = Query(default="hours", regex="^(hours|days)$", description="Unidade da janela: 'hours' ou 'days'."),
    any_order: bool = Query(default=False, description="Se true, busca qualquer ordem dos 3 numeros (todas as permutacoes)."),
) -> Dict[str, Any]:
    window_hours: Optional[float] = None
    if window_value is not None:
        window_hours = float(window_value) * (24.0 if window_unit == "days" else 1.0)
    try:
        return await lookup_triplet_ranking(
            a=a,
            b=b,
            c=c,
            positions=positions,
            prev_positions=prev_positions,
            roulette_id=roulette_id,
            window_hours=window_hours,
            any_order=any_order,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha ao consultar trigrama: {exc}")
