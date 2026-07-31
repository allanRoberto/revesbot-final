#!/usr/bin/env python3
"""
Busca ocorrências de um número na collection history usando índices existentes.

Índices relevantes (roleta_db.history):
  - idx_roulette_value          -> (roulette_id, value)     [melhor para achar o número]
  - history_roulette_ts_desc    -> (roulette_id, timestamp) [melhor para giros recentes da mesa]

Requer túnel SSH:
  ssh -N -L 27018:127.0.0.1:27017 root@45.179.88.173
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection

INDEX_ROULETTE_VALUE = "idx_roulette_value"
INDEX_ROULETTE_TS = "history_roulette_ts_desc"
DISPLAY_TZ = ZoneInfo("America/Sao_Paulo")


def load_mongo_url() -> str:
    env_path = Path(__file__).resolve().parent / ".env"
    for line in env_path.read_text().splitlines():
        if line.startswith("MONGO_URL="):
            return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError("MONGO_URL não encontrado no .env")


def get_history() -> tuple[MongoClient, Collection]:
    client = MongoClient(
        os.getenv("MONGO_URL") or load_mongo_url(),
        serverSelectionTimeoutMS=8000,
    )
    client.admin.command("ping")
    return client, client["roleta_db"]["history"]


def format_timestamp(timestamp: Any) -> str:
    local_timestamp = to_display_timezone(timestamp)
    if local_timestamp is None:
        return str(timestamp)

    return local_timestamp.strftime("%d/%m/%Y %H:%M")


def format_time(timestamp: Any) -> str:
    local_timestamp = to_display_timezone(timestamp)
    if local_timestamp is None:
        return str(timestamp)

    return local_timestamp.strftime("%H:%M")


def to_display_timezone(timestamp: Any) -> datetime | None:
    if not isinstance(timestamp, datetime):
        return None

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    return timestamp.astimezone(DISPLAY_TZ)


def to_utc_naive(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=DISPLAY_TZ)

    return timestamp.astimezone(timezone.utc).replace(tzinfo=None)


def format_minute_diff(delta: timedelta) -> str:
    minutes = int(round(delta.total_seconds() / 60))
    sign = "+" if minutes > 0 else ""
    return f"{sign}{minutes} min"


def format_window_values(items: list[dict[str, Any]]) -> str:
    if not items:
        return "nenhum resultado na janela"

    return ", ".join(
        f"{item['doc']['value']} às {format_time(item['doc']['timestamp'])} "
        f"({format_minute_diff(item['delta'])})"
        for item in items
    )


def fetch_results_window_one_table(
    history: Collection,
    *,
    roulette_id: str,
    target_timestamp: datetime,
    window_minutes: int,
) -> list[dict[str, Any]]:
    window = timedelta(minutes=window_minutes)
    start_utc = to_utc_naive(target_timestamp - window)
    end_utc = to_utc_naive(target_timestamp + window)
    query = {
        "roulette_id": roulette_id,
        "timestamp": {"$gte": start_utc, "$lte": end_utc},
    }
    projection = {"_id": 0, "roulette_id": 1, "value": 1, "timestamp": 1}

    cursor = (
        history.find(query, projection)
        .hint(INDEX_ROULETTE_TS)
        .sort("timestamp", ASCENDING)
    )
    return list(cursor)


def compare_previous_days(
    history: Collection,
    *,
    roulette_id: str,
    value: int,
    docs: list[dict[str, Any]],
    base_limit: int,
    days_previous: int,
    window_minutes: int,
) -> list[dict[str, Any]]:
    normalized: list[tuple[dict[str, Any], datetime]] = []
    for doc in docs:
        local_timestamp = to_display_timezone(doc.get("timestamp"))
        if local_timestamp is not None:
            normalized.append((doc, local_timestamp))

    normalized.sort(key=lambda item: item[1], reverse=True)
    window = timedelta(minutes=window_minutes)
    comparisons: list[dict[str, Any]] = []

    for base_doc, base_timestamp in normalized[:base_limit]:
        days: list[dict[str, Any]] = []

        for day_offset in range(1, days_previous + 1):
            target_timestamp = base_timestamp - timedelta(days=day_offset)
            window_docs = fetch_results_window_one_table(
                history,
                roulette_id=roulette_id,
                target_timestamp=target_timestamp,
                window_minutes=window_minutes,
            )
            day_items: list[tuple[timedelta, datetime, dict[str, Any], timedelta]] = []

            for candidate_doc in window_docs:
                candidate_timestamp = to_display_timezone(candidate_doc.get("timestamp"))
                if candidate_timestamp is None:
                    continue

                delta = candidate_timestamp - target_timestamp
                absolute_delta = abs(delta)
                if absolute_delta <= window:
                    day_items.append((absolute_delta, candidate_timestamp, candidate_doc, delta))

            day_items.sort(key=lambda item: (item[0], item[1]))
            matches = [
                {
                    "doc": candidate_doc,
                    "timestamp": candidate_timestamp,
                    "delta": delta,
                }
                for _, candidate_timestamp, candidate_doc, delta in day_items
                if candidate_doc.get("value") == value
            ]
            alternatives_by_time = sorted(day_items, key=lambda item: item[1])
            alternatives = [
                {
                    "doc": candidate_doc,
                    "timestamp": candidate_timestamp,
                    "delta": delta,
                }
                for _, candidate_timestamp, candidate_doc, delta in alternatives_by_time
                if candidate_doc.get("value") != value
            ]

            days.append(
                {
                    "day_offset": day_offset,
                    "target_timestamp": target_timestamp,
                    "matches": matches,
                    "alternatives": alternatives,
                }
            )

        comparisons.append(
            {
                "base_doc": base_doc,
                "base_timestamp": base_timestamp,
                "days": days,
            }
        )

    return comparisons


def print_day_comparison(
    *,
    history: Collection,
    roulette_id: str,
    value: int,
    docs: list[dict[str, Any]],
    base_limit: int,
    days_previous: int,
    window_minutes: int,
) -> None:
    print(
        f"\n=== {roulette_id} | número {value} | "
        f"janela ±{window_minutes} min | {days_previous} dias anteriores ==="
    )
    print(f"Total de ocorrências do número: {len(docs)}")

    comparisons = compare_previous_days(
        history,
        roulette_id=roulette_id,
        value=value,
        docs=docs,
        base_limit=base_limit,
        days_previous=days_previous,
        window_minutes=window_minutes,
    )
    if not comparisons:
        print("  Nenhuma ocorrência encontrada.")
        return

    for comparison in comparisons:
        base_doc = comparison["base_doc"]
        print(f"\nBase: {format_timestamp(base_doc['timestamp'])}  value={base_doc['value']}")

        for day in comparison["days"]:
            matches = day["matches"]
            if matches:
                for match in matches:
                    match_doc = match["doc"]
                    print(
                        f"  D-{day['day_offset']}: {format_timestamp(match_doc['timestamp'])}  "
                        f"diferença={format_minute_diff(match['delta'])}  "
                        f"value={match_doc['value']}"
                    )
                continue

            print(
                f"  D-{day['day_offset']}: {format_timestamp(day['target_timestamp'])}  "
                f"sem value={value} | vieram: {format_window_values(day['alternatives'])}"
            )


def list_mesas(history: Collection) -> list[str]:
    return sorted(
        mesa
        for mesa in history.distinct("roulette_id")
        if isinstance(mesa, str) and mesa and not mesa.startswith("_")
    )


def fetch_occurrences_one_table(
    history: Collection,
    *,
    roulette_id: str,
    value: int,
    limit: int | None = None,
    sort_desc: bool = True,
) -> list[dict[str, Any]]:
    """
    Usa idx_roulette_value (roulette_id + value).
    O sort por timestamp é feito em memória sobre só as ocorrências do número,
    evitando scan de ~200k docs que o planner faria sozinho.
    """
    query = {"roulette_id": roulette_id, "value": int(value)}
    projection = {"_id": 0, "roulette_id": 1, "value": 1, "timestamp": 1}

    cursor = history.find(query, projection).hint(INDEX_ROULETTE_VALUE)
    docs = list(cursor)

    docs.sort(key=lambda d: d["timestamp"], reverse=sort_desc)
    if limit is not None:
        docs = docs[:limit]
    return docs


def fetch_occurrences_all_tables(
    history: Collection,
    *,
    value: int,
    roulette_ids: Iterable[str] | None = None,
    limit_per_table: int | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """
    Não existe índice só em value. Para todas as mesas, consulta mesa a mesa
    com idx_roulette_value (rápido) em vez de varrer a collection inteira.
    """
    mesas = list(roulette_ids) if roulette_ids is not None else list_mesas(history)
    out: dict[str, list[dict[str, Any]]] = {}

    for roulette_id in mesas:
        docs = fetch_occurrences_one_table(
            history,
            roulette_id=roulette_id,
            value=value,
            limit=limit_per_table,
            sort_desc=True,
        )
        if docs:
            out[roulette_id] = docs
    return out


def count_occurrences_one_table(history: Collection, *, roulette_id: str, value: int) -> int:
    return history.count_documents(
        {"roulette_id": roulette_id, "value": int(value)},
        hint=INDEX_ROULETTE_VALUE,
    )


def explain_query(history: Collection, *, roulette_id: str, value: int) -> None:
    plan = (
        history.find({"roulette_id": roulette_id, "value": value}, {"timestamp": 1})
        .hint(INDEX_ROULETTE_VALUE)
        .sort("timestamp", DESCENDING)
        .limit(10)
        .explain()
    )
    stats = plan.get("executionStats", {})
    winning = plan["queryPlanner"]["winningPlan"]

    def walk(node: dict[str, Any], depth: int = 0) -> None:
        indent = "  " * depth
        idx = node.get("indexName", "-")
        print(f"{indent}{node.get('stage')} index={idx}")
        for key in ("inputStage", "inputStages"):
            child = node.get(key)
            if isinstance(child, list):
                for item in child:
                    walk(item, depth + 1)
            elif isinstance(child, dict):
                walk(child, depth + 1)

    print("Plano de execução (mesa + valor + sort timestamp):")
    walk(winning)
    print(
        f"docsExamined={stats.get('totalDocsExamined')} "
        f"keysExamined={stats.get('totalKeysExamined')}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Busca ocorrências de um número no MongoDB")
    parser.add_argument("numero", type=int, help="Número da roleta (0-36)")
    parser.add_argument(
        "--mesa",
        help="Slug da mesa (ex: pragmatic-brazilian-roulette). Omita para buscar em todas.",
    )
    parser.add_argument("--limit", type=int, default=10, help="Quantas ocorrências mostrar por mesa")
    parser.add_argument("--count-only", action="store_true", help="Só conta, não lista timestamps")
    parser.add_argument("--explain", action="store_true", help="Mostra plano de execução do MongoDB")
    parser.add_argument(
        "--comparar-dias",
        action="store_true",
        help="Compara ocorrências do número com os dias anteriores no mesmo horário.",
    )
    parser.add_argument(
        "--janela-minutos",
        type=int,
        default=3,
        help="Janela em minutos para comparar o mesmo horário dos dias anteriores.",
    )
    parser.add_argument(
        "--dias-anteriores",
        type=int,
        default=7,
        help="Quantidade de dias anteriores para comparar.",
    )
    args = parser.parse_args()

    if args.limit < 1:
        parser.error("--limit precisa ser maior que zero")
    if args.janela_minutos < 1:
        parser.error("--janela-minutos precisa ser maior que zero")
    if args.dias_anteriores < 1:
        parser.error("--dias-anteriores precisa ser maior que zero")
    if args.comparar_dias and args.count_only:
        parser.error("--comparar-dias não pode ser usado com --count-only")

    client, history = get_history()
    try:
        if args.explain and args.mesa:
            explain_query(history, roulette_id=args.mesa, value=args.numero)

        if args.comparar_dias:
            if args.mesa:
                docs = fetch_occurrences_one_table(
                    history,
                    roulette_id=args.mesa,
                    value=args.numero,
                    limit=None,
                )
                print_day_comparison(
                    history=history,
                    roulette_id=args.mesa,
                    value=args.numero,
                    docs=docs,
                    base_limit=args.limit,
                    days_previous=args.dias_anteriores,
                    window_minutes=args.janela_minutos,
                )
                return

            mesas = list_mesas(history)
            by_mesa = fetch_occurrences_all_tables(
                history,
                value=args.numero,
                roulette_ids=mesas,
                limit_per_table=None,
            )

            for mesa, docs in sorted(by_mesa.items(), key=lambda item: (-len(item[1]), item[0])):
                print_day_comparison(
                    history=history,
                    roulette_id=mesa,
                    value=args.numero,
                    docs=docs,
                    base_limit=args.limit,
                    days_previous=args.dias_anteriores,
                    window_minutes=args.janela_minutos,
                )
            return

        if args.mesa:
            total = count_occurrences_one_table(history, roulette_id=args.mesa, value=args.numero)
            print(f"Mesa: {args.mesa} | número {args.numero} | total: {total}")

            if not args.count_only:
                docs = fetch_occurrences_one_table(
                    history,
                    roulette_id=args.mesa,
                    value=args.numero,
                    limit=args.limit,
                )
                for i, doc in enumerate(docs, 1):
                    print(f"  {i:>3}. {format_timestamp(doc['timestamp'])}  value={doc['value']}")
            return

        mesas = list_mesas(history)
        counts = {
            mesa: count_occurrences_one_table(history, roulette_id=mesa, value=args.numero)
            for mesa in mesas
        }
        mesas_com_ocorrencia = {mesa: n for mesa, n in counts.items() if n > 0}
        grand_total = sum(counts.values())
        print(
            f"Todas as mesas | número {args.numero} | total: {grand_total} "
            f"em {len(mesas_com_ocorrencia)} mesas"
        )

        if args.count_only:
            for mesa, n in sorted(mesas_com_ocorrencia.items(), key=lambda x: (-x[1], x[0])):
                print(f"  {mesa}: {n}")
            return

        by_mesa = fetch_occurrences_all_tables(
            history,
            value=args.numero,
            roulette_ids=mesas_com_ocorrencia.keys(),
            limit_per_table=args.limit,
        )

        for mesa, docs in sorted(by_mesa.items(), key=lambda x: (-counts[x[0]], x[0])):
            print(f"\n=== {mesa} ({counts[mesa]} ocorrências) ===")
            for i, doc in enumerate(docs, 1):
                print(f"  {i:>3}. {format_timestamp(doc['timestamp'])}  value={doc['value']}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
