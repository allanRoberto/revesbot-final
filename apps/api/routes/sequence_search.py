from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from api.services.sequence_search_service import sequence_search

router = APIRouter()


@router.get("/api/sequence-search")
async def search(
    n1: int = Query(..., ge=0, le=36),
    n2: int = Query(..., ge=0, le=36),
    n3: Optional[int] = Query(None, ge=0, le=36),
    n4: Optional[int] = Query(None, ge=0, le=36),
    n5: Optional[int] = Query(None, ge=0, le=36),
    n6: Optional[int] = Query(None, ge=0, le=36),
    m1: str = Query("exato"),
    m2: str = Query("exato"),
    m3: str = Query("exato"),
    m4: str = Query("exato"),
    m5: str = Query("exato"),
    m6: str = Query("exato"),
    roulette_id: Optional[str] = Query(None),
    shuffled: bool = Query(False),
) -> Dict[str, Any]:
    def _parse_modes(raw: str) -> List[str]:
        items = [p.strip().lower() for p in (raw or "exato").split(",") if p.strip()]
        return items or ["exato"]

    pairs = [(n1, m1), (n2, m2), (n3, m3), (n4, m4), (n5, m5), (n6, m6)]
    fields: List[Dict[str, Any]] = []
    for value, mode_str in pairs:
        if value is None:
            break
        fields.append({"value": int(value), "modes": _parse_modes(mode_str)})

    try:
        return await sequence_search(fields, roulette_id=roulette_id, shuffled=shuffled)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha ao buscar sequencia: {exc}")
