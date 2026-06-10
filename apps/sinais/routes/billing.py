"""Saldo do usuário e checkout de créditos (Stripe)."""

import asyncio

from fastapi import APIRouter, Body, Depends, HTTPException

from sinais.core.auth import get_current_user
from sinais.core.config import settings
from sinais.services.credits import count_pending

router = APIRouter(prefix="/api")

# Pacotes de crédito. Os price_id precisam ser criados no painel do Stripe
# (ver Pendências no plano). Enquanto vazios, o checkout responde 503.
CREDIT_PACKS: dict[str, dict] = {
    "p10": {"credits": 10, "price_id": None},
    "p50": {"credits": 50, "price_id": None},
    "p100": {"credits": 100, "price_id": None},
}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    pending = await count_pending(user["clerk_user_id"])
    credits = int(user.get("credits", 0))
    return {
        "clerk_user_id": user["clerk_user_id"],
        "email": user.get("email"),
        "credits": credits,
        "pending": pending,
        "available": credits - pending,
    }


@router.get("/packs")
async def list_packs():
    return [
        {"id": pid, "credits": p["credits"], "available": bool(p["price_id"])}
        for pid, p in CREDIT_PACKS.items()
    ]


@router.post("/checkout")
async def checkout(payload: dict = Body(default={}), user: dict = Depends(get_current_user)):
    if not settings.stripe_secret_key:
        raise HTTPException(503, "pagamentos não configurados")

    pack = CREDIT_PACKS.get((payload or {}).get("pack"))
    if not pack:
        raise HTTPException(400, "pacote inválido")
    if not pack["price_id"]:
        raise HTTPException(503, "pacote sem preço configurado no Stripe")

    import stripe

    stripe.api_key = settings.stripe_secret_key
    user_id = user["clerk_user_id"]

    def _create_session():
        return stripe.checkout.Session.create(
            mode="payment",
            line_items=[{"price": pack["price_id"], "quantity": 1}],
            success_url=f"{settings.sinais_app_url}/app?paid=1",
            cancel_url=f"{settings.sinais_app_url}/app?canceled=1",
            client_reference_id=user_id,
            metadata={"clerk_user_id": user_id, "credits": str(pack["credits"])},
        )

    try:
        session = await asyncio.to_thread(_create_session)
    except Exception:
        raise HTTPException(502, "falha ao criar sessão de pagamento")
    return {"url": session.url}
