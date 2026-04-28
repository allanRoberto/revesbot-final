from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha1
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING

from .mongo import mongo_db
from .suggestion_monitor_runtime import normalize_history_doc
from .time_window_prior import BR_TZ, build_daily_window_bounds


def _roulette_filter(roulette_id: str) -> Dict[str, Any]:
    safe_roulette_id = str(roulette_id or "").strip()
    return {
        "$or": [
            {"roulette_id": safe_roulette_id},
            {"slug": safe_roulette_id},
        ]
    }


def _roulette_query_variants(roulette_id: str) -> List[Dict[str, Any]]:
    safe_roulette_id = str(roulette_id or "").strip()
    if not safe_roulette_id:
        return []
    return [
        {"roulette_id": safe_roulette_id},
        {"slug": safe_roulette_id},
    ]


def _combine_query(
    roulette_query: Mapping[str, Any],
    *conditions: Mapping[str, Any],
) -> Dict[str, Any]:
    clauses: List[Dict[str, Any]] = [dict(roulette_query)]
    clauses.extend(dict(condition) for condition in conditions if condition)
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _offset_document_id(config_key: str) -> str:
    digest = sha1(config_key.encode("utf-8")).hexdigest()[:12]
    return f"smonitor-offset:{digest}"


def _to_object_id(value: Any) -> ObjectId | None:
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(str(value))
    except Exception:
        return None


class SuggestionMonitorRepository:
    def __init__(self) -> None:
        self.history_coll = mongo_db["history"]
        self.events_coll = mongo_db["suggestion_monitor_events"]
        self.attempts_coll = mongo_db["suggestion_monitor_attempts"]
        self.offsets_coll = mongo_db["suggestion_monitor_offsets"]
        self.pattern_outcomes_coll = mongo_db["suggestion_monitor_pattern_outcomes"]
        self.model_states_coll = mongo_db["suggestion_monitor_model_states"]

    def ensure_indexes(self) -> None:
        self.history_coll.create_index(
            [("roulette_id", ASCENDING), ("timestamp", DESCENDING), ("_id", DESCENDING)],
            name="history_roulette_ts_desc",
        )
        self.events_coll.create_index(
            [("roulette_id", ASCENDING), ("anchor_timestamp_utc", DESCENDING)],
            name="smonitor_events_roulette_time",
        )
        self.events_coll.create_index(
            [("roulette_id", ASCENDING), ("status", ASCENDING), ("anchor_timestamp_utc", DESCENDING)],
            name="smonitor_events_roulette_status_time",
        )
        self.events_coll.create_index(
            [("roulette_id", ASCENDING), ("ranking_variant", ASCENDING), ("anchor_timestamp_utc", DESCENDING)],
            name="smonitor_events_roulette_variant_time",
        )
        self.events_coll.create_index(
            [("roulette_id", ASCENDING), ("ranking_variant", ASCENDING), ("status", ASCENDING), ("anchor_timestamp_utc", DESCENDING)],
            name="smonitor_events_roulette_variant_status_time",
        )
        self.events_coll.create_index(
            [("roulette_id", ASCENDING), ("config_key", ASCENDING), ("anchor_timestamp_utc", DESCENDING)],
            name="smonitor_events_config_time",
        )
        self.events_coll.create_index(
            [("roulette_id", ASCENDING), ("config_key", ASCENDING), ("status", ASCENDING), ("anchor_timestamp_utc", DESCENDING)],
            name="smonitor_events_status",
        )
        self.events_coll.create_index(
            [("roulette_id", ASCENDING), ("config_key", ASCENDING), ("anchor_number", ASCENDING), ("anchor_timestamp_utc", DESCENDING)],
            name="smonitor_events_anchor",
        )
        self.events_coll.create_index(
            [("roulette_id", ASCENDING), ("config_key", ASCENDING), ("resolved_attempt", ASCENDING), ("anchor_timestamp_utc", DESCENDING)],
            name="smonitor_events_attempt",
        )
        self.events_coll.create_index(
            [("anchor_history_id", ASCENDING), ("config_key", ASCENDING)],
            name="smonitor_events_anchor_history",
        )
        self.attempts_coll.create_index(
            [("suggestion_event_id", ASCENDING), ("attempt_number", ASCENDING)],
            name="smonitor_attempts_event_attempt",
        )
        self.attempts_coll.create_index(
            [("roulette_id", ASCENDING), ("result_timestamp_utc", DESCENDING)],
            name="smonitor_attempts_result_time",
        )
        self.pattern_outcomes_coll.create_index(
            [("roulette_id", ASCENDING), ("pattern_id", ASCENDING), ("anchor_timestamp_utc", DESCENDING)],
            name="smonitor_pattern_pattern_time",
        )
        self.pattern_outcomes_coll.create_index(
            [("suggestion_event_id", ASCENDING), ("pattern_id", ASCENDING)],
            name="smonitor_pattern_event_pattern",
        )
        self.model_states_coll.create_index(
            [("roulette_id", ASCENDING), ("config_key", ASCENDING), ("model_name", ASCENDING)],
            name="smonitor_model_state_config",
            unique=True,
        )
        self.offsets_coll.create_index(
            [("roulette_id", ASCENDING), ("config_key", ASCENDING)],
            name="smonitor_offsets_config",
            unique=True,
        )

    def get_offset(self, *, config_key: str) -> Dict[str, Any] | None:
        doc = self.offsets_coll.find_one({"_id": _offset_document_id(config_key)})
        return dict(doc) if isinstance(doc, Mapping) else None

    def save_offset(self, *, config_key: str, roulette_id: str, history_doc: Mapping[str, Any]) -> Dict[str, Any]:
        document = {
            "_id": _offset_document_id(config_key),
            "config_key": config_key,
            "roulette_id": roulette_id,
            "last_history_id": str(history_doc["history_id"]),
            "last_history_timestamp_utc": history_doc["history_timestamp_utc"],
            "last_history_number": int(history_doc["value"]),
            "updated_at": datetime.now(timezone.utc),
        }
        self.offsets_coll.update_one({"_id": document["_id"]}, {"$set": document}, upsert=True)
        return document

    def get_latest_history_doc(self, roulette_id: str) -> Dict[str, Any] | None:
        for roulette_query in _roulette_query_variants(roulette_id):
            doc = self.history_coll.find_one(
                dict(roulette_query),
                sort=[("timestamp", DESCENDING), ("_id", DESCENDING)],
            )
            if isinstance(doc, Mapping):
                return normalize_history_doc(doc)
        return None

    def get_new_history_docs(
        self,
        *,
        roulette_id: str,
        last_history_timestamp_utc: datetime,
        last_history_id: str,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        object_id = _to_object_id(last_history_id)
        time_query: Dict[str, Any]
        if object_id is not None:
            time_query = {
                "$or": [
                    {"timestamp": {"$gt": last_history_timestamp_utc}},
                    {"timestamp": last_history_timestamp_utc, "_id": {"$gt": object_id}},
                ]
            }
        else:
            time_query = {"timestamp": {"$gt": last_history_timestamp_utc}}

        for roulette_query in _roulette_query_variants(roulette_id):
            docs = list(
                self.history_coll.find(_combine_query(roulette_query, time_query))
                .sort([("timestamp", ASCENDING), ("_id", ASCENDING)])
                .limit(int(limit))
            )
            if docs:
                return [normalize_history_doc(doc) for doc in docs if isinstance(doc, Mapping)]
        return []

    def count_new_history_docs(
        self,
        *,
        roulette_id: str,
        last_history_timestamp_utc: datetime,
        last_history_id: str,
    ) -> int:
        object_id = _to_object_id(last_history_id)
        if object_id is not None:
            time_query: Dict[str, Any] = {
                "$or": [
                    {"timestamp": {"$gt": last_history_timestamp_utc}},
                    {"timestamp": last_history_timestamp_utc, "_id": {"$gt": object_id}},
                ]
            }
        else:
            time_query = {"timestamp": {"$gt": last_history_timestamp_utc}}
        for roulette_query in _roulette_query_variants(roulette_id):
            count = int(self.history_coll.count_documents(_combine_query(roulette_query, time_query)))
            if count > 0:
                return count
        return 0

    def mark_pending_events_unavailable(
        self,
        *,
        roulette_id: str,
        config_keys: Sequence[str],
        reason: str,
    ) -> int:
        clean_keys = [str(key).strip() for key in config_keys if str(key).strip()]
        if not clean_keys:
            return 0
        result = self.events_coll.update_many(
            {
                "roulette_id": roulette_id,
                "config_key": {"$in": clean_keys},
                "status": "pending",
            },
            {
                "$set": {
                    "status": "unavailable",
                    "unavailable_reason": "fast_forward_on_backlog",
                    "explanation": reason,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )
        return int(result.modified_count or 0)

    def get_history_window_up_to(
        self,
        *,
        roulette_id: str,
        anchor_history_timestamp_utc: datetime,
        anchor_history_id: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        object_id = _to_object_id(anchor_history_id)
        if object_id is not None:
            time_query: Dict[str, Any] = {
                "$or": [
                    {"timestamp": {"$lt": anchor_history_timestamp_utc}},
                    {"timestamp": anchor_history_timestamp_utc, "_id": {"$lte": object_id}},
                ]
            }
        else:
            time_query = {"timestamp": {"$lte": anchor_history_timestamp_utc}}

        for roulette_query in _roulette_query_variants(roulette_id):
            docs = list(
                self.history_coll.find(_combine_query(roulette_query, time_query))
                .sort([("timestamp", DESCENDING), ("_id", DESCENDING)])
                .limit(int(limit))
            )
            if docs:
                return [normalize_history_doc(doc) for doc in docs if isinstance(doc, Mapping)]
        return []

    def get_history_docs_by_time_window_days(
        self,
        *,
        roulette_id: str,
        reference_timestamp_utc: datetime,
        lookback_days: int,
        minute_span: int,
    ) -> Dict[str, List[Dict[str, Any]]]:
        if reference_timestamp_utc.tzinfo is None:
            reference_timestamp_utc = reference_timestamp_utc.replace(tzinfo=timezone.utc)
        else:
            reference_timestamp_utc = reference_timestamp_utc.astimezone(timezone.utc)

        reference_br = reference_timestamp_utc.astimezone(BR_TZ)
        docs_by_day: Dict[str, List[Dict[str, Any]]] = {}
        for days_ago in range(1, max(1, int(lookback_days)) + 1):
            day_reference_br = reference_br - timedelta(days=days_ago)
            start_br, end_br = build_daily_window_bounds(day_reference_br, minute_span=minute_span)
            start_utc = start_br.astimezone(timezone.utc)
            end_utc = end_br.astimezone(timezone.utc)
            day_docs: List[Dict[str, Any]] = []
            time_query = {"timestamp": {"$gte": start_utc, "$lt": end_utc}}
            for roulette_query in _roulette_query_variants(roulette_id):
                docs = list(
                    self.history_coll.find(_combine_query(roulette_query, time_query))
                    .sort([("timestamp", ASCENDING), ("_id", ASCENDING)])
                )
                if docs:
                    day_docs = [dict(doc) for doc in docs if isinstance(doc, Mapping)]
                    break
            docs_by_day[day_reference_br.strftime("%Y-%m-%d")] = day_docs
        return docs_by_day

    def load_pending_events(self, *, roulette_id: str, config_key: str) -> List[Dict[str, Any]]:
        docs = list(
            self.events_coll.find(
                {"roulette_id": roulette_id, "config_key": config_key, "status": "pending"}
            ).sort([("anchor_timestamp_utc", ASCENDING), ("anchor_history_id", ASCENDING)])
        )
        return [dict(doc) for doc in docs if isinstance(doc, Mapping)]

    def get_latest_resolved_event(self, *, roulette_id: str, config_key: str) -> Dict[str, Any] | None:
        doc = self.events_coll.find_one(
            {"roulette_id": roulette_id, "config_key": config_key, "status": "resolved"},
            sort=[("anchor_timestamp_utc", DESCENDING), ("_id", DESCENDING)],
        )
        return dict(doc) if isinstance(doc, Mapping) else None

    def get_latest_event(self, *, roulette_id: str, config_key: str) -> Dict[str, Any] | None:
        doc = self.events_coll.find_one(
            {"roulette_id": roulette_id, "config_key": config_key},
            sort=[("anchor_timestamp_utc", DESCENDING), ("_id", DESCENDING)],
        )
        return dict(doc) if isinstance(doc, Mapping) else None

    def get_recent_resolved_events(
        self,
        *,
        roulette_id: str,
        config_key: str,
        limit: int = 8,
    ) -> List[Dict[str, Any]]:
        docs = list(
            self.events_coll.find(
                {"roulette_id": roulette_id, "config_key": config_key, "status": "resolved"}
            )
            .sort([("anchor_timestamp_utc", DESCENDING), ("_id", DESCENDING)])
            .limit(int(limit))
        )
        return [dict(doc) for doc in docs if isinstance(doc, Mapping)]

    def get_model_state(
        self,
        *,
        roulette_id: str,
        config_key: str,
        model_name: str,
    ) -> Dict[str, Any] | None:
        doc = self.model_states_coll.find_one(
            {
                "roulette_id": str(roulette_id or "").strip(),
                "config_key": str(config_key or "").strip(),
                "model_name": str(model_name or "").strip(),
            }
        )
        return dict(doc) if isinstance(doc, Mapping) else None

    def save_model_state(self, model_state: Mapping[str, Any]) -> None:
        document = dict(model_state)
        if "_id" not in document:
            digest = sha1(
                f"{document.get('roulette_id')}|{document.get('config_key')}|{document.get('model_name')}".encode("utf-8")
            ).hexdigest()[:12]
            document["_id"] = f"smonitor-ml:{digest}"
        self.model_states_coll.replace_one({"_id": document["_id"]}, document, upsert=True)

    def upsert_event(self, event_doc: Mapping[str, Any]) -> None:
        self.events_coll.replace_one({"_id": event_doc["_id"]}, dict(event_doc), upsert=True)

    def upsert_pattern_outcomes(self, documents: Sequence[Mapping[str, Any]]) -> None:
        for document in documents:
            self.pattern_outcomes_coll.replace_one({"_id": document["_id"]}, dict(document), upsert=True)

    def apply_attempt(
        self,
        *,
        event_doc: Mapping[str, Any],
        attempt_doc: Mapping[str, Any],
        resolution_fields: Mapping[str, Any],
        pattern_resolution_docs: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        result_history_id = str(attempt_doc["result_history_id"])
        if str(event_doc.get("last_attempt_history_id") or "") == result_history_id:
            return dict(event_doc)

        self.attempts_coll.update_one(
            {"_id": attempt_doc["_id"]},
            {"$setOnInsert": dict(attempt_doc)},
            upsert=True,
        )
        self.events_coll.update_one(
            {"_id": event_doc["_id"], "last_attempt_history_id": {"$ne": result_history_id}},
            {"$set": dict(resolution_fields)},
        )
        for pattern_doc in pattern_resolution_docs:
            payload = dict(pattern_doc)
            identifier = payload.pop("_id")
            self.pattern_outcomes_coll.update_one({"_id": identifier}, {"$set": payload}, upsert=True)

        updated = dict(event_doc)
        updated.update(dict(resolution_fields))
        return updated
