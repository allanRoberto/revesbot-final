from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from pymongo import MongoClient


def _iso(value: object) -> object:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return value


def main() -> None:
    mongo_url = os.environ["MONGO_URL"]
    database_name = os.getenv("MONGO_DATABASE", "roleta_db")
    collection_name = os.getenv("MONGO_COLLECTION", "history")
    client = MongoClient(mongo_url, serverSelectionTimeoutMS=5_000)
    collection = client[database_name][collection_name]

    latest = collection.find_one(
        {},
        {
            "_id": 0,
            "roulette_id": 1,
            "value": 1,
            "timestamp": 1,
            "external_game_id": 1,
            "slots": 1,
            "winning_multiplier": 1,
            "captured_at": 1,
            "recovered": 1,
            "timestamp_source": 1,
        },
        sort=[("timestamp", -1)],
    )
    duplicate_groups = list(
        collection.aggregate(
            [
                {
                    "$group": {
                        "_id": {"roulette_id": "$roulette_id", "external_game_id": "$external_game_id"},
                        "count": {"$sum": 1},
                    }
                },
                {"$match": {"_id.external_game_id": {"$ne": None}, "count": {"$gt": 1}}},
                {"$count": "total"},
            ]
        )
    )
    output = {
        "database": database_name,
        "collection": collection_name,
        "documents": collection.count_documents({}),
        "tables": len(collection.distinct("roulette_id")),
        "duplicate_game_groups": duplicate_groups[0]["total"] if duplicate_groups else 0,
        "documents_with_slots": collection.count_documents(
            {"slots": {"$exists": True, "$ne": {}}}
        ),
        "multiplier_payments": collection.count_documents({"winning_multiplier": {"$ne": None}}),
        "recovered_documents": collection.count_documents({"recovered": True}),
        "provider_timestamps": collection.count_documents({"timestamp_source": "provider"}),
        "captured_fallback_timestamps": collection.count_documents(
            {"timestamp_source": "captured_fallback"}
        ),
        "latest": {key: _iso(value) for key, value in (latest or {}).items()},
    }
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
