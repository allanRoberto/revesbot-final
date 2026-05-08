#!/usr/bin/env python3
"""Busca 3000 sugestões por roleta e analisa a posição do ranking onde a sugestão bateu."""
from __future__ import annotations
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
import certifi
from pymongo import MongoClient, DESCENDING, ASCENDING
from bson import ObjectId


def _read_dotenv() -> str | None:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        if line.startswith("MONGO_URL="):
            return line.split("=", 1)[1].strip()
    return None


def correlate(db, roulette_id: str, limit: int = 3000):
    print(f"  Querying {limit} snapshots...", flush=True)
    snapshots = list(
        db["suggestion_snapshots"].find(
            {"roulette_id": roulette_id},
            sort=[("anchor_timestamp_utc", DESCENDING)],
            limit=limit,
        )
    )
    print(f"  Found {len(snapshots)} snapshots", flush=True)
    if not snapshots:
        return []

    # Get the range of timestamps for the snapshots
    # snapshots are descending, so first is most recent, last is oldest
    most_recent_ts = snapshots[0].get("anchor_timestamp_utc")
    oldest_ts = snapshots[-1].get("anchor_timestamp_utc")

    # Buffer 30 minutes after most_recent for the next-doc lookup
    if isinstance(most_recent_ts, datetime):
        upper_ts = most_recent_ts + timedelta(minutes=30)
    else:
        upper_ts = most_recent_ts

    print(f"  History range: {oldest_ts} to {upper_ts}", flush=True)
    print(f"  Querying history in this range...", flush=True)

    history_docs = list(
        db["history"].find(
            {
                "roulette_id": roulette_id,
                "timestamp": {"$gte": oldest_ts, "$lte": upper_ts},
            },
            {"_id": 1, "timestamp": 1, "value": 1},
            sort=[("timestamp", ASCENDING)],
        )
    )
    print(f"  Found {len(history_docs)} history docs in range", flush=True)

    history_by_id = {str(h["_id"]): h for h in history_docs}
    timestamps = [h["timestamp"] for h in history_docs]

    import bisect

    items = []
    for snap in snapshots:
        anchor_history_id = snap.get("anchor_history_id")
        ranking_full = snap.get("ranking_full") or []

        if not anchor_history_id or not ranking_full:
            continue

        anchor_doc = history_by_id.get(str(anchor_history_id))
        if not anchor_doc:
            continue

        anchor_ts_value = anchor_doc["timestamp"]
        idx = bisect.bisect_right(timestamps, anchor_ts_value)
        if idx >= len(history_docs):
            continue

        next_doc = history_docs[idx]
        next_number = next_doc["value"]

        try:
            hit_rank = ranking_full.index(next_number) + 1
        except ValueError:
            continue

        items.append({
            "snapshot_id": str(snap.get("_id")),
            "roulette_id": roulette_id,
            "anchor_number": anchor_doc["value"],
            "anchor_history_id": str(anchor_history_id),
            "anchor_timestamp_utc": anchor_doc["timestamp"].isoformat() if isinstance(anchor_doc["timestamp"], datetime) else str(anchor_doc["timestamp"]),
            "next_number": next_number,
            "next_history_id": str(next_doc["_id"]),
            "next_timestamp_utc": next_doc["timestamp"].isoformat() if isinstance(next_doc["timestamp"], datetime) else str(next_doc["timestamp"]),
            "hit_rank": hit_rank,
            "hit": True,
            "ranking_full": ranking_full,
            "ranking_size": snap.get("ranking_size", len(ranking_full)),
            "config_key": snap.get("config_key"),
        })

    print(f"  Correlated {len(items)} items", flush=True)
    return items


def analyze_ranking_distribution(items: list) -> dict:
    """Analisa a distribuição dos rankings onde a sugestão bateu."""
    if not items:
        return {}

    rank_distribution = defaultdict(int)
    rank_by_position = defaultdict(list)

    for item in items:
        hit_rank = item["hit_rank"]
        rank_distribution[hit_rank] += 1
        rank_by_position[hit_rank].append({
            "number": item["next_number"],
            "snapshot_id": item["snapshot_id"],
            "roulette_id": item["roulette_id"],
        })

    # Calcular estatísticas
    ranks = list(rank_distribution.keys())
    total_hits = len(items)

    stats = {
        "total_hits": total_hits,
        "min_rank": min(ranks) if ranks else None,
        "max_rank": max(ranks) if ranks else None,
        "avg_rank": sum(rank_distribution.keys()) / len(rank_distribution) if rank_distribution else None,
        "median_rank": sorted(rank_distribution.keys())[len(rank_distribution)//2] if rank_distribution else None,
        "distribution": dict(sorted(rank_distribution.items())),
        "hits_in_top_5": sum(rank_distribution[r] for r in ranks if r <= 5),
        "hits_in_top_10": sum(rank_distribution[r] for r in ranks if r <= 10),
        "hits_in_top_20": sum(rank_distribution[r] for r in ranks if r <= 20),
        "percentage_top_5": (sum(rank_distribution[r] for r in ranks if r <= 5) / total_hits * 100) if total_hits > 0 else 0,
        "percentage_top_10": (sum(rank_distribution[r] for r in ranks if r <= 10) / total_hits * 100) if total_hits > 0 else 0,
        "percentage_top_20": (sum(rank_distribution[r] for r in ranks if r <= 20) / total_hits * 100) if total_hits > 0 else 0,
    }

    return {
        "statistics": stats,
        "distribution_by_rank": rank_by_position,
    }


def main():
    url = _read_dotenv()
    if not url:
        print("❌ MONGO_URL not found in .env file", flush=True)
        sys.exit(1)

    print("Connecting to MongoDB...", flush=True)
    client = MongoClient(url, tls=True, tlsCAFile=certifi.where())
    db = client["roleta_db"]

    all_items = []
    summary = {"by_roulette": {}}

    for roulette in ["pragmatic-auto-roulette", "pragmatic-brazilian-roulette"]:
        print(f"\n=== {roulette} ===", flush=True)
        items = correlate(db, roulette, limit=3000)
        all_items.extend(items)
        summary["by_roulette"][roulette] = {
            "count": len(items),
            "analysis": analyze_ranking_distribution(items)
        }

    summary["total_items"] = len(all_items)

    # Análise geral
    print(f"\n=== ANÁLISE GERAL ===", flush=True)
    overall_analysis = analyze_ranking_distribution(all_items)
    summary["overall_analysis"] = overall_analysis

    output = {
        "summary": summary,
        "items": all_items,
        "generated_at": datetime.now().isoformat(),
    }

    out_path = Path("suggestion_hits_3000_analysis.json")
    with open(out_path, "w") as f:
        json.dump(output, f, default=str, indent=2)

    print(f"\n✅ Análise salva em {out_path}", flush=True)
    print(f"\n📊 RESUMO:", flush=True)
    print(f"   Total de hits: {summary['total_items']}", flush=True)

    for r, data in summary["by_roulette"].items():
        print(f"\n   {r}:")
        print(f"      Total de hits: {data['count']}", flush=True)
        if "analysis" in data and "statistics" in data["analysis"]:
            stats = data["analysis"]["statistics"]
            print(f"      Média de ranking: {stats.get('avg_rank', 'N/A'):.2f}" if isinstance(stats.get('avg_rank'), (int, float)) else f"      Média de ranking: {stats.get('avg_rank', 'N/A')}", flush=True)
            print(f"      Top 5: {stats.get('hits_in_top_5', 0)} ({stats.get('percentage_top_5', 0):.1f}%)", flush=True)
            print(f"      Top 10: {stats.get('hits_in_top_10', 0)} ({stats.get('percentage_top_10', 0):.1f}%)", flush=True)
            print(f"      Top 20: {stats.get('hits_in_top_20', 0)} ({stats.get('percentage_top_20', 0):.1f}%)", flush=True)

    if "statistics" in overall_analysis:
        stats = overall_analysis["statistics"]
        print(f"\n   GERAL:", flush=True)
        print(f"      Média de ranking: {stats.get('avg_rank', 'N/A'):.2f}" if isinstance(stats.get('avg_rank'), (int, float)) else f"      Média de ranking: {stats.get('avg_rank', 'N/A')}", flush=True)
        print(f"      Top 5: {stats.get('hits_in_top_5', 0)} ({stats.get('percentage_top_5', 0):.1f}%)", flush=True)
        print(f"      Top 10: {stats.get('hits_in_top_10', 0)} ({stats.get('percentage_top_10', 0):.1f}%)", flush=True)
        print(f"      Top 20: {stats.get('hits_in_top_20', 0)} ({stats.get('percentage_top_20', 0):.1f}%)", flush=True)


if __name__ == "__main__":
    main()
