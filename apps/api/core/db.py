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
    tls=False,
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
suggestion_snapshots_coll = mongo_db["suggestion_snapshots"]
suggestion_snapshot_configs_coll = mongo_db["suggestion_snapshot_configs"]
suggestion_trend_signals_coll = mongo_db["suggestion_trend_signals"]
suggestion_trend_strategy_configs_coll = mongo_db["suggestion_trend_strategy_configs"]
pattern_score_events_coll = mongo_db["pattern_score_events"]
pattern_score_state_coll = mongo_db["pattern_score_state"]
next_number_rankings_coll = mongo_db["next_number_rankings"]
next_number_sequences_coll = mongo_db["next_number_sequences"]
history_triplets_coll = mongo_db["history_triplets"]
triplet_strategy_bets_coll = mongo_db["triplet_strategy_bets"]
triplet_strategy_state_coll = mongo_db["triplet_strategy_state"]
puxado_trigger_signals_coll = mongo_db["puxado_trigger_signals"]
puxado_trigger_assertiveness_coll = mongo_db["puxado_trigger_assertiveness"]
gatilhos_coll = mongo_db["gatilhos"]
sinais_coll = mongo_db["sinais"]
roulettes_config_coll = mongo_db["roulettes_config"]
app_settings_coll = mongo_db["app_settings"]
orbit_predictions_coll = mongo_db["orbit_predictions"]
orbit_prediction_trials_coll = mongo_db["orbit_prediction_trials"]
orbit_trigger_trials_coll = mongo_db["orbit_trigger_trials"]
orbit_trigger_candidates_coll = mongo_db["orbit_trigger_candidates"]
orbit_model_runs_coll = mongo_db["orbit_model_runs"]
orbit_backtest_runs_coll = mongo_db["orbit_backtest_runs"]
orbit_snapshot_manifests_coll = mongo_db["orbit_snapshot_manifests"]

_suggestion_monitor_indexes_ready = False
_suggestion_monitor_indexes_lock = asyncio.Lock()
_occurrence_analysis_indexes_ready = False
_occurrence_analysis_indexes_lock = asyncio.Lock()
_suggestion_snapshot_indexes_ready = False
_suggestion_snapshot_indexes_lock = asyncio.Lock()
_suggestion_trend_indexes_ready = False
_suggestion_trend_indexes_lock = asyncio.Lock()
_pattern_score_indexes_ready = False
_pattern_score_indexes_lock = asyncio.Lock()
_next_number_ranking_indexes_ready = False
_next_number_ranking_indexes_lock = asyncio.Lock()
_next_number_sequence_indexes_ready = False
_next_number_sequence_indexes_lock = asyncio.Lock()
_triplet_strategy_indexes_ready = False
_triplet_strategy_indexes_lock = asyncio.Lock()
_puxado_trigger_indexes_ready = False
_puxado_trigger_indexes_lock = asyncio.Lock()
_gatilhos_indexes_ready = False
_gatilhos_indexes_lock = asyncio.Lock()
_sinais_indexes_ready = False
_sinais_indexes_lock = asyncio.Lock()
_orbit_indexes_ready = False
_orbit_indexes_lock = asyncio.Lock()


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


async def ensure_suggestion_snapshot_indexes() -> None:
    global _suggestion_snapshot_indexes_ready
    if _suggestion_snapshot_indexes_ready:
        return
    async with _suggestion_snapshot_indexes_lock:
        if _suggestion_snapshot_indexes_ready:
            return

        await _create_index_if_missing(
            suggestion_snapshots_coll,
            [("snapshot_id", ASCENDING)],
            name="suggestion_snapshots_snapshot_id",
            unique=True,
        )
        await _create_index_if_missing(
            suggestion_snapshots_coll,
            [("roulette_id", ASCENDING), ("anchor_timestamp_utc", DESCENDING)],
            name="suggestion_snapshots_roulette_anchor_ts_desc",
        )
        await _create_index_if_missing(
            suggestion_snapshots_coll,
            [("roulette_id", ASCENDING), ("anchor_history_id", ASCENDING), ("config_key", ASCENDING)],
            name="suggestion_snapshots_anchor_config",
            unique=True,
        )
        await _create_index_if_missing(
            suggestion_snapshots_coll,
            [("config_key", ASCENDING), ("created_at_utc", DESCENDING)],
            name="suggestion_snapshots_config_created_desc",
        )
        await _create_index_if_missing(
            suggestion_snapshot_configs_coll,
            [("config_id", ASCENDING)],
            name="suggestion_snapshot_configs_config_id",
            unique=True,
        )

        _suggestion_snapshot_indexes_ready = True


async def ensure_suggestion_trend_indexes() -> None:
    global _suggestion_trend_indexes_ready
    if _suggestion_trend_indexes_ready:
        return
    async with _suggestion_trend_indexes_lock:
        if _suggestion_trend_indexes_ready:
            return

        await _create_index_if_missing(
            suggestion_trend_signals_coll,
            [("signal_id", ASCENDING)],
            name="suggestion_trend_signals_signal_id",
            unique=True,
        )
        await _create_index_if_missing(
            suggestion_trend_signals_coll,
            [("roulette_id", ASCENDING), ("status", ASCENDING), ("created_at_utc", DESCENDING)],
            name="suggestion_trend_signals_roulette_status_created_desc",
        )
        await _create_index_if_missing(
            suggestion_trend_signals_coll,
            [("roulette_id", ASCENDING), ("created_at_utc", DESCENDING)],
            name="suggestion_trend_signals_roulette_created_desc",
        )
        await _create_index_if_missing(
            suggestion_trend_strategy_configs_coll,
            [("config_id", ASCENDING)],
            name="suggestion_trend_strategy_configs_config_id",
            unique=True,
        )

        _suggestion_trend_indexes_ready = True


async def ensure_pattern_score_indexes() -> None:
    global _pattern_score_indexes_ready
    if _pattern_score_indexes_ready:
        return
    async with _pattern_score_indexes_lock:
        if _pattern_score_indexes_ready:
            return

        await _create_index_if_missing(
            pattern_score_events_coll,
            [("event_id", ASCENDING)],
            name="pattern_score_events_event_id",
            unique=True,
        )
        await _create_index_if_missing(
            pattern_score_events_coll,
            [("roulette_id", ASCENDING), ("anchor_timestamp_utc", DESCENDING)],
            name="pattern_score_events_roulette_anchor_ts_desc",
        )
        await _create_index_if_missing(
            pattern_score_events_coll,
            [("roulette_id", ASCENDING), ("pattern_id", ASCENDING), ("anchor_timestamp_utc", DESCENDING)],
            name="pattern_score_events_roulette_pattern_anchor_ts_desc",
        )
        await _create_index_if_missing(
            pattern_score_state_coll,
            [("roulette_id", ASCENDING), ("pattern_id", ASCENDING)],
            name="pattern_score_state_roulette_pattern",
            unique=True,
        )
        await _create_index_if_missing(
            pattern_score_state_coll,
            [("roulette_id", ASCENDING), ("current_multiplier", DESCENDING)],
            name="pattern_score_state_roulette_multiplier_desc",
        )

        _pattern_score_indexes_ready = True


async def ensure_next_number_ranking_indexes() -> None:
    global _next_number_ranking_indexes_ready
    if _next_number_ranking_indexes_ready:
        return
    async with _next_number_ranking_indexes_lock:
        if _next_number_ranking_indexes_ready:
            return

        await _create_index_if_missing(
            next_number_rankings_coll,
            [("roulette_id", ASCENDING)],
            name="next_number_rankings_roulette_id",
            unique=True,
        )
        await _create_index_if_missing(
            next_number_rankings_coll,
            [("updated_at_utc", DESCENDING)],
            name="next_number_rankings_updated_desc",
        )

        _next_number_ranking_indexes_ready = True


async def ensure_next_number_sequence_indexes() -> None:
    global _next_number_sequence_indexes_ready
    if _next_number_sequence_indexes_ready:
        return
    async with _next_number_sequence_indexes_lock:
        if _next_number_sequence_indexes_ready:
            return

        await _create_index_if_missing(
            next_number_sequences_coll,
            [("roulette_id", ASCENDING), ("base_history_id", ASCENDING)],
            name="next_number_sequences_roulette_history",
            unique=True,
        )
        await _create_index_if_missing(
            next_number_sequences_coll,
            [("roulette_id", ASCENDING), ("base_number", ASCENDING), ("base_hour_br", ASCENDING)],
            name="next_number_sequences_roulette_base_hour_br",
        )
        await _create_index_if_missing(
            next_number_sequences_coll,
            [("roulette_id", ASCENDING), ("base_timestamp_utc", DESCENDING)],
            name="next_number_sequences_roulette_base_ts_desc",
        )
        await _create_index_if_missing(
            next_number_sequences_coll,
            [("roulette_id", ASCENDING), ("base_number", ASCENDING), ("base_timestamp_utc", DESCENDING)],
            name="next_number_sequences_roulette_base_number_ts_desc",
        )

        _next_number_sequence_indexes_ready = True


async def ensure_triplet_strategy_indexes() -> None:
    global _triplet_strategy_indexes_ready
    if _triplet_strategy_indexes_ready:
        return
    async with _triplet_strategy_indexes_lock:
        if _triplet_strategy_indexes_ready:
            return

        await _create_index_if_missing(
            triplet_strategy_bets_coll,
            [("roulette_id", ASCENDING), ("status", ASCENDING), ("resolved_at", ASCENDING)],
            name="triplet_strategy_bets_roulette_status_resolved",
        )

        _triplet_strategy_indexes_ready = True


async def ensure_puxado_trigger_indexes() -> None:
    global _puxado_trigger_indexes_ready
    if _puxado_trigger_indexes_ready:
        return
    async with _puxado_trigger_indexes_lock:
        if _puxado_trigger_indexes_ready:
            return

        await _create_index_if_missing(
            puxado_trigger_signals_coll,
            [("roulette_id", ASCENDING), ("status", ASCENDING)],
            name="puxado_trigger_rid_status",
        )
        await _create_index_if_missing(
            puxado_trigger_signals_coll,
            [("roulette_id", ASCENDING), ("created_at", DESCENDING)],
            name="puxado_trigger_rid_created",
        )
        await _create_index_if_missing(
            puxado_trigger_signals_coll,
            [
                ("roulette_id", ASCENDING),
                ("triplet_a", ASCENDING),
                ("triplet_b", ASCENDING),
                ("triplet_c", ASCENDING),
                ("trigger_number", ASCENDING),
                ("status", ASCENDING),
            ],
            name="puxado_trigger_dedup",
        )

        _puxado_trigger_indexes_ready = True


async def ensure_gatilhos_indexes() -> None:
    global _gatilhos_indexes_ready
    if _gatilhos_indexes_ready:
        return
    async with _gatilhos_indexes_lock:
        if _gatilhos_indexes_ready:
            return

        await _create_index_if_missing(
            gatilhos_coll,
            [("trigger_number", ASCENDING), ("status", ASCENDING)],
            name="g_trigger_status",
        )
        await _create_index_if_missing(
            gatilhos_coll,
            [("roulette_id", ASCENDING), ("status", ASCENDING), ("created_at", DESCENDING)],
            name="g_roulette_status_created",
        )
        await _create_index_if_missing(
            gatilhos_coll,
            [("roulette_id", ASCENDING), ("triplet_a", ASCENDING), ("triplet_b", ASCENDING),
             ("triplet_c", ASCENDING), ("trigger_number", ASCENDING), ("status", ASCENDING)],
            name="g_dedup",
        )
        await _create_index_if_missing(
            gatilhos_coll,
            [("created_at", DESCENDING)],
            name="g_created_desc",
        )
        await _create_index_if_missing(
            gatilhos_coll,
            [("status", ASCENDING), ("created_at", ASCENDING)],
            name="g_status_expiry",
        )

        _gatilhos_indexes_ready = True


async def ensure_sinais_indexes() -> None:
    global _sinais_indexes_ready
    if _sinais_indexes_ready:
        return
    async with _sinais_indexes_lock:
        if _sinais_indexes_ready:
            return

        await _create_index_if_missing(
            sinais_coll,
            [("fired_roulette_id", ASCENDING), ("status", ASCENDING)],
            name="s_fired_status",
        )
        await _create_index_if_missing(
            sinais_coll,
            [("gatilho_id", ASCENDING), ("created_at", DESCENDING)],
            name="s_gatilho_created",
        )
        await _create_index_if_missing(
            sinais_coll,
            [("trigger_number", ASCENDING), ("status", ASCENDING), ("created_at", DESCENDING)],
            name="s_trigger_status_created",
        )
        await _create_index_if_missing(
            sinais_coll,
            [("created_at", DESCENDING)],
            name="s_created_desc",
        )
        await _create_index_if_missing(
            sinais_coll,
            [("status", ASCENDING), ("created_at", ASCENDING)],
            name="s_status_expiry",
        )

        _sinais_indexes_ready = True


async def ensure_orbit_indexes() -> None:
    global _orbit_indexes_ready
    if _orbit_indexes_ready:
        return
    async with _orbit_indexes_lock:
        if _orbit_indexes_ready:
            return

        await _create_index_if_missing(
            orbit_predictions_coll,
            [("prediction_id", ASCENDING)],
            name="orbit_predictions_prediction_id",
            unique=True,
        )
        await _create_index_if_missing(
            orbit_predictions_coll,
            [("roulette_id", ASCENDING), ("anchor_timestamp_utc", DESCENDING)],
            name="orbit_predictions_roulette_anchor_desc",
        )
        await _create_index_if_missing(
            orbit_predictions_coll,
            [("roulette_id", ASCENDING), ("engine_version", ASCENDING), ("anchor_timestamp_utc", DESCENDING)],
            name="orbit_predictions_engine_anchor_desc",
        )
        await _create_index_if_missing(
            orbit_prediction_trials_coll,
            [("trial_id", ASCENDING)],
            name="orbit_trials_trial_id",
            unique=True,
        )
        await _create_index_if_missing(
            orbit_prediction_trials_coll,
            [("roulette_id", ASCENDING), ("anchor_timestamp_utc", DESCENDING)],
            name="orbit_trials_roulette_anchor_desc",
        )
        await _create_index_if_missing(
            orbit_prediction_trials_coll,
            [("roulette_id", ASCENDING), ("status", ASCENDING), ("anchor_timestamp_utc", DESCENDING)],
            name="orbit_trials_status_anchor_desc",
        )
        await _create_index_if_missing(
            orbit_trigger_trials_coll,
            [("event_id", ASCENDING)],
            name="orbit_trigger_trials_event_id",
            unique=True,
        )
        await _create_index_if_missing(
            orbit_trigger_trials_coll,
            [
                ("strategy_slug", ASCENDING),
                ("roulette_id", ASCENDING),
                ("activation_timestamp_utc", DESCENDING),
            ],
            name="orbit_trigger_trials_strategy_roulette_activation_desc",
        )
        await _create_index_if_missing(
            orbit_trigger_trials_coll,
            [
                ("strategy_slug", ASCENDING),
                ("roulette_id", ASCENDING),
                ("status", ASCENDING),
                ("activation_timestamp_utc", DESCENDING),
            ],
            name="orbit_trigger_trials_strategy_status_activation_desc",
        )
        await _create_index_if_missing(
            orbit_trigger_candidates_coll,
            [("candidate_id", ASCENDING)],
            name="orbit_trigger_candidates_candidate_id",
            unique=True,
        )
        await _create_index_if_missing(
            orbit_trigger_candidates_coll,
            [
                ("roulette_id", ASCENDING),
                ("strategy_slug", ASCENDING),
                ("status", ASCENDING),
                ("created_at_utc", ASCENDING),
            ],
            name="orbit_trigger_candidates_active",
        )
        await _create_index_if_missing(
            orbit_model_runs_coll,
            [("model_run_id", ASCENDING)],
            name="orbit_model_runs_id",
            unique=True,
        )
        await _create_index_if_missing(
            orbit_model_runs_coll,
            [("roulette_id", ASCENDING), ("created_at_utc", DESCENDING)],
            name="orbit_model_runs_roulette_created_desc",
        )
        await _create_index_if_missing(
            orbit_backtest_runs_coll,
            [("backtest_id", ASCENDING)],
            name="orbit_backtest_runs_id",
            unique=True,
        )
        await _create_index_if_missing(
            orbit_backtest_runs_coll,
            [("roulette_id", ASCENDING), ("created_at_utc", DESCENDING)],
            name="orbit_backtest_runs_roulette_created_desc",
        )
        await _create_index_if_missing(
            orbit_snapshot_manifests_coll,
            [("snapshot_id", ASCENDING)],
            name="orbit_snapshot_manifests_id",
            unique=True,
        )

        _orbit_indexes_ready = True
