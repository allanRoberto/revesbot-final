from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient

from api.core.config import settings


def _client(url: str | None) -> AsyncIOMotorClient:
    return AsyncIOMotorClient(url or "mongodb://127.0.0.1:27017", tls=False)


history_mongo_client = _client(settings.mongo_url)
history_db = history_mongo_client[settings.mongo_database or "roleta_db"]
history_coll = history_db["history"]

_billing_url = settings.pixgo_mongo_url or settings.mongo_url
billing_mongo_client = (
    history_mongo_client
    if _billing_url == settings.mongo_url
    else _client(_billing_url)
)
billing_db = billing_mongo_client[
    settings.pixgo_mongo_database or "roleta_db"
]


async def ping_runtime_dependencies() -> None:
    await history_db.command("ping")
    await billing_db.command("ping")


__all__ = [
    "billing_db",
    "billing_mongo_client",
    "history_coll",
    "history_db",
    "history_mongo_client",
    "ping_runtime_dependencies",
]
