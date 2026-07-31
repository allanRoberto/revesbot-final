from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Sequence
from zoneinfo import ZoneInfo

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, ReturnDocument

from .minute_region_signal_runtime import apply_result_to_signal, number_color
from .mongo import mongo_db


BR_TZ = ZoneInfo("America/Sao_Paulo")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _history_id_query(history_id: str) -> Any:
    try:
        return ObjectId(str(history_id))
    except Exception:
        return history_id


def serialize_history_doc(doc: Mapping[str, Any]) -> Dict[str, Any]:
    timestamp_utc = _as_utc(doc["timestamp"])
    timestamp_br = timestamp_utc.astimezone(BR_TZ)
    value = int(doc["value"])
    return {
        "history_id": str(doc.get("_id") or ""),
        "value": value,
        "color": number_color(value),
        "timestamp_utc": timestamp_utc,
        "timestamp_br": timestamp_br,
        "formatted": timestamp_br.strftime("%d/%m/%Y %H:%M:%S"),
    }


class MinuteRegionSignalRepository:
    def __init__(self) -> None:
        self.history_coll = mongo_db["history"]
        self.signals_coll = mongo_db["minute_region_signals"]

    def ensure_indexes(self) -> None:
        self.history_coll.create_index(
            [("roulette_id", ASCENDING), ("timestamp", DESCENDING), ("_id", DESCENDING)],
            name="history_roulette_ts_desc",
        )
        self.signals_coll.create_index(
            [("roulette_id", ASCENDING), ("signal_minute_utc", DESCENDING)],
            name="minute_region_roulette_minute_desc",
            unique=True,
        )
        self.signals_coll.create_index(
            [("roulette_id", ASCENDING), ("status", ASCENDING), ("signal_minute_utc", DESCENDING)],
            name="minute_region_roulette_status_minute_desc",
        )
        self.signals_coll.create_index(
            [("status", ASCENDING), ("updated_at_utc", DESCENDING)],
            name="minute_region_status_updated_desc",
        )

    def fetch_training_days(
        self,
        *,
        roulette_id: str,
        signal_minute_br: datetime,
        training_days: int,
        window_minutes: int,
    ) -> List[Dict[str, Any]]:
        windows = []
        day_meta = []
        for day_offset in range(1, max(1, int(training_days)) + 1):
            target = signal_minute_br - timedelta(days=day_offset)
            start_utc = (target - timedelta(minutes=window_minutes)).astimezone(timezone.utc)
            end_utc = (target + timedelta(minutes=window_minutes)).astimezone(timezone.utc)
            windows.append({"timestamp": {"$gte": start_utc, "$lte": end_utc}})
            day_meta.append((day_offset, target, start_utc, end_utc))

        docs = list(
            self.history_coll.find(
                {"roulette_id": roulette_id, "$or": windows},
                {"_id": 1, "value": 1, "timestamp": 1},
            ).sort([("timestamp", ASCENDING), ("_id", ASCENDING)])
        )

        days = []
        for day_offset, target, start_utc, end_utc in day_meta:
            items = [
                serialize_history_doc(doc)
                for doc in docs
                if start_utc <= _as_utc(doc["timestamp"]) <= end_utc
            ]
            days.append(
                {
                    "day_offset": day_offset,
                    "target": target,
                    "items": items,
                }
            )
        return days

    def fetch_previous_results(
        self,
        *,
        roulette_id: str,
        before_utc: datetime,
        limit: int,
    ) -> List[Dict[str, Any]]:
        docs = list(
            self.history_coll.find(
                {"roulette_id": roulette_id, "timestamp": {"$lte": before_utc}},
                {"_id": 1, "value": 1, "timestamp": 1},
            )
            .sort([("timestamp", DESCENDING), ("_id", DESCENDING)])
            .limit(max(1, int(limit)))
        )
        return [serialize_history_doc(doc) for doc in docs]

    def create_signal_if_missing(self, document: Mapping[str, Any]) -> tuple[Dict[str, Any], bool]:
        query = {
            "roulette_id": document["roulette_id"],
            "signal_minute_utc": document["signal_minute_utc"],
        }
        existing = self.signals_coll.find_one(query)
        if existing:
            return dict(existing), False

        result = self.signals_coll.find_one_and_update(
            query,
            {"$setOnInsert": dict(document)},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return dict(result), str(result.get("signal_key")) == str(document.get("signal_key"))

    def list_active_signals(self, roulette_id: str) -> List[Dict[str, Any]]:
        return [
            dict(doc)
            for doc in self.signals_coll.find(
                {"roulette_id": roulette_id, "status": "active"}
            ).sort("signal_minute_utc", ASCENDING)
        ]

    def fetch_results_for_signal(self, signal: Mapping[str, Any]) -> List[Dict[str, Any]]:
        attempts = list(signal.get("attempts", []))
        if attempts:
            last = attempts[-1]
            timestamp = _as_utc(last["timestamp_utc"])
            object_id = _history_id_query(str(last["result_history_id"]))
            after_query = {
                "$or": [
                    {"timestamp": {"$gt": timestamp}},
                    {"timestamp": timestamp, "_id": {"$gt": object_id}},
                ]
            }
        else:
            after_query = {"timestamp": {"$gt": _as_utc(signal["generated_at_utc"])}}

        remaining = max(
            0,
            int(signal.get("config", {}).get("max_attempts", 10)) - int(signal.get("attempt_count", 0)),
        )
        if remaining <= 0:
            return []
        docs = list(
            self.history_coll.find(
                {"roulette_id": signal["roulette_id"], **after_query},
                {"_id": 1, "value": 1, "timestamp": 1},
            )
            .sort([("timestamp", ASCENDING), ("_id", ASCENDING)])
            .limit(remaining)
        )
        return [serialize_history_doc(doc) for doc in docs]

    def apply_result(self, signal: Mapping[str, Any], result: Mapping[str, Any]) -> Dict[str, Any]:
        updated = apply_result_to_signal(signal, result)
        if int(updated.get("attempt_count", 0)) == int(signal.get("attempt_count", 0)):
            return dict(signal)

        query = {
            "_id": signal["_id"],
            "status": "active",
            "attempt_count": int(signal.get("attempt_count", 0)),
            "attempts.result_history_id": {"$ne": str(result["history_id"])},
        }
        fields = {
            "attempts": updated["attempts"],
            "attempt_count": updated["attempt_count"],
            "payment_count": updated["payment_count"],
            "status": updated["status"],
            "completed_at_utc": updated["completed_at_utc"],
            "updated_at_utc": updated["updated_at_utc"],
        }
        stored = self.signals_coll.find_one_and_update(
            query,
            {"$set": fields},
            return_document=ReturnDocument.AFTER,
        )
        return dict(stored) if stored else dict(self.signals_coll.find_one({"_id": signal["_id"]}))
