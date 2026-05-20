from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

from api.services.occurrence_signal_service import validate_occurrence_signal

router = APIRouter()


@router.get("/api/occurrence-signal/validate")
async def validate(roulette_id: str = Query(...)) -> Dict[str, Any]:
    try:
        return await validate_occurrence_signal(roulette_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha ao validar sinal: {exc}")
