"""Read the published trio catalog without calculating or changing rankings."""
from __future__ import annotations

import math
import re


class CatalogNotFound(LookupError):
    pass


class CatalogUnavailable(RuntimeError):
    pass


def parse_numbers(raw: str) -> list[int]:
    parts = raw.split(",")
    if len(parts) != 3 or any(not re.fullmatch(r"[0-9]{1,2}", part.strip()) for part in parts):
        raise ValueError("Informe exatamente três números inteiros separados por vírgula.")
    numbers = [int(part.strip()) for part in parts]
    if any(number > 36 for number in numbers) or len(set(numbers)) != 3:
        raise ValueError("Os três números devem ser distintos e estar entre 0 e 36.")
    return numbers


async def get_triple_context_ranking(db, *, numbers: list[int], direction: str,
                                     ordered: bool, input_order: str, roulette_id: str) -> dict:
    chronological = list(reversed(numbers)) if input_order == "latest_first" else list(numbers)
    combination = chronological if ordered else sorted(numbers)
    mode = "ordered" if ordered else "unordered"
    key = ",".join(map(str, combination))
    active = await db["triple_context_active_v1"].find_one(
        {"_id": roulette_id}, {"_id": 0, "build_id": 1})
    if active is None:
        raise CatalogNotFound("Nenhum catálogo publicado para esta roleta.")
    build_id = active.get("build_id")
    if not isinstance(build_id, str) or not build_id:
        raise CatalogUnavailable("O catálogo está temporariamente indisponível.")
    # Keep a single build ID for the whole request, even if another version is published.
    manifest = await db["triple_context_builds_v1"].find_one(
        {"_id": build_id, "roulette_id": roulette_id},
        {"_id": 0, "status": 1, "source.records": 1,
         "source.first_timestamp": 1, "source.last_timestamp": 1})
    if manifest is None or manifest.get("status") not in {"verified", "ready"}:
        raise CatalogUnavailable("O catálogo ativo ainda não está disponível para consulta.")
    document = await db["triple_context_rankings_v1"].find_one(
        {"build_id": build_id, "roulette_id": roulette_id, "mode": mode, "key": key},
        {"_id": 0, "key": 1, "combination": 1, "occurrences": 1, direction: 1})
    if document is None:
        # All combinations, including those with zero evidence, must exist in a valid build.
        raise CatalogUnavailable("A combinação está ausente do catálogo publicado.")
    try:
        side = document[direction]
        ranking = side["ranking"]
        depth = 20 if direction == "forward" else 10
        valid = (
            document["key"] == key and document["combination"] == combination
            and type(document["occurrences"]) is int and document["occurrences"] >= 0
            and side["depth"] == depth and len(side["position_counts"]) == depth
            and len(ranking) == 37 and {row["number"] for row in ranking} == set(range(37))
            and all(type(row["number"]) is int
                    and type(row["score"]) in (int, float) and math.isfinite(row["score"]) and row["score"] >= 0
                    and type(row["direct_hits"]) is int and row["direct_hits"] >= 0 for row in ranking)
        )
        if not valid:
            raise CatalogUnavailable("O catálogo retornou dados inconsistentes.")
        source = manifest["source"]
        return {
            "roulette_id": roulette_id, "requested_numbers": list(numbers),
            "input_order": input_order, "ordered": ordered, "direction": direction,
            "combination": combination, "key": key, "build_id": build_id,
            "occurrences": document["occurrences"], "has_evidence": side["context_events"] > 0,
            "depth": side["depth"], "context_events": side["context_events"],
            "complete_occurrences": side["complete_occurrences"],
            "position_counts": side["position_counts"],
            "ranking": [{"position": index, "number": row["number"],
                         "score": row["score"], "direct_hits": row["direct_hits"]}
                        for index, row in enumerate(ranking, 1)],
            "source": {name: source[name] for name in
                       ("records", "first_timestamp", "last_timestamp")},
        }
    except (KeyError, TypeError, ValueError) as error:
        raise CatalogUnavailable("O catálogo retornou dados inconsistentes.") from error
