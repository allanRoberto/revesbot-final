from __future__ import annotations

import re
from typing import Any

from api.core.runtime_db import history_coll
from gatilhos.roulette_analyzer import analyze


class RouletteHistoryNotFoundError(LookupError):
    """A roleta solicitada não possui resultados armazenados."""


class RouletteHistoryUnavailableError(RuntimeError):
    """O histórico não pôde ser consultado."""


async def analyze_roulette(roulette_id: str, quantidade: int) -> dict[str, Any]:
    """Carrega o histórico e delega todo o cálculo ao roulette_analyzer."""
    normalized_roulette_id = roulette_id.strip()
    try:
        docs = await (
            history_coll.find(
                {"roulette_id": normalized_roulette_id},
                {"_id": 0, "value": 1},
            )
            .sort("timestamp", -1)
            .limit(quantidade)
            .to_list(length=quantidade)
        )
    except Exception as exc:
        raise RouletteHistoryUnavailableError from exc

    history = [doc.get("value") for doc in docs]
    if not history:
        raise RouletteHistoryNotFoundError(normalized_roulette_id)

    # Fonte única de verdade: não há cálculo, ranking ou pós-processamento aqui.
    analysis = analyze(history)
    numeros_fortes = list(analysis["numeros_fortes"])
    gatilhos = list(analysis["gatilhos"])
    return {
        "roulette_id": normalized_roulette_id,
        "quantidade_solicitada": quantidade,
        "quantidade_analisada": len(history),
        "numeros_fortes": numeros_fortes,
        "numeros_puxando": numeros_fortes,
        "gatilhos": gatilhos,
    }


async def list_analyzer_roulettes() -> list[dict[str, Any]]:
    """Lista diretamente do histórico as roletas disponíveis para a página."""
    try:
        roulette_ids = await history_coll.distinct("roulette_id")
    except Exception as exc:
        raise RouletteHistoryUnavailableError from exc

    normalized_ids = sorted(
        value
        for value in roulette_ids
        if isinstance(value, str) and re.fullmatch(r"[a-z0-9][a-z0-9-]*", value)
    )
    return [
        {
            "roulette_id": roulette_id,
            "name": roulette_id.replace("-", " ").title(),
            "result_count": None,
        }
        for roulette_id in normalized_ids
    ]
