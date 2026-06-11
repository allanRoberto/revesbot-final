"""Operações de crédito e ledger (auditoria de saldo)."""

from datetime import datetime, timezone
from typing import Any

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from sinais.core.config import settings
from sinais.core.db import entries_coll, ledger_coll, users_coll


def _now() -> datetime:
    return datetime.now(timezone.utc)


def serialize_user(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "clerk_user_id": doc.get("clerk_user_id"),
        "email": doc.get("email"),
        "credits": int(doc.get("credits", 0)),
    }


async def get_or_create_user(clerk_user_id: str, email: str | None = None) -> dict[str, Any]:
    """Retorna o usuário; cria com os créditos de boas-vindas na primeira vez."""
    user = await users_coll.find_one({"clerk_user_id": clerk_user_id})
    if user:
        # completa o e-mail se chegou agora (ex.: via webhook depois do lazy-create)
        if email and not user.get("email"):
            await users_coll.update_one(
                {"clerk_user_id": clerk_user_id},
                {"$set": {"email": email, "updated_at": _now()}},
            )
            user["email"] = email
        return user

    now = _now()
    doc = {
        "clerk_user_id": clerk_user_id,
        "email": email,
        "credits": settings.signup_credits,
        "purchase_count": 0,
        "created_at": now,
        "updated_at": now,
    }
    try:
        await users_coll.insert_one(doc)
    except DuplicateKeyError:
        # corrida: outro request criou primeiro — não dá bônus de novo
        return await users_coll.find_one({"clerk_user_id": clerk_user_id})

    await ledger_coll.insert_one({
        "user_id": clerk_user_id,
        "entry_id": None,
        "type": "signup_bonus",
        "amount": settings.signup_credits,
        "balance_after": settings.signup_credits,
        "created_at": now,
    })
    return doc


async def count_pending(clerk_user_id: str) -> int:
    return await entries_coll.count_documents({"user_id": clerk_user_id, "status": "pending"})


async def apply_credit_delta(
    clerk_user_id: str,
    delta: int,
    ledger_type: str,
    *,
    entry_id: Any = None,
    stripe_event_id: str | None = None,
) -> int:
    """Aplica +/- créditos de forma atômica e registra no ledger. Retorna o novo saldo."""
    now = _now()
    updated = await users_coll.find_one_and_update(
        {"clerk_user_id": clerk_user_id},
        {"$inc": {"credits": delta}, "$set": {"updated_at": now}},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise ValueError(f"usuário não encontrado: {clerk_user_id}")

    await ledger_coll.insert_one({
        "user_id": clerk_user_id,
        "entry_id": entry_id,
        "type": ledger_type,
        "amount": delta,
        "balance_after": int(updated["credits"]),
        "stripe_event_id": stripe_event_id,
        "created_at": now,
    })
    return int(updated["credits"])


async def record_purchase(
    clerk_user_id: str,
    credits: int,
    *,
    stripe_event_id: str | None = None,
    unit_price: float | None = None,
) -> int:
    """Credita um pacote comprado e incrementa o contador de compras (atômico).

    O contador (`purchase_count`) é o que faz o preço subir na próxima compra.
    Assume que o usuário já existe (o webhook chama get_or_create_user antes).
    """
    now = _now()
    updated = await users_coll.find_one_and_update(
        {"clerk_user_id": clerk_user_id},
        {"$inc": {"credits": credits, "purchase_count": 1}, "$set": {"updated_at": now}},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise ValueError(f"usuário não encontrado: {clerk_user_id}")

    await ledger_coll.insert_one({
        "user_id": clerk_user_id,
        "entry_id": None,
        "type": "purchase",
        "amount": credits,
        "balance_after": int(updated["credits"]),
        "stripe_event_id": stripe_event_id,
        "unit_price": unit_price,
        "created_at": now,
    })
    return int(updated["credits"])
