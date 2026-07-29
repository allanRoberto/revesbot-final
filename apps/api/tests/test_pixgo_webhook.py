from __future__ import annotations

import asyncio
import hashlib
import hmac
import json

import pytest
from fastapi import HTTPException

from api.routes import pixgo_webhook


class _UpdateResult:
    def __init__(self, modified_count: int = 1):
        self.modified_count = modified_count


class _FakeCollection:
    def __init__(self, find_result=None):
        self.find_result = find_result
        self.updates: list[tuple] = []
        self.inserts: list[dict] = []

    async def find_one(self, query):
        return self.find_result

    async def update_one(self, *args, **kwargs):
        self.updates.append((args, kwargs))
        return _UpdateResult()

    async def insert_one(self, document):
        self.inserts.append(document)
        return object()

    async def create_index(self, *args, **kwargs):
        return "pixgo_event_key_unique"


class _FakeRequest:
    def __init__(self, raw_body: bytes, headers: dict[str, str]):
        self._raw_body = raw_body
        self.headers = headers

    async def body(self):
        return self._raw_body


def _signature(secret: str, timestamp: str, raw_body: bytes) -> str:
    return hmac.new(
        secret.encode(),
        timestamp.encode() + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()


def test_verify_signature_rejects_replay() -> None:
    raw = b'{"event":"payment.completed"}'
    secret = "whsec_test"
    timestamp = "1000"
    signature = _signature(secret, timestamp, raw)

    assert pixgo_webhook._verify_signature(
        raw,
        timestamp,
        signature,
        secret,
        now=1301,
    ) is False


def test_completed_payment_clears_billing(monkeypatch) -> None:
    secret = "whsec_test"
    timestamp = "1700000000"
    payload = {
        "event": "payment.completed",
        "data": {
            "payment_id": "pay_1",
            "external_id": "revesbot_order_1",
        },
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    request = _FakeRequest(
        raw,
        {
            "x-webhook-timestamp": timestamp,
            "x-webhook-signature": _signature(secret, timestamp, raw),
            "x-webhook-event": "payment.completed",
        },
    )
    order = {
        "orderId": "order_1",
        "providerPaymentId": "pay_1",
        "externalId": "revesbot_order_1",
        "amountCents": 2500,
        "email": "cliente@example.com",
        "runId": "run_1",
        "status": "pending",
    }
    orders = _FakeCollection(order)
    billing = _FakeCollection()
    runs = _FakeCollection()
    events = _FakeCollection()

    async def fake_ensure_indexes():
        return None

    async def fake_status(_payment_id):
        return {
            "payment_id": "pay_1",
            "external_id": "revesbot_order_1",
            "amount": 25.00,
            "status": "completed",
        }

    monkeypatch.setattr(pixgo_webhook.settings, "pixgo_webhook_secret", secret)
    monkeypatch.setattr(pixgo_webhook, "payment_orders_coll", orders)
    monkeypatch.setattr(pixgo_webhook, "billing_accounts_coll", billing)
    monkeypatch.setattr(pixgo_webhook, "automation_runs_coll", runs)
    monkeypatch.setattr(pixgo_webhook, "webhook_events_coll", events)
    monkeypatch.setattr(pixgo_webhook, "_ensure_indexes", fake_ensure_indexes)
    monkeypatch.setattr(pixgo_webhook, "_get_pixgo_status", fake_status)
    monkeypatch.setattr(pixgo_webhook.time, "time", lambda: 1700000000)

    result = asyncio.run(pixgo_webhook.pixgo_webhook(request))

    assert result == {"received": True}
    assert orders.updates[0][0][1]["$set"]["status"] == "completed"
    assert billing.updates[0][0][1]["$set"]["outstandingCents"] == 0
    assert billing.updates[0][0][1]["$set"]["status"] == "clear"
    assert runs.updates[0][0][1]["$set"]["status"] == "completed"
    assert events.inserts[0]["eventKey"].startswith("payment.completed:pay_1:")


def test_invalid_signature_returns_401(monkeypatch) -> None:
    monkeypatch.setattr(
        pixgo_webhook.settings,
        "pixgo_webhook_secret",
        "whsec_test",
    )
    request = _FakeRequest(
        b"{}",
        {
            "x-webhook-timestamp": "1700000000",
            "x-webhook-signature": "0" * 64,
        },
    )
    monkeypatch.setattr(pixgo_webhook.time, "time", lambda: 1700000000)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(pixgo_webhook.pixgo_webhook(request))

    assert exc.value.status_code == 401


def test_completed_activation_invoice_does_not_require_run(monkeypatch) -> None:
    secret = "whsec_test"
    timestamp = "1700000000"
    payload = {
        "event": "payment.completed",
        "data": {
            "payment_id": "pay_activation",
            "external_id": "revesbot_activation",
        },
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    request = _FakeRequest(
        raw,
        {
            "x-webhook-timestamp": timestamp,
            "x-webhook-signature": _signature(secret, timestamp, raw),
        },
    )
    order = {
        "orderId": "order_activation",
        "invoiceId": "invoice_activation",
        "providerPaymentId": "pay_activation",
        "externalId": "revesbot_activation",
        "amountCents": 3000,
        "email": "cliente@example.com",
        "status": "pending",
    }
    orders = _FakeCollection(order)
    invoices = _FakeCollection()
    billing = _FakeCollection()
    runs = _FakeCollection()
    events = _FakeCollection()

    async def fake_ensure_indexes():
        return None

    async def fake_status(_payment_id):
        return {
            "payment_id": "pay_activation",
            "external_id": "revesbot_activation",
            "amount": 30.00,
            "status": "completed",
        }

    monkeypatch.setattr(pixgo_webhook.settings, "pixgo_webhook_secret", secret)
    monkeypatch.setattr(pixgo_webhook, "payment_orders_coll", orders)
    monkeypatch.setattr(pixgo_webhook, "automation_invoices_coll", invoices)
    monkeypatch.setattr(pixgo_webhook, "billing_accounts_coll", billing)
    monkeypatch.setattr(pixgo_webhook, "automation_runs_coll", runs)
    monkeypatch.setattr(pixgo_webhook, "webhook_events_coll", events)
    monkeypatch.setattr(pixgo_webhook, "_ensure_indexes", fake_ensure_indexes)
    monkeypatch.setattr(pixgo_webhook, "_get_pixgo_status", fake_status)
    monkeypatch.setattr(pixgo_webhook.time, "time", lambda: 1700000000)

    result = asyncio.run(pixgo_webhook.pixgo_webhook(request))

    assert result == {"received": True}
    assert invoices.updates[0][0][1]["$set"]["status"] == "paid"
    assert billing.updates == []
    assert runs.updates == []
