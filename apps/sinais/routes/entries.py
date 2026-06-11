"""Rotas de geração e consulta de entradas."""

import asyncio
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Body, Depends, HTTPException

from sinais.core.auth import get_current_user
from sinais.core.config import settings
from sinais.core.db import entries_coll, history_coll
from sinais.core.roulettes import display_name
from sinais.services.credits import count_pending
from sinais.services.predictor import MIN_HISTORICO, gerar_de_historico_desc

router = APIRouter(prefix="/api")


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _serialize_result(result: dict | None) -> dict | None:
    if not result:
        return None
    out = dict(result)
    out["settled_at"] = _iso(out.get("settled_at"))
    return out


def _serialize_entry(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "roulette_id": doc["roulette_id"],
        "roulette_name": display_name(doc["roulette_id"]),
        "numbers": doc["numbers"],
        "size": doc.get("size", len(doc.get("numbers", []))),
        "arcos": doc.get("arcos"),
        "attempts": doc.get("attempts"),
        "status": doc["status"],
        "result": _serialize_result(doc.get("result")),
        "credit_delta": doc.get("credit_delta", 0),
        "created_at": _iso(doc.get("created_at")),
    }


@router.post("/entries")
async def create_entry(payload: dict = Body(default={}), user: dict = Depends(get_current_user)):
    roulette_id = (payload or {}).get("roulette_id")
    if roulette_id not in settings.allowed_roulettes:
        raise HTTPException(400, "mesa inválida")

    size = (payload or {}).get("size", settings.entry_numbers)
    try:
        size = int(size)
    except (TypeError, ValueError):
        raise HTTPException(400, "quantidade inválida")
    if size not in settings.allowed_entry_sizes:
        raise HTTPException(400, "quantidade inválida")

    user_id = user["clerk_user_id"]

    # Gate de crédito: disponível = créditos − pendentes
    pending = await count_pending(user_id)
    available = int(user.get("credits", 0)) - pending
    if available < 1:
        raise HTTPException(402, "créditos insuficientes")

    # No máximo 1 entrada pendente por mesa
    existing = await entries_coll.find_one(
        {"user_id": user_id, "roulette_id": roulette_id, "status": "pending"}
    )
    if existing:
        raise HTTPException(409, "já existe uma entrada pendente nesta mesa")

    # Últimos N números (mais recente primeiro)
    cursor = (
        history_coll
        .find({"roulette_id": roulette_id})
        .sort("timestamp", -1)
        .limit(settings.history_window)
    )
    docs = await cursor.to_list(length=settings.history_window)
    if len(docs) < MIN_HISTORICO:
        raise HTTPException(422, "histórico insuficiente para esta mesa")

    numeros_desc = [int(d["value"]) for d in docs]
    anchor_ts = docs[0]["timestamp"]
    # A busca de setores é CPU-bound (~200ms); roda fora do event loop.
    gen = await asyncio.to_thread(
        gerar_de_historico_desc, numeros_desc, qtd=size, janela=settings.attempts
    )

    entry = {
        "user_id": user_id,
        "roulette_id": roulette_id,
        "numbers": gen["numbers"],
        "size": size,
        "arcos": gen.get("arcos"),
        "attempts": settings.attempts,
        "anchor_timestamp": anchor_ts,
        "status": "pending",
        "result": None,
        "credit_delta": 0,
        "created_at": datetime.now(timezone.utc),
    }
    res = await entries_coll.insert_one(entry)
    entry["_id"] = res.inserted_id
    return _serialize_entry(entry)


@router.get("/entries")
async def list_entries(user: dict = Depends(get_current_user), limit: int = 50):
    limit = max(1, min(limit, 200))
    cursor = (
        entries_coll
        .find({"user_id": user["clerk_user_id"]})
        .sort("created_at", -1)
        .limit(limit)
    )
    docs = await cursor.to_list(length=limit)
    return [_serialize_entry(d) for d in docs]


@router.get("/entries/{entry_id}")
async def get_entry(entry_id: str, user: dict = Depends(get_current_user)):
    try:
        oid = ObjectId(entry_id)
    except (InvalidId, TypeError):
        raise HTTPException(400, "id inválido")
    doc = await entries_coll.find_one({"_id": oid, "user_id": user["clerk_user_id"]})
    if not doc:
        raise HTTPException(404, "entrada não encontrada")
    return _serialize_entry(doc)
