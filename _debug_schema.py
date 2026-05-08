"""Imprime um documento exemplo de cada coleção relevante para inspecionar o schema."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import certifi
from pymongo import MongoClient, DESCENDING


def _read_dotenv() -> str | None:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        if line.startswith("MONGO_URL="):
            return line.split("=", 1)[1].strip()
    return None


def _default(v):
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)


def main():
    url = _read_dotenv()
    client = MongoClient(url, tls=True, tlsCAFile=certifi.where())
    db = client["roleta_db"]

    print("== history (last doc) ==")
    h = db["history"].find_one({"roulette_id": "pragmatic-auto-roulette"}, sort=[("timestamp", DESCENDING)])
    if h is None:
        # talvez o nome da roleta seja diferente
        print("Nenhum doc encontrado para roulette_id=pragmatic-auto-roulette. Procurando distintos...")
        ids = db["history"].distinct("roulette_id")
        print("roulette_ids existentes:", ids[:30])
        any_h = db["history"].find_one({}, sort=[("timestamp", DESCENDING)])
        print("doc qualquer:", json.dumps(any_h, default=_default, indent=2)[:2000] if any_h else "vazio")
    else:
        print(json.dumps(h, default=_default, indent=2)[:3000])

    print("\n== suggestion_snapshots (last doc) ==")
    s = db["suggestion_snapshots"].find_one(
        {"roulette_id": "pragmatic-auto-roulette"}, sort=[("anchor_timestamp_utc", DESCENDING)]
    )
    if s is None:
        ids = db["suggestion_snapshots"].distinct("roulette_id")
        print("roulette_ids no snapshots:", ids[:30])
        any_s = db["suggestion_snapshots"].find_one({}, sort=[("anchor_timestamp_utc", DESCENDING)])
        print("doc qualquer:", json.dumps(any_s, default=_default, indent=2)[:2000] if any_s else "vazio")
    else:
        # mostra só as chaves de topo + algumas sub-chaves
        keys = list(s.keys())
        print("top keys:", keys)
        payload = s.get("payload") or {}
        print("payload keys:", list(payload.keys())[:60])
        # mostra os primeiros campos
        excerpt = {k: s.get(k) for k in keys if k != "payload"}
        print("doc head:", json.dumps(excerpt, default=_default, indent=2)[:2000])
        print("payload.suggestion (head):", payload.get("suggestion") or payload.get("list"))
        print("payload.invertedInFinal:", payload.get("invertedInFinal"))
        print("payload.invertedRemoved:", payload.get("invertedRemoved"))

    print("\n== contagens ==")
    print("history total:", db["history"].count_documents({"roulette_id": "pragmatic-auto-roulette"}))
    print("snapshots total:", db["suggestion_snapshots"].count_documents({"roulette_id": "pragmatic-auto-roulette"}))


if __name__ == "__main__":
    main()
