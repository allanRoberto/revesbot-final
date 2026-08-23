from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from pymongo import MongoClient

from apps.monitoring.patterns.__main__ import _mongo_kwargs


PATTERN_KEYS = ("nera", "last_hope")


def main() -> None:
    load_dotenv()
    mongo_url = (os.getenv("MONGO_URL") or os.getenv("mongo_url") or "").strip()
    if not mongo_url:
        raise RuntimeError("MONGO_URL nao configurado")
    database_name = (
        os.getenv("MONGO_DATABASE") or os.getenv("MONGO_DB") or "roleta_db"
    ).strip()
    client = MongoClient(
        mongo_url,
        serverSelectionTimeoutMS=5_000,
        tz_aware=True,
        **_mongo_kwargs(mongo_url),
    )
    database = client[database_name]
    database.command("ping")

    now = datetime.now(timezone.utc)
    summary: dict[str, dict[str, int | str]] = {}
    for pattern_key in PATTERN_KEYS:
        definition = database["patterns"].find_one(
            {"key": pattern_key, "enabled": True},
            {"_id": 1, "version": 1},
        )
        if not definition:
            raise RuntimeError(f"definicao ausente para {pattern_key}")
        runtime = database["pattern_states"].find_one(
            {
                "pattern_key": pattern_key,
                "roulette_id": "__runtime__",
                "status": "online",
                "lease_expires_at": {"$gt": now},
            },
            {"_id": 1},
        )
        if not runtime:
            raise RuntimeError(f"runtime sem lease ativa para {pattern_key}")
        monitored_tables = database["pattern_states"].count_documents(
            {
                "pattern_key": pattern_key,
                "roulette_id": {"$ne": "__runtime__"},
                "status": "monitoring",
            }
        )
        if monitored_tables < 1:
            raise RuntimeError(f"nenhuma mesa monitorada por {pattern_key}")
        summary[pattern_key] = {
            "status": "online",
            "version": str(definition.get("version") or ""),
            "monitored_tables": monitored_tables,
        }
    print(json.dumps({"status": "ok", "patterns": summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
