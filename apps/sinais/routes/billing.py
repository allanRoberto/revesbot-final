"""Saldo do usuário e checkout de créditos (Stripe) com preço progressivo."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from sinais.core.auth import get_current_user
from sinais.core.config import settings
from sinais.services import pricing
from sinais.services.credits import count_pending

router = APIRouter(prefix="/api")


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    pending = await count_pending(user["clerk_user_id"])
    credits = int(user.get("credits", 0))
    purchase_count = int(user.get("purchase_count", 0))
    return {
        "clerk_user_id": user["clerk_user_id"],
        "email": user.get("email"),
        "credits": credits,
        "pending": pending,
        "available": credits - pending,
        "purchase_count": purchase_count,
        "next_pack": pricing.offer(purchase_count),
    }


@router.get("/packs")
async def current_pack(user: dict = Depends(get_current_user)):
    """Próxima compra do usuário (preço já considerando as compras anteriores)."""
    return pricing.offer(int(user.get("purchase_count", 0)))


@router.post("/checkout")
async def checkout(user: dict = Depends(get_current_user)):
    if not settings.stripe_secret_key:
        raise HTTPException(503, "pagamentos não configurados")

    user_id = user["clerk_user_id"]
    n = int(user.get("purchase_count", 0))
    unit_cents = pricing.unit_price_cents(n)

    import stripe

    stripe.api_key = settings.stripe_secret_key

    def _create_session():
        return stripe.checkout.Session.create(
            mode="payment",
            line_items=[{
                "price_data": {
                    "currency": settings.currency,
                    "unit_amount": unit_cents,
                    "product_data": {"name": f"{settings.credit_pack_size} créditos — Revesbot Sinais"},
                },
                "quantity": settings.credit_pack_size,
            }],
            success_url=f"{settings.sinais_app_url}/app?paid=1",
            cancel_url=f"{settings.sinais_app_url}/app?canceled=1",
            client_reference_id=user_id,
            metadata={
                "clerk_user_id": user_id,
                "credits": str(settings.credit_pack_size),
                "purchase_index": str(n),
                "unit_price": f"{pricing.unit_price(n):.2f}",
            },
        )

    try:
        session = await asyncio.to_thread(_create_session)
    except Exception:
        raise HTTPException(502, "falha ao criar sessão de pagamento")
    return {"url": session.url}
