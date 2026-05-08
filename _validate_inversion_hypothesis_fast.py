"""Versão otimizada com índices mais inteligentes."""
from __future__ import annotations

import json
from pathlib import Path
from collections import defaultdict

import certifi
from pymongo import MongoClient, DESCENDING, ASCENDING

ROULETTE_ID = "pragmatic-auto-roulette"


def _read_dotenv() -> str | None:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        if line.startswith("MONGO_URL="):
            return line.split("=", 1)[1].strip()
    return None


def main():
    url = _read_dotenv()
    client = MongoClient(url, tls=True, tlsCAFile=certifi.where())
    db = client["roleta_db"]

    print("Carregando histórico com índice de timestamp...")
    hist = list(db["history"].find({"roulette_id": ROULETTE_ID}).sort("timestamp", ASCENDING))
    print(f"Total: {len(hist)} draws")

    # Índices: timestamp → doc, timestamp → índice
    ts_to_doc = {h.get("timestamp"): h for h in hist}
    ts_list = sorted(ts_to_doc.keys())
    ts_to_idx = {ts: i for i, ts in enumerate(ts_list)}

    print(f"Processando snapshots...")
    results = []
    cursor = (
        db["suggestion_snapshots"]
        .find({"roulette_id": ROULETTE_ID})
        .sort("anchor_timestamp_utc", ASCENDING)
    )

    for i, snap in enumerate(cursor):
        if (i + 1) % 2000 == 0:
            print(f"  {i+1}...")

        anchor_ts = snap.get("anchor_timestamp_utc")
        if not anchor_ts:
            continue

        payload = snap.get("payload") or {}
        ranking = payload.get("suggestion") or []

        # Busca próximo draw (binary search ou linear)
        idx = ts_to_idx.get(anchor_ts)
        if idx is None or idx + 1 >= len(ts_list):
            continue

        next_ts = ts_list[idx + 1]
        next_doc = ts_to_doc[next_ts]
        next_num = next_doc.get("value")

        try:
            pos = ranking.index(int(next_num)) + 1
        except (ValueError, TypeError, IndexError):
            continue

        # Recência
        recency = idx + 1 - idx if idx is not None else None

        # Inversão
        inv_num = set(payload.get("invertedNumbers") or [])
        in_inv = int(next_num) in inv_num

        conf = payload.get("confidence") or {}
        results.append({
            "snapshot_id": snap.get("snapshot_id"),
            "pos": pos,
            "in_inverted_numbers": in_inv,
            "confidence_label": conf.get("label"),
        })

    print(f"\n✓ {len(results)} snapshots\n")

    if not results:
        return

    pos_all = [r["pos"] for r in results]
    pos_inv = [r["pos"] for r in results if r["in_inverted_numbers"]]
    pos_not_inv = [r["pos"] for r in results if not r["in_inverted_numbers"]]

    print(f"GERAL: n={len(pos_all)}, média={sum(pos_all)/len(pos_all):.2f}")
    print(f"\n✓ next ∈ invertedNumbers (n={len(pos_inv)}): média={sum(pos_inv)/len(pos_inv):.2f}")
    print(f"✗ next ∉ invertedNumbers (n={len(pos_not_inv)}): média={sum(pos_not_inv)/len(pos_not_inv):.2f}")
    if pos_inv and pos_not_inv:
        gap = sum(pos_not_inv)/len(pos_not_inv) - sum(pos_inv)/len(pos_inv)
        print(f"\n➜ INSIGHT: gap de {gap:.2f} posições (melhor quando em invertedNumbers)")

    # Por confiança
    conf_groups = defaultdict(list)
    for r in results:
        conf_groups[r["confidence_label"]].append(r["pos"])

    print(f"\nPor confiança:")
    for label in sorted(conf_groups.keys()):
        pos = conf_groups[label]
        print(f"  {label}: n={len(pos)}, média={sum(pos)/len(pos):.2f}")

    # Salva JSON
    out_json = Path(__file__).resolve().parent / "_validation_summary_fast.json"
    summary = {
        "total": len(results),
        "all": {"mean": sum(pos_all)/len(pos_all), "min": min(pos_all), "max": max(pos_all)},
        "in_inverted_numbers": {"count": len(pos_inv), "mean": sum(pos_inv)/len(pos_inv) if pos_inv else None},
        "not_in_inverted_numbers": {"count": len(pos_not_inv), "mean": sum(pos_not_inv)/len(pos_not_inv) if pos_not_inv else None},
        "gap": sum(pos_not_inv)/len(pos_not_inv) - sum(pos_inv)/len(pos_inv) if (pos_inv and pos_not_inv) else None,
        "by_confidence": {k: {"count": len(v), "mean": sum(v)/len(v)} for k, v in conf_groups.items()},
    }
    out_json.write_text(json.dumps(summary, indent=2))
    print(f"\n✓ Resumo em {out_json}\n")


if __name__ == "__main__":
    main()
