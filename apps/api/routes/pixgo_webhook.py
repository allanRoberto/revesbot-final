from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from pymongo.errors import DuplicateKeyError

from api.core.config import settings
from api.core.runtime_db import billing_db


router = APIRouter(prefix="/webhooks", tags=["pixgo"])
logger = logging.getLogger(__name__)

# A PixGo pode reenviar o mesmo evento horas depois da confirmação. A
# assinatura HMAC continua obrigatória e a coleção de eventos impede replay.
WEBHOOK_TOLERANCE_SECONDS = 24 * 60 * 60

payment_orders_coll = billing_db["commission_payment_orders"]
automation_invoices_coll = billing_db["automation_invoices"]
billing_accounts_coll = billing_db["automation_billing_accounts"]
automation_runs_coll = billing_db["automation_runs"]
webhook_events_coll = billing_db["payment_webhook_events"]

_indexes_ready = False


async def _ensure_indexes() -> None:
    global _indexes_ready
    if _indexes_ready:
        return
    await webhook_events_coll.create_index(
        [("eventKey", 1)],
        unique=True,
    )
    _indexes_ready = True


def _signature_error(
    raw_body: bytes,
    timestamp: str,
    signature: str,
    secret: str,
    *,
    now: float | None = None,
) -> str | None:
    if not timestamp or not signature or not secret:
        return "missing_signature_data"
    if len(signature) != 64:
        return "invalid_signature_format"
    try:
        event_time = int(timestamp)
        int(signature, 16)
    except (TypeError, ValueError):
        return "invalid_signature_format"
    current_time = time.time() if now is None else now
    if abs(current_time - event_time) > WEBHOOK_TOLERANCE_SECONDS:
        return "timestamp_outside_tolerance"
    message = timestamp.encode("utf-8") + b"." + raw_body
    expected = hmac.new(
        secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature.lower()):
        return "signature_mismatch"
    return None


def _verify_signature(
    raw_body: bytes,
    timestamp: str,
    signature: str,
    secret: str,
    *,
    now: float | None = None,
) -> bool:
    return _signature_error(
        raw_body,
        timestamp,
        signature,
        secret,
        now=now,
    ) is None


async def _get_pixgo_status(payment_id: str) -> dict[str, Any]:
    api_key = settings.pixgo_api_key
    if not api_key:
        raise HTTPException(status_code=503, detail="PIXGO_API_KEY não configurada.")
    base_url = (settings.pixgo_base_url or "https://pixgo.org/api/v1").rstrip("/")
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{base_url}/payment/{payment_id}/status",
            headers={"X-API-Key": api_key},
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail="Resposta inválida da PixGo.",
        ) from exc
    data = payload.get("data") if isinstance(payload, dict) else None
    if response.status_code >= 400 or not payload.get("success") or not isinstance(data, dict):
        message = (
            payload.get("message")
            or payload.get("error")
            or f"PixGo respondeu {response.status_code}"
        )
        raise HTTPException(status_code=502, detail=str(message))
    return data


def _amount_cents(value: Any) -> int:
    try:
        return round(float(value) * 100)
    except (TypeError, ValueError):
        return -1


@router.post("/pixgo")
async def pixgo_webhook(request: Request) -> dict[str, Any]:
    raw_body = await request.body()
    timestamp = request.headers.get("x-webhook-timestamp", "")
    signature = request.headers.get("x-webhook-signature", "")
    secret = settings.pixgo_webhook_secret or ""
    signature_error = _signature_error(
        raw_body,
        timestamp,
        signature,
        secret,
    )
    if signature_error:
        logger.warning(
            "PixGo webhook rejeitado | motivo=%s",
            signature_error,
        )
        raise HTTPException(status_code=401, detail="Assinatura inválida.")

    try:
        payload = json.loads(raw_body)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Payload inválido.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload inválido.")

    data = payload.get("data")
    if not isinstance(data, dict):
        data = payload
    event = str(
        payload.get("event")
        or request.headers.get("x-webhook-event", "")
    )
    payment_id = str(data.get("payment_id") or payload.get("payment_id") or "")
    external_id = str(data.get("external_id") or payload.get("external_id") or "")
    if not event or not payment_id:
        raise HTTPException(status_code=400, detail="Evento incompleto.")

    await _ensure_indexes()
    event_key = f"{event}:{payment_id}:{timestamp}"
    if await webhook_events_coll.find_one({"eventKey": event_key}):
        return {"received": True, "duplicate": True}

    order = await payment_orders_coll.find_one(
        {"providerPaymentId": payment_id}
    )
    if not order or (external_id and order.get("externalId") != external_id):
        raise HTTPException(status_code=404, detail="Cobrança não reconhecida.")

    now = datetime.now(timezone.utc)

    if event == "payment.completed":
        confirmed = await _get_pixgo_status(payment_id)
        if (
            str(confirmed.get("status") or "") != "completed"
            or str(confirmed.get("external_id") or "") != order.get("externalId")
            or _amount_cents(confirmed.get("amount")) != order.get("amountCents")
        ):
            raise HTTPException(status_code=409, detail="Confirmação divergente.")

        await payment_orders_coll.update_one(
            {
                "orderId": order["orderId"],
                "status": {"$in": ["pending", "expired"]},
            },
            {
                "$set": {
                    "status": "completed",
                    "paidAt": now,
                    "atualizadoEm": now,
                }
            },
        )
        invoice_id = order.get("invoiceId")
        if invoice_id:
            await automation_invoices_coll.update_one(
                {
                    "invoiceId": invoice_id,
                    "email": order["email"],
                    "status": {"$in": ["pending", "awaiting_payment"]},
                },
                {
                    "$set": {
                        "status": "paid",
                        "paidAt": now,
                        "atualizadoEm": now,
                    }
                },
            )
        run_id = order.get("runId")
        if run_id:
            await billing_accounts_coll.update_one(
                {
                    "email": order["email"],
                    "activeRunId": run_id,
                },
                {
                    "$set": {
                        "status": "clear",
                        "outstandingCents": 0,
                        "atualizadoEm": now,
                    },
                    "$unset": {"activeRunId": ""},
                },
            )
            await automation_runs_coll.update_one(
                {"runId": run_id, "status": "payment_due"},
                {"$set": {"status": "completed", "atualizadoEm": now}},
            )

    elif event == "payment.expired":
        changed = await payment_orders_coll.update_one(
            {"orderId": order["orderId"], "status": "pending"},
            {"$set": {"status": "expired", "atualizadoEm": now}},
        )
        if changed.modified_count > 0:
            invoice_id = order.get("invoiceId")
            if invoice_id:
                await automation_invoices_coll.update_one(
                    {
                        "invoiceId": invoice_id,
                        "status": "awaiting_payment",
                    },
                    {
                        "$set": {
                            "status": "pending",
                            "atualizadoEm": now,
                        }
                    },
                )
            if order.get("runId"):
                await billing_accounts_coll.update_one(
                    {"email": order["email"]},
                    {
                        "$set": {
                            "status": "payment_due",
                            "atualizadoEm": now,
                        }
                    },
                )

    elif event == "payment.refunded":
        changed = await payment_orders_coll.update_one(
            {"orderId": order["orderId"], "status": "completed"},
            {"$set": {"status": "refunded", "atualizadoEm": now}},
        )
        if changed.modified_count > 0:
            invoice_id = order.get("invoiceId")
            if invoice_id:
                await automation_invoices_coll.update_one(
                    {"invoiceId": invoice_id},
                    {
                        "$set": {
                            "status": "pending",
                            "atualizadoEm": now,
                        },
                        "$unset": {"paidAt": ""},
                    },
                )
            run_id = order.get("runId")
            if run_id:
                await billing_accounts_coll.update_one(
                    {"email": order["email"]},
                    {
                        "$set": {
                            "status": "payment_due",
                            "outstandingCents": order["amountCents"],
                            "activeRunId": run_id,
                            "atualizadoEm": now,
                        }
                    },
                    upsert=True,
                )
                await automation_runs_coll.update_one(
                    {"runId": run_id},
                    {"$set": {"status": "payment_due", "atualizadoEm": now}},
                )

    try:
        await webhook_events_coll.insert_one(
            {
                "eventKey": event_key,
                "provider": "pixgo",
                "event": event,
                "providerPaymentId": payment_id,
                "externalId": external_id or None,
                "payload": payload,
                "recebidoEm": now,
            }
        )
    except DuplicateKeyError:
        return {"received": True, "duplicate": True}

    return {"received": True}
