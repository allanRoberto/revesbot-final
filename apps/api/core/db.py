# core/db.py
import asyncio
import certifi
import pytz
import redis
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import OperationFailure
from pymongo import ASCENDING, DESCENDING

from api.core.config import settings

# ─── Conexão MongoDB / Motor ───────────────────────────────────────────────────
MONGO_URL = settings.mongo_url
mongo_client = AsyncIOMotorClient(
    MONGO_URL,
    tls=True,
    tlsCAFile=certifi.where()
)
mongo_db     = mongo_client["roleta_db"]
history_coll = mongo_db["history"]
agent_sessions_coll = mongo_db["agent_sessions"]
agent_templates_coll = mongo_db["agent_templates"]

# Função utilitária (mantida aqui se outros módulos precisarem)
def format_timestamp_br(timestamp: int) -> str:
    tz = pytz.timezone("America/Sao_Paulo")
    dt = datetime.fromtimestamp(timestamp, tz)
    return dt.strftime("%d/%m/%Y %H:%M:%S")

predictions_norm_coll = mongo_db["predictions_normalized"]
suggestion_monitor_events_coll = mongo_db["suggestion_monitor_events"]
suggestion_monitor_attempts_coll = mongo_db["suggestion_monitor_attempts"]
suggestion_monitor_offsets_coll = mongo_db["suggestion_monitor_offsets"]
suggestion_monitor_pattern_outcomes_coll = mongo_db["suggestion_monitor_pattern_outcomes"]
occurrence_analysis_runs_coll = mongo_db["occurrence_analysis_runs"]
occurrence_analysis_events_coll = mongo_db["occurrence_analysis_events"]

_suggestion_monitor_indexes_ready = False
_suggestion_monitor_indexes_lock = asyncio.Lock()
_occurrence_analysis_indexes_ready = False
_occurrence_analysis_indexes_lock = asyncio.Lock()


async def _create_index_if_missing(collection, keys, name: str, **kwargs) -> None:
    normalized_keys = tuple((str(field), int(direction)) for field, direction in keys)
    try:
        existing = await collection.index_information()
    except Exception:
        existing = {}
    for spec in existing.values():
        spec_keys = tuple((str(field), int(direction)) for field, direction in spec.get("key", []))
        if spec_keys == normalized_keys:
            return
    try:
        await collection.create_index(keys, name=name, **kwargs)
    except OperationFailure as exc:
        message = str(exc)
        if "Index already exists with a different name" in message or "IndexOptionsConflict" in message:
            return
        raise


async def ensure_suggestion_monitor_indexes() -> None:
    global _suggestion_monitor_indexes_ready
    if _suggestion_monitor_indexes_ready:
        return
    async with _suggestion_monitor_indexes_lock:
        if _suggestion_monitor_indexes_ready:
            return

        await _create_index_if_missing(
            suggestion_monitor_events_coll,
            [("roulette_id", ASCENDING), ("anchor_timestamp_utc", DESCENDING)],
            name="sm_events_roulette_anchor_ts_desc",
        )
        await _create_index_if_missing(
            suggestion_monitor_events_coll,
            [("roulette_id", ASCENDING), ("status", ASCENDING), ("anchor_timestamp_utc", DESCENDING)],
            name="sm_events_roulette_status_anchor_ts_desc",
        )
        await _create_index_if_missing(
            suggestion_monitor_events_coll,
            [("roulette_id", ASCENDING), ("ranking_variant", ASCENDING), ("anchor_timestamp_utc", DESCENDING)],
            name="sm_events_roulette_variant_anchor_ts_desc",
        )
        await _create_index_if_missing(
            suggestion_monitor_events_coll,
            [("roulette_id", ASCENDING), ("ranking_variant", ASCENDING), ("status", ASCENDING), ("anchor_timestamp_utc", DESCENDING)],
            name="sm_events_roulette_variant_status_anchor_ts_desc",
        )
        await _create_index_if_missing(
            suggestion_monitor_events_coll,
            [("roulette_id", ASCENDING), ("config_key", ASCENDING), ("anchor_timestamp_utc", DESCENDING)],
            name="sm_events_roulette_config_anchor_ts_desc",
        )
        await _create_index_if_missing(
            suggestion_monitor_events_coll,
            [("roulette_id", ASCENDING), ("config_key", ASCENDING), ("status", ASCENDING), ("anchor_timestamp_utc", DESCENDING)],
            name="sm_events_roulette_config_status_anchor_ts_desc",
        )
        await _create_index_if_missing(
            suggestion_monitor_events_coll,
            [("roulette_id", ASCENDING), ("ranking_variant", ASCENDING), ("resolved_attempt", ASCENDING), ("anchor_timestamp_utc", DESCENDING)],
            name="sm_events_roulette_variant_attempt_anchor_ts_desc",
        )
        await _create_index_if_missing(
            suggestion_monitor_pattern_outcomes_coll,
            [("suggestion_event_id", ASCENDING), ("pattern_id", ASCENDING)],
            name="sm_pattern_event_pattern",
        )
        await _create_index_if_missing(
            suggestion_monitor_pattern_outcomes_coll,
            [("roulette_id", ASCENDING), ("pattern_id", ASCENDING), ("anchor_timestamp_utc", DESCENDING)],
            name="sm_pattern_roulette_pattern_anchor_ts_desc",
        )

        _suggestion_monitor_indexes_ready = True


async def ensure_occurrence_analysis_indexes() -> None:
    global _occurrence_analysis_indexes_ready
    if _occurrence_analysis_indexes_ready:
        return
    async with _occurrence_analysis_indexes_lock:
        if _occurrence_analysis_indexes_ready:
            return

        await _create_index_if_missing(
            occurrence_analysis_runs_coll,
            [("run_id", ASCENDING)],
            name="occ_runs_run_id",
            unique=True,
        )
        await _create_index_if_missing(
            occurrence_analysis_runs_coll,
            [("roulette_id", ASCENDING), ("created_at_utc", DESCENDING)],
            name="occ_runs_roulette_created_desc",
        )
        await _create_index_if_missing(
            occurrence_analysis_runs_coll,
            [("mode", ASCENDING), ("status", ASCENDING), ("created_at_utc", DESCENDING)],
            name="occ_runs_mode_status_created_desc",
        )
        await _create_index_if_missing(
            occurrence_analysis_events_coll,
            [("event_id", ASCENDING)],
            name="occ_events_event_id",
            unique=True,
        )
        await _create_index_if_missing(
            occurrence_analysis_events_coll,
            [("run_id", ASCENDING), ("created_at_utc", DESCENDING)],
            name="occ_events_run_created_desc",
        )
        await _create_index_if_missing(
            occurrence_analysis_events_coll,
            [("roulette_id", ASCENDING), ("status", ASCENDING), ("created_at_utc", DESCENDING)],
            name="occ_events_roulette_status_created_desc",
        )
        await _create_index_if_missing(
            occurrence_analysis_events_coll,
            [("roulette_id", ASCENDING), ("mode", ASCENDING), ("created_at_utc", DESCENDING)],
            name="occ_events_roulette_mode_created_desc",
        )

        _occurrence_analysis_indexes_ready = True
