"""Webhooks de Clerk (novo usuário → 5 créditos) e Stripe (compra → créditos)."""

import logging

from fastapi import APIRouter, Header, HTTPException, Request
from pymongo.errors import DuplicateKeyError

from sinais.core.config import settings
from sinais.core.db import payments_coll
from sinais.services.credits import apply_credit_delta, get_or_create_user

router = APIRouter(prefix="/webhooks")
log = logging.getLogger("webhooks")


@router.post("/clerk")
async def clerk_webhook(request: Request):
    if not settings.clerk_webhook_secret:
        raise HTTPException(503, "clerk webhook não configurado")

    payload = await request.body()
    try:
        from svix.webhooks import Webhook
    except ImportError:
        raise HTTPException(503, "dependência svix não instalada")

    try:
        wh = Webhook(settings.clerk_webhook_secret)
        evt = wh.verify(payload, {
            "svix-id": request.headers.get("svix-id"),
            "svix-timestamp": request.headers.get("svix-timestamp"),
            "svix-signature": request.headers.get("svix-signature"),
        })
    except Exception:
        raise HTTPException(400, "assinatura inválida")

    if evt.get("type") == "user.created":
        data = evt.get("data", {})
        uid = data.get("id")
        email = None
        emails = data.get("email_addresses") or []
        if emails:
            email = emails[0].get("email_address")
        if uid:
            await get_or_create_user(uid, email)

    return {"ok": True}


@router.post("/stripe")
async def stripe_webhook(request: Request, stripe_signature: str = Header(default=None)):
    if not (settings.stripe_secret_key and settings.stripe_webhook_secret):
        raise HTTPException(503, "stripe não configurado")

    import stripe

    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, settings.stripe_webhook_secret
        )
    except Exception:
        raise HTTPException(400, "assinatura inválida")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        event_id = event["id"]

        # idempotência: primeira gravação vence; reentrega vira no-op
        try:
            await payments_coll.insert_one({
                "event_id": event_id,
                "type": event["type"],
                "payment_status": session.get("payment_status"),
            })
        except DuplicateKeyError:
            return {"ok": True, "duplicate": True}

        metadata = session.get("metadata") or {}
        uid = session.get("client_reference_id") or metadata.get("clerk_user_id")
        try:
            credits = int(metadata.get("credits", 0))
        except (TypeError, ValueError):
            credits = 0

        if uid and credits > 0:
            await get_or_create_user(uid)
            await apply_credit_delta(uid, credits, "purchase", stripe_event_id=event_id)
        else:
            log.warning("checkout.session.completed sem uid/credits: %s", event_id)

    return {"ok": True}
