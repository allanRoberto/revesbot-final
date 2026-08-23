from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from .contracts import PatternDefinition


ACTIVE_STATUSES = ("active",)
RESOLVED_STATUSES = ("won", "lost")


class PatternRepository:
    def __init__(self, database: Database):
        self.database = database
        self.patterns: Collection = database["patterns"]
        self.signals: Collection = database["pattern_signals"]
        self.states: Collection = database["pattern_states"]

    def ensure_indexes(self) -> None:
        self.patterns.create_index([("key", ASCENDING)], unique=True, name="patterns_key_unique")
        self.signals.create_index(
            [
                ("pattern_key", ASCENDING),
                ("roulette_id", ASCENDING),
                ("trigger_history_id", ASCENDING),
            ],
            unique=True,
            name="pattern_signal_trigger_unique",
        )
        self.signals.create_index(
            [("pattern_key", ASCENDING), ("status", ASCENDING), ("created_at", DESCENDING)],
            name="pattern_signal_status_created",
        )
        self.signals.create_index(
            [("pattern_key", ASCENDING), ("roulette_id", ASCENDING), ("created_at", DESCENDING)],
            name="pattern_signal_roulette_created",
        )
        self.states.create_index(
            [("pattern_key", ASCENDING), ("roulette_id", ASCENDING)],
            unique=True,
            name="pattern_state_unique",
        )

    def upsert_definition(self, definition: PatternDefinition) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        document = definition.as_document()
        return self.patterns.find_one_and_update(
            {"key": definition.key},
            {
                "$set": {**document, "updated_at": now},
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )

    def acquire_lease(
        self,
        pattern_key: str,
        owner: str,
        *,
        ttl_seconds: int,
    ) -> bool:
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ttl_seconds)
        query = {
            "pattern_key": pattern_key,
            "roulette_id": "__runtime__",
            "$or": [
                {"lease_expires_at": {"$lte": now}},
                {"lease_expires_at": {"$exists": False}},
                {"lease_owner": owner},
            ],
        }
        try:
            doc = self.states.find_one_and_update(
                query,
                {
                    "$set": {
                        "lease_owner": owner,
                        "lease_expires_at": expires_at,
                        "status": "online",
                        "updated_at": now,
                    },
                    "$setOnInsert": {
                        "pattern_key": pattern_key,
                        "roulette_id": "__runtime__",
                        "created_at": now,
                    },
                },
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            return False
        return bool(doc and doc.get("lease_owner") == owner)

    def release_lease(self, pattern_key: str, owner: str) -> None:
        now = datetime.now(timezone.utc)
        self.states.update_one(
            {
                "pattern_key": pattern_key,
                "roulette_id": "__runtime__",
                "lease_owner": owner,
            },
            {
                "$set": {
                    "status": "offline",
                    "lease_expires_at": now,
                    "updated_at": now,
                }
            },
        )

    def load_state(self, pattern_key: str, roulette_id: str) -> dict[str, Any] | None:
        return self.states.find_one(
            {"pattern_key": pattern_key, "roulette_id": roulette_id}
        )

    def save_state(self, document: Mapping[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        key = {
            "pattern_key": document["pattern_key"],
            "roulette_id": document["roulette_id"],
        }
        values = dict(document)
        values.pop("_id", None)
        values["updated_at"] = now
        self.states.update_one(
            key,
            {"$set": values, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )

    def load_active_signal(self, pattern_key: str, roulette_id: str) -> dict[str, Any] | None:
        return self.signals.find_one(
            {
                "pattern_key": pattern_key,
                "roulette_id": roulette_id,
                "status": {"$in": list(ACTIVE_STATUSES)},
            },
            sort=[("created_at", DESCENDING)],
        )

    def create_signal(self, document: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
        key = {
            "pattern_key": document["pattern_key"],
            "roulette_id": document["roulette_id"],
            "trigger_history_id": document["trigger_history_id"],
        }
        values = dict(document)
        values.pop("_id", None)
        result = self.signals.update_one(key, {"$setOnInsert": values}, upsert=True)
        stored = self.signals.find_one(key)
        if stored is None:  # pragma: no cover - defensive guard
            raise RuntimeError("sinal nao encontrado apos upsert")
        return stored, result.upserted_id is not None

    def save_signal(self, document: Mapping[str, Any]) -> None:
        values = dict(document)
        signal_id = values.pop("_id")
        self.signals.replace_one({"_id": signal_id}, values, upsert=False)

    def dashboard_snapshot(self, pattern_key: str) -> dict[str, Any]:
        pipeline = [
            {"$match": {"pattern_key": pattern_key}},
            {
                "$group": {
                    "_id": {"status": "$status", "roulette_id": "$roulette_id"},
                    "count": {"$sum": 1},
                    "profit": {"$sum": {"$ifNull": ["$financial.net_profit", 0]}},
                    "wagered": {"$sum": {"$ifNull": ["$financial.total_wagered", 0]}},
                }
            },
        ]
        by_status: dict[str, dict[str, float | int]] = {}
        by_roulette: dict[str, dict[str, float | int]] = {}
        for row in self.signals.aggregate(pipeline):
            status = str(row.get("_id", {}).get("status") or "unknown")
            roulette_id = str(row.get("_id", {}).get("roulette_id") or "unknown")
            count = int(row.get("count") or 0)
            profit_row = float(row.get("profit") or 0)
            wagered_row = float(row.get("wagered") or 0)
            status_bucket = by_status.setdefault(status, {"count": 0, "profit": 0.0, "wagered": 0.0})
            status_bucket["count"] += count
            status_bucket["profit"] += profit_row
            status_bucket["wagered"] += wagered_row
            table = by_roulette.setdefault(
                roulette_id,
                {"active": 0, "won": 0, "lost": 0, "resolved": 0, "profit": 0.0, "wagered": 0.0},
            )
            if status in {"active", "won", "lost"}:
                table[status] += count
            if status in RESOLVED_STATUSES:
                table["resolved"] += count
                table["profit"] += profit_row
                table["wagered"] += wagered_row
        for table in by_roulette.values():
            table["assertiveness"] = table["won"] / table["resolved"] if table["resolved"] else 0.0
            table["roi_on_wagered"] = table["profit"] / table["wagered"] if table["wagered"] else 0.0
        won = by_status.get("won", {}).get("count", 0)
        lost = by_status.get("lost", {}).get("count", 0)
        resolved = won + lost
        profit = sum(by_status.get(status, {}).get("profit", 0) for status in RESOLVED_STATUSES)
        wagered = sum(by_status.get(status, {}).get("wagered", 0) for status in RESOLVED_STATUSES)
        active = list(
            self.signals.find(
                {"pattern_key": pattern_key, "status": "active"}
            ).sort("created_at", DESCENDING)
        )
        runtime = self.states.find_one(
            {"pattern_key": pattern_key, "roulette_id": "__runtime__"}
        )
        return {
            "pattern_key": pattern_key,
            "generated_at": datetime.now(timezone.utc),
            "runtime": runtime or {},
            "counts": {
                "active": len(active),
                "won": won,
                "lost": lost,
                "resolved": resolved,
                "skipped_outside_schedule": by_status.get("skipped_outside_schedule", {}).get("count", 0),
                "cancelled_gap": by_status.get("cancelled_gap", {}).get("count", 0),
            },
            "assertiveness": (won / resolved) if resolved else 0.0,
            "profit": profit,
            "wagered": wagered,
            "roi_on_wagered": (profit / wagered) if wagered else 0.0,
            "by_roulette": by_roulette,
            "active_signals": active,
        }
