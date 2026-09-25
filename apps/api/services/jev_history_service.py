"""Ordered MongoDB history adapter for the fixed Jev roulette."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


ROULETTE_SLUG = "pragmatic-auto-roulette"


class JevHistorySourceError(RuntimeError):
    """The configured history source failed or returned an invalid record."""


def utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


async def fetch_recent_history(collection: Any, quantity: int) -> dict[str, Any]:
    """Select newest N records, then return their numbers oldest-to-newest."""
    try:
        cursor = collection.find(
            {"roulette_id": ROULETTE_SLUG},
            {"value": 1, "timestamp": 1},
        )
        cursor = cursor.sort([("timestamp", -1), ("_id", -1)]).limit(quantity)
        docs = await cursor.to_list(length=quantity)
    except Exception as exc:
        raise JevHistorySourceError("Não foi possível consultar o histórico da roleta.") from exc

    newest_timestamp: str | None = None
    if docs:
        timestamp = docs[0].get("timestamp")
        if timestamp is not None:
            if not isinstance(timestamp, datetime):
                raise JevHistorySourceError("A fonte retornou um horário de resultado inválido.")
            newest_timestamp = utc_iso(timestamp)

    newest_first: list[int] = []
    for index, document in enumerate(docs, start=1):
        value = document.get("value")
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 36:
            raise JevHistorySourceError(
                f"A fonte retornou um número de roleta inválido no registro {index}."
            )
        newest_first.append(value)

    return {
        "roulette_slug": ROULETTE_SLUG,
        "quantidade_solicitada": quantity,
        "quantidade_retornada": len(newest_first),
        "history_order": "oldest_to_newest",
        "historico": list(reversed(newest_first)),
        "buscado_em": utc_iso(datetime.now(timezone.utc)),
        "ultimo_resultado_em": newest_timestamp,
    }
