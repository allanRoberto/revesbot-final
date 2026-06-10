"""Conexão MongoDB (motor) e coleções do app de sinais.

Reaproveita o cluster da API interna (`roleta_db`). A coleção `history`
é usada apenas para leitura; o restante (`sinais_*`) é deste app.
"""

import asyncio

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import OperationFailure

from sinais.core.config import settings

mongo_client = AsyncIOMotorClient(settings.mongo_url, tls=False)
mongo_db = mongo_client["roleta_db"]

# Leitura (compartilhada com a API interna / collector)
history_coll = mongo_db["history"]

# Coleções deste app
users_coll = mongo_db["sinais_users"]
entries_coll = mongo_db["sinais_entries"]
ledger_coll = mongo_db["sinais_ledger"]
payments_coll = mongo_db["sinais_payments"]

_indexes_ready = False
_indexes_lock = asyncio.Lock()


async def ensure_indexes() -> None:
    """Cria os índices das coleções sinais_* (idempotente)."""
    global _indexes_ready
    if _indexes_ready:
        return
    async with _indexes_lock:
        if _indexes_ready:
            return
        try:
            await users_coll.create_index(
                [("clerk_user_id", ASCENDING)], name="clerk_user_id_unique", unique=True
            )
            await entries_coll.create_index(
                [("user_id", ASCENDING), ("status", ASCENDING)], name="user_status"
            )
            await entries_coll.create_index(
                [("user_id", ASCENDING), ("created_at", DESCENDING)], name="user_created"
            )
            await entries_coll.create_index(
                [("roulette_id", ASCENDING), ("status", ASCENDING)], name="roulette_status"
            )
            await ledger_coll.create_index(
                [("user_id", ASCENDING), ("created_at", DESCENDING)], name="ledger_user"
            )
            await payments_coll.create_index(
                [("event_id", ASCENDING)], name="event_id_unique", unique=True
            )
        except OperationFailure:
            # Índices já existentes com outra config não devem derrubar o boot.
            pass
        _indexes_ready = True
