from __future__ import annotations

import logging
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection

from .contracts import Spin


log = logging.getLogger("patterns.mongo-history")


class MongoHistorySource:
    """Fonte exclusiva dos resultados usados na apuracao dos patterns."""

    def __init__(self, collection: Collection):
        self.collection = collection

    @staticmethod
    def _spins(documents) -> list[Spin]:
        result: list[Spin] = []
        for document in documents:
            try:
                result.append(Spin.from_mongo(document))
            except (TypeError, ValueError) as exc:
                log.warning("Resultado do Mongo ignorado: %s", exc)
        return result

    def latest(self, roulette_id: str, limit: int) -> list[Spin]:
        cursor = (
            self.collection.find(
                {"roulette_id": roulette_id},
                {"value": 1, "roulette_id": 1, "timestamp": 1, "captured_at": 1},
            )
            .sort([("timestamp", DESCENDING), ("_id", DESCENDING)])
            .limit(limit)
        )
        return self._spins(cursor)

    def ending_at(
        self,
        roulette_id: str,
        source_id: Any,
        timestamp,
        limit: int,
    ) -> list[Spin]:
        cursor = (
            self.collection.find(
                {
                    "roulette_id": roulette_id,
                    "$or": [
                        {"timestamp": {"$lt": timestamp}},
                        {"timestamp": timestamp, "_id": {"$lte": source_id}},
                    ],
                },
                {"value": 1, "roulette_id": 1, "timestamp": 1, "captured_at": 1},
            )
            .sort([("timestamp", DESCENDING), ("_id", DESCENDING)])
            .limit(limit)
        )
        return self._spins(cursor)

    def after(
        self,
        roulette_id: str,
        source_id: Any,
        timestamp,
        limit: int,
    ) -> list[Spin]:
        cursor = (
            self.collection.find(
                {
                    "roulette_id": roulette_id,
                    "$or": [
                        {"timestamp": {"$gt": timestamp}},
                        {"timestamp": timestamp, "_id": {"$gt": source_id}},
                    ],
                },
                {"value": 1, "roulette_id": 1, "timestamp": 1, "captured_at": 1},
            )
            .sort([("timestamp", ASCENDING), ("_id", ASCENDING)])
            .limit(limit)
        )
        return self._spins(cursor)
