"""Retrospective evaluation of the published catalog; never calculates ranking weights."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
from datetime import datetime, timezone

from api.services.triple_backtest_evaluation import evaluate_signals
from api.services.triple_context_ranking_service import CatalogNotFound, CatalogUnavailable

ROULETTE = "pragmatic-auto-roulette"


def _utc(value):
    if not isinstance(value, datetime):
        raise CatalogUnavailable("O histórico contém uma data inválida. Nenhum resultado foi descartado.")
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _catalog_date(value):
    try:
        return _utc(value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00")))
    except (AttributeError, TypeError, ValueError) as error:
        raise CatalogUnavailable("As datas do catálogo estão inconsistentes.") from error


def normalize_history(documents, requested_records):
    """Reverse the database's descending order without dropping or compressing rows."""
    rows = []
    ids, games = set(), set()
    previous = None
    gaps, maximum_gap = 0, 0.0
    digest = hashlib.sha256()
    for document in reversed(documents):
        value = document.get("value")
        if type(value) is not int or not 0 <= value <= 36 or document.get("roulette_id") != ROULETTE:
            raise CatalogUnavailable("O histórico contém um resultado inválido. Nenhum resultado foi descartado.")
        timestamp = _utc(document.get("timestamp"))
        identity = str(document["_id"])
        external = document.get("external_game_id")
        if identity in ids or (external is not None and str(external) in games):
            raise CatalogUnavailable("O histórico contém resultados duplicados. Nenhum resultado foi descartado.")
        ids.add(identity)
        if external is not None:
            games.add(str(external))
        if previous is not None:
            gap = (timestamp - previous).total_seconds()
            if gap < 0:
                raise CatalogUnavailable("A ordem temporal do histórico está inconsistente.")
            gaps += gap > 300
            maximum_gap = max(maximum_gap, gap)
        previous = timestamp
        row = {"value": value, "timestamp": timestamp.isoformat(), "source_id": identity}
        digest.update((json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode())
        rows.append(row)
    return rows, {
        "records": len(rows), "requested_records": requested_records,
        "first_timestamp": rows[0]["timestamp"] if rows else None,
        "last_timestamp": rows[-1]["timestamp"] if rows else None,
        "read_at": datetime.now(timezone.utc).isoformat(),
        "gaps_over_300_seconds": gaps, "maximum_gap_seconds": maximum_gap,
        "content_sha256": digest.hexdigest(), "records_discarded": 0,
        "continuity": "Registros coletados consecutivos; giros ausentes não são reconstruídos.",
    }


def trio_key(trio, ordered):
    return ",".join(map(str, trio if ordered else sorted(trio)))


def ranking_quality(document, side, ranking, *, top_k, ordered):
    """Build comparable support and concentration metrics from stored catalog facts."""
    occurrences = document["occurrences"]
    depth = side["depth"]
    context_events = side["context_events"]
    complete_occurrences = side["complete_occurrences"]
    selected = ranking[:top_k]
    total_score = sum(row["score"] for row in ranking)
    selected_score = sum(row["score"] for row in selected)
    selected_direct_hits = sum(row["direct_hits"] for row in selected)
    baseline = top_k / 37
    direct_hit_rate = selected_direct_hits / context_events if context_events else None
    score_concentration = selected_score / total_score if total_score else None
    cutoff_margin = (
        (ranking[top_k - 1]["score"] - ranking[top_k]["score"]) / context_events
        if context_events and top_k < 37 else None
    )
    leader_margin = (
        (ranking[0]["score"] - ranking[1]["score"]) / context_events
        if context_events else None
    )
    order_dominance = None
    if not ordered and occurrences:
        order_dominance = max(row["occurrences"] for row in document["permutation_counts"]) / occurrences
    return {
        "occurrences": occurrences,
        "depth": depth,
        "context_events": context_events,
        "complete_occurrences": complete_occurrences,
        "context_coverage": context_events / (occurrences * depth) if occurrences else None,
        "complete_coverage": complete_occurrences / occurrences if occurrences else None,
        "top_k_direct_hits": selected_direct_hits,
        "direct_hit_rate": direct_hit_rate,
        "direct_lift": direct_hit_rate / baseline if direct_hit_rate is not None else None,
        "top_k_score": selected_score,
        "total_score": total_score,
        "score_concentration": score_concentration,
        "score_concentration_lift": score_concentration / baseline if score_concentration is not None else None,
        "cutoff_score": ranking[top_k - 1]["score"],
        "next_score": ranking[top_k]["score"] if top_k < 37 else None,
        "cutoff_margin_per_event": cutoff_margin,
        "leader_margin_per_event": leader_margin,
        "order_dominance": order_dominance,
    }


def build_signals(rows, documents, *, ordered, direction, top_k):
    signals = []
    depth = 20 if direction == "forward" else 10
    for end in range(2, len(rows), 3):
        trio = [row["value"] for row in rows[end - 2:end + 1]]
        signal = {
            "signal_id": len(signals) + 1, "end_index": end, "trio": trio,
            "trigger_timestamp": rows[end]["timestamp"], "trigger_position": end + 1,
            "selected_numbers": [], "catalog_occurrences": 0, "context_events": 0,
            "quality": None,
        }
        if len(set(trio)) != 3:
            signals.append({**signal, "status": "repeated_trio", "key": None})
            continue
        key = trio_key(trio, ordered)
        document = documents.get(key)
        if document is None:
            raise CatalogUnavailable("Uma combinação está ausente do catálogo publicado. A execução foi interrompida.")
        try:
            side = document[direction]
            ranking = side["ranking"]
            valid = (
                document["key"] == key
                and document["combination"] == (trio if ordered else sorted(trio))
                and type(document["occurrences"]) is int and document["occurrences"] >= 0
                and side["depth"] == depth
                and type(side["context_events"]) is int and side["context_events"] >= 0
                and type(side["complete_occurrences"]) is int
                and 0 <= side["complete_occurrences"] <= document["occurrences"]
                and isinstance(side["position_counts"], list)
                and len(side["position_counts"]) == depth
                and all(type(count) is int and count >= 0 for count in side["position_counts"])
                and sum(side["position_counts"]) == side["context_events"]
                and len(ranking) == 37
                and all(type(row["number"]) is int and 0 <= row["number"] <= 36
                        and type(row["score"]) in (int, float) and math.isfinite(row["score"])
                        and row["score"] >= 0
                        and type(row["direct_hits"]) is int and row["direct_hits"] >= 0
                        for row in ranking)
                and sum(row["direct_hits"] for row in ranking) == side["context_events"]
                and len({row["number"] for row in ranking}) == 37
                and ranking == sorted(ranking, key=lambda row: (-row["score"], row["number"]))
            )
            if not ordered:
                permutations = document["permutation_counts"]
                valid = valid and isinstance(permutations, list) and len(permutations) == 6
                valid = valid and all(
                    isinstance(row, dict) and isinstance(row.get("combination"), list)
                    and len(row["combination"]) == 3
                    and sorted(row["combination"]) == document["combination"]
                    and type(row.get("occurrences")) is int and row["occurrences"] >= 0
                    for row in permutations)
                valid = valid and len({tuple(row["combination"]) for row in permutations}) == 6
                valid = valid and sum(row["occurrences"] for row in permutations) == document["occurrences"]
            if not valid:
                raise CatalogUnavailable("O catálogo retornou um ranking inconsistente.")
        except (KeyError, TypeError, ValueError) as error:
            raise CatalogUnavailable("O catálogo retornou um ranking inconsistente.") from error
        signal.update(key=key, catalog_occurrences=document["occurrences"], context_events=side["context_events"])
        signal["quality"] = ranking_quality(
            document, side, ranking, top_k=top_k, ordered=ordered)
        if side["context_events"] == 0:
            signal["status"] = "no_evidence"
        else:
            signal["selected_numbers"] = [row["number"] for row in ranking[:top_k]]
        signals.append(signal)
    return signals


async def run_catalog_backtest(db, *, history_limit, top_k, attempts, ordered, direction,
                               prevent_overlapping_bets=False):
    active = await db["triple_context_active_v1"].find_one(
        {"_id": ROULETTE}, {"_id": 0, "build_id": 1})
    if active is None:
        raise CatalogNotFound("Nenhum catálogo publicado para a Pragmatic Auto Roulette.")
    build_id = active.get("build_id")
    if not isinstance(build_id, str) or not build_id:
        raise CatalogUnavailable("O catálogo ativo está inconsistente.")
    manifest = await db["triple_context_builds_v1"].find_one(
        {"_id": build_id, "roulette_id": ROULETTE},
        {"_id": 0, "status": 1, "source.records": 1,
         "source.first_timestamp": 1, "source.last_timestamp": 1})
    if manifest is None or manifest.get("status") not in {"ready", "verified"}:
        raise CatalogUnavailable("O catálogo ativo ainda não está disponível.")
    try:
        source = manifest["source"]
        catalog_start = _catalog_date(source["first_timestamp"])
        catalog_end = _catalog_date(source["last_timestamp"])
        if type(source["records"]) is not int or source["records"] < 0 or catalog_end < catalog_start:
            raise CatalogUnavailable("A fonte do catálogo está inconsistente.")
        catalog_source = {"records": source["records"], "first_timestamp": catalog_start.isoformat(),
                          "last_timestamp": catalog_end.isoformat()}
    except (KeyError, TypeError) as error:
        raise CatalogUnavailable("A fonte do catálogo está inconsistente.") from error
    history = db["history"]
    upper = await history.find_one({"roulette_id": ROULETTE}, {"_id": 1}, sort=[("_id", -1)])
    if upper is None:
        raise CatalogNotFound("Nenhum resultado disponível para esta roleta.")
    descending = await history.find(
        {"roulette_id": ROULETTE, "_id": {"$lte": upper["_id"]}},
        {"_id": 1, "value": 1, "timestamp": 1, "roulette_id": 1, "external_game_id": 1},
    ).sort([("timestamp", -1), ("_id", -1)]).limit(history_limit).max_time_ms(15000).to_list(length=history_limit)
    if len(descending) < 3:
        raise CatalogNotFound("São necessários pelo menos três resultados disponíveis para formar um trio.")
    rows, history_source = await asyncio.to_thread(normalize_history, descending, history_limit)
    history_source["source_upper_id"] = str(upper["_id"])
    keys = set()
    for end in range(2, len(rows), 3):
        trio = [row["value"] for row in rows[end - 2:end + 1]]
        if len(set(trio)) == 3:
            keys.add(trio_key(trio, ordered))
    keys = sorted(keys)
    documents = {}
    for offset in range(0, len(keys), 500):
        batch = await db["triple_context_rankings_v1"].find(
            {"build_id": build_id, "roulette_id": ROULETTE,
             "mode": "ordered" if ordered else "unordered", "key": {"$in": keys[offset:offset + 500]}},
            {"_id": 0, "key": 1, "combination": 1, "occurrences": 1,
             "permutation_counts": 1, direction: 1},
        ).max_time_ms(15000).to_list(length=501)
        for document in batch:
            key = document.get("key")
            if key not in keys[offset:offset + 500] or key in documents:
                raise CatalogUnavailable("Há combinações inconsistentes no catálogo publicado.")
            documents[key] = document
    signals = await asyncio.to_thread(build_signals, rows, documents, ordered=ordered,
                                      direction=direction, top_k=top_k)
    evaluated = await asyncio.to_thread(
        evaluate_signals, rows, signals, attempts, prevent_overlapping_bets)
    before_catalog_end = sum(
        signal["status"] not in {"repeated_trio", "no_evidence", "overlap_skipped"}
        and _catalog_date(signal["trigger_timestamp"]) < catalog_end
        for signal in evaluated["signals"])
    warning = (
        "O catálogo inclui dados posteriores à entrada de " + str(before_catalog_end)
        + " sinais desta amostra. A assertividade é retrospectiva e pode estar favorecida por informação futura."
        if before_catalog_end else None
    )
    return {
        "config": {"history_limit": history_limit, "top_k": top_k, "attempts": attempts,
                   "ordered": ordered, "direction": direction,
                   "prevent_overlapping_bets": prevent_overlapping_bets,
                   "sampling": "blocks_of_three",
                   "roulette_id": ROULETTE, "ranking_source": "published_catalog"},
        "source": history_source,
        "catalog": {"build_id": build_id, "source": catalog_source},
        "methodology": {
            "description": (
                "Análise retrospectiva com uma versão fixa do catálogo publicado. Blocos de três; "
                + ("uma nova aposta só começa após o encerramento da anterior."
                   if prevent_overlapping_bets else "as apostas podem se sobrepor.")
            ),
            "warning": warning, "signals_with_potential_future_data": before_catalog_end,
            "ranking_frozen": True, "exact_number_hits": True,
            "followup": "Primeiro acerto do mesmo conjunto até o fim dos resultados selecionados; uma recuperação não altera a derrota.",
            "accuracy": "Vitórias / (vitórias + derrotas). Entradas sem ranking, sem desfecho ou bloqueadas por outra aposta são contabilizadas separadamente.",
        },
        **evaluated,
    }
