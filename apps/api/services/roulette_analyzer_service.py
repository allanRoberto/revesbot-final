from __future__ import annotations

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
    pipeline = [
        {
            "$group": {
                "_id": "$roulette_id",
                "name": {"$first": "$roulette_name"},
                "result_count": {"$sum": 1},
            }
        },
        {"$match": {"_id": {"$type": "string", "$ne": ""}}},
        {"$sort": {"name": 1, "_id": 1}},
    ]
    try:
        rows = await history_coll.aggregate(pipeline).to_list(length=500)
    except Exception as exc:
        raise RouletteHistoryUnavailableError from exc

    return [
        {
            "roulette_id": str(row["_id"]),
            "name": str(row.get("name") or row["_id"]),
            "result_count": int(row.get("result_count") or 0),
        }
        for row in rows
    ]
