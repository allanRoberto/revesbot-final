from __future__ import annotations

from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument

from ..models import RouletteResult


class MongoResultRepository:
    def __init__(self, url: str, database: str, collection: str):
        self.client = MongoClient(
            url,
            serverSelectionTimeoutMS=8000,
            connectTimeoutMS=5000,
            appname="revesbot-collector",
        )
        self.database = self.client[database]
        self.collection = self.database[collection]

    def ping(self) -> None:
        self.client.admin.command("ping")

    def ensure_indexes(self) -> None:
        self.collection.create_index(
            [("roulette_id", ASCENDING), ("timestamp", DESCENDING)],
            name="collector_roulette_timestamp_desc",
        )
        self.collection.create_index(
            [("roulette_id", ASCENDING), ("external_game_id", ASCENDING)],
            name="collector_roulette_external_game_unique",
            unique=True,
            partialFilterExpression={"external_game_id": {"$type": "string"}},
        )

    def insert_if_new(self, result: RouletteResult) -> tuple[bool, str | None]:
        document = result.as_document()
        if result.external_game_id:
            saved = self.collection.find_one_and_update(
                {
                    "roulette_id": result.roulette_id,
                    "external_game_id": result.external_game_id,
                },
                {"$setOnInsert": document},
                upsert=True,
                return_document=ReturnDocument.BEFORE,
                projection={"_id": 1},
            )
            if saved is not None:
                return False, str(saved["_id"])
            inserted = self.collection.find_one(
                {
                    "roulette_id": result.roulette_id,
                    "external_game_id": result.external_game_id,
                },
                {"_id": 1},
            )
            return True, str(inserted["_id"]) if inserted else None

        inserted = self.collection.insert_one(document)
        return True, str(inserted.inserted_id)

    def trim(self, limit_per_table: int) -> int:
        if limit_per_table <= 0:
            return 0
        removed = 0
        for roulette_id in self.collection.distinct("roulette_id"):
            count = self.collection.count_documents({"roulette_id": roulette_id})
            excess = count - limit_per_table
            if excess <= 0:
                continue
            ids = [
                item["_id"]
                for item in self.collection.find(
                    {"roulette_id": roulette_id},
                    {"_id": 1},
                    sort=[("timestamp", ASCENDING)],
                    limit=excess,
                )
            ]
            if ids:
                removed += self.collection.delete_many({"_id": {"$in": ids}}).deleted_count
        return removed
