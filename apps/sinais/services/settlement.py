"""Apuração das entradas (WIN/LOST) e ajuste de crédito.

Lógica única usada pelo worker. WIN debita 1 crédito; LOST credita 1.
A apuração só ocorre quando já existem `attempts` rodadas após a geração.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from sinais.core.config import settings
from sinais.core.db import entries_coll, history_coll
from sinais.services.credits import apply_credit_delta

log = logging.getLogger("settlement")


async def _next_spins(roulette_id: str, anchor_ts: Any, limit: int) -> list[int]:
    cursor = (
        history_coll
        .find({"roulette_id": roulette_id, "timestamp": {"$gt": anchor_ts}})
        .sort("timestamp", 1)
        .limit(limit)
    )
    docs = await cursor.to_list(length=limit)
    return [int(d["value"]) for d in docs]


async def settle_entry(entry: dict[str, Any]) -> bool:
    """Apura uma entrada. Retorna True se apurou agora, False se ainda não dá."""
    attempts = int(entry.get("attempts", settings.attempts))
    spins = await _next_spins(entry["roulette_id"], entry["anchor_timestamp"], attempts)
    if len(spins) < attempts:
        return False  # rodadas insuficientes ainda

    numbers = set(entry["numbers"])
    hit_number = None
    hit_attempt = None
    for i, v in enumerate(spins, start=1):
        if v in numbers:
            hit_number, hit_attempt = v, i
            break

    status = "win" if hit_number is not None else "lost"
    delta = -1 if status == "win" else 1
    now = datetime.now(timezone.utc)

    # flip atômico: só processa se ainda estiver pending (idempotência entre workers)
    claimed = await entries_coll.find_one_and_update(
        {"_id": entry["_id"], "status": "pending"},
        {"$set": {
            "status": status,
            "credit_delta": delta,
            "result": {
                "hit_number": hit_number,
                "hit_attempt": hit_attempt,
                "spins": spins,
                "settled_at": now,
            },
            "settled_at": now,
        }},
    )
    if claimed is None:
        return False  # outro worker já apurou

    ledger_type = "win_debit" if status == "win" else "lost_refund"
    try:
        await apply_credit_delta(entry["user_id"], delta, ledger_type, entry_id=entry["_id"])
    except Exception:
        # entrada já foi marcada como apurada (credit_delta gravado);
        # log para reconciliação manual em vez de reprocessar.
        log.exception("falha ao aplicar crédito da entry %s", entry["_id"])
    return True


async def settle_pending_once(limit: int = 200) -> int:
    """Varre as entradas pendentes e apura as que já têm rodadas suficientes."""
    cursor = entries_coll.find({"status": "pending"}).limit(limit)
    settled = 0
    async for entry in cursor:
        try:
            if await settle_entry(entry):
                settled += 1
        except Exception:
            log.exception("erro apurando entry %s", entry.get("_id"))
            continue
    return settled
