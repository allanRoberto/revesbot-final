"""
Debug helper: pega as últimas N sugestões da pragmatic-auto-roulette
e cruza com os números sorteados (history.value) para entender o
"zigzag" da posição em que cada sugestão acerta.

Uso:
  python _debug_zigzag.py [N]   (default N=10)
"""
from __future__ import annotations

import os
import sys
import json
from datetime import datetime, timezone
from pathlib import Path

import certifi
from pymongo import MongoClient, DESCENDING, ASCENDING

ROULETTE_ID = "pragmatic-auto-roulette"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 10


def _read_dotenv() -> str | None:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        if line.startswith("MONGO_URL="):
            return line.split("=", 1)[1].strip()
    return None


def _to_utc(dt) -> datetime | None:
    if isinstance(dt, datetime):
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    if isinstance(dt, str):
        try:
            parsed = datetime.fromisoformat(dt.replace("Z", "+00:00"))
            return _to_utc(parsed)
        except Exception:
            return None
    return None


def _ts(dt) -> str | None:
    out = _to_utc(dt)
    return out.isoformat() if out else None


def main() -> int:
    mongo_url = os.environ.get("MONGO_URL") or _read_dotenv()
    if not mongo_url:
        print("MONGO_URL não encontrado.", file=sys.stderr)
        return 1

    client = MongoClient(mongo_url, tls=True, tlsCAFile=certifi.where())
    db = client["roleta_db"]
    snaps = db["suggestion_snapshots"]
    history = db["history"]

    print(f"== Últimas {N} sugestões para {ROULETTE_ID} ==\n")

    cursor = (
        snaps.find({"roulette_id": ROULETTE_ID})
        .sort("anchor_timestamp_utc", DESCENDING)
        .limit(N)
    )
    docs = list(cursor)
    docs.reverse()  # cronológico (mais antigo primeiro)

    if not docs:
        print("Nenhum snapshot encontrado.")
        return 0

    # busca histórico cobrindo um pouco antes do primeiro snapshot
    earliest = _to_utc(docs[0].get("anchor_timestamp_utc"))
    hist_query = {"roulette_id": ROULETTE_ID}
    if earliest:
        # `timestamp` em history é datetime naive em UTC
        hist_query["timestamp"] = {"$gte": earliest.replace(tzinfo=None)}
    hist = list(history.find(hist_query).sort("timestamp", ASCENDING).limit(N + 80))

    print(
        f"{'idx':>3} | {'anchor_ts (UTC)':<27} | {'anchor':>6} | {'next_ts (UTC)':<27} | {'next':>4} | {'pos':>4} | {'top10':<40} | inverted(first 8)"
    )
    print("-" * 165)

    rows = []
    for i, doc in enumerate(docs):
        anchor_ts = _to_utc(doc.get("anchor_timestamp_utc"))
        anchor_num = doc.get("anchor_number")
        payload = doc.get("payload") or {}
        ranking = payload.get("suggestion") or payload.get("list") or []
        inverted_numbers = payload.get("invertedNumbers") or []
        inverted_in_final = payload.get("invertedInFinal") or []
        inverted_removed = payload.get("invertedRemoved") or []
        pulled_numbers = payload.get("pulledNumbers") or []
        pulled_in_final = payload.get("pulledInFinal") or []

        # próximo número: primeiro item em hist com timestamp > anchor_ts
        next_num = None
        next_ts = None
        for h in hist:
            ts_h = _to_utc(h.get("timestamp"))
            if ts_h and anchor_ts and ts_h > anchor_ts:
                next_num = h.get("value")
                next_ts = ts_h
                break

        pos = None
        if next_num is not None and isinstance(ranking, list):
            try:
                pos = ranking.index(int(next_num)) + 1
            except ValueError:
                pos = None

        top10 = ranking[:10]
        rows.append(
            {
                "idx": i + 1,
                "snapshot_id": doc.get("snapshot_id"),
                "anchor_ts": _ts(anchor_ts),
                "next_ts": _ts(next_ts),
                "anchor": anchor_num,
                "next": next_num,
                "pos": pos,
                "ranking": ranking,
                "invertedNumbers": inverted_numbers,
                "invertedInFinal": inverted_in_final,
                "invertedRemoved": inverted_removed,
                "pulledNumbers": pulled_numbers,
                "pulledInFinal": pulled_in_final,
                "confidence": payload.get("confidence"),
            }
        )
        print(
            f"{i+1:>3} | {_ts(anchor_ts) or '-':<27} | {str(anchor_num):>6} | "
            f"{_ts(next_ts) or '-':<27} | {str(next_num):>4} | {str(pos):>4} | "
            f"{str(top10):<40} | {inverted_in_final[:8]}"
        )

    # contexto: últimos 30 sorteios
    print("\n== Últimos 30 números sorteados (ordem cronológica) ==")
    last_hist = list(
        history.find({"roulette_id": ROULETTE_ID})
        .sort("timestamp", DESCENDING)
        .limit(30)
    )
    last_hist.reverse()
    print(" -> ".join(str(h.get("value")) for h in last_hist))

    # estatística rápida das posições do "next" no ranking
    positions = [r["pos"] for r in rows if r["pos"] is not None]
    if positions:
        print(f"\nPosições (acerto): {positions}")
        print(f"Min={min(positions)}  Max={max(positions)}  Média={sum(positions)/len(positions):.2f}")

    # salva detalhe completo em JSON
    out_path = Path(__file__).resolve().parent / "_debug_zigzag_output.json"
    out_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False))
    print(f"\nDetalhe salvo em {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
