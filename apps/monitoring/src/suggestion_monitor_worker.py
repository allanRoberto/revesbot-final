from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Mapping

import aiohttp
import redis.asyncio as aioredis

from src.config import settings
from src.ml_entry_gate import (
    build_default_ml_entry_gate_state,
    build_ml_entry_gate_payload_from_ml_meta,
    build_ml_top12_reference_payload_from_ml_meta,
    train_ml_entry_gate_state_from_ml_meta_event,
    train_ml_entry_gate_state_from_reference_event,
)
from src.ml_meta_rank import (
    build_default_ml_meta_rank_state,
    build_ml_meta_rank_payload_from_context,
    train_ml_meta_rank_state_from_resolved_event,
)
from src.suggestion_monitor_repo import SuggestionMonitorRepository
from src.suggestion_monitor_runtime import (
    build_attempt_document,
    build_config_key,
    build_event_resolution_fields,
    build_monitor_event_document,
    apply_rank_confidence_feedback,
    build_time_window_prior_payload_from_base,
    build_top26_dynamic_follow_fields,
    build_ranking_v2_top26_payload_from_base,
    build_top26_selective_16x4_payload_from_top26,
    build_top26_selective_16x4_dynamic_payload_from_top26,
    build_realtime_pattern_weights,
    build_pattern_outcome_documents,
    build_pattern_resolution_documents,
)


logger = logging.getLogger(__name__)


class SuggestionMonitorWorker:
    def __init__(self) -> None:
        self.roulette_id = settings.suggestion_monitor_roulette_id
        self.max_numbers = max(1, min(37, int(settings.suggestion_monitor_max_numbers)))
        self.history_window_size = max(10, int(settings.suggestion_monitor_history_window))
        self.dynamic_weights_enabled = bool(settings.suggestion_monitor_dynamic_weights_enabled)
        self.dynamic_weights_lookback = max(12, int(settings.suggestion_monitor_dynamic_weights_lookback))
        self.dynamic_weight_floor = float(settings.suggestion_monitor_dynamic_weight_floor)
        self.dynamic_weight_ceil = float(settings.suggestion_monitor_dynamic_weight_ceil)
        self.dynamic_weight_smoothing = float(settings.suggestion_monitor_dynamic_weight_smoothing)
        self.dynamic_weight_sample_target = float(settings.suggestion_monitor_dynamic_weight_sample_target)
        self.dynamic_top_rank_bonus = float(settings.suggestion_monitor_dynamic_top_rank_bonus)
        self.time_window_prior_enabled = bool(settings.suggestion_monitor_time_window_prior_enabled)
        self.time_window_prior_lookback_days = max(3, int(settings.suggestion_monitor_time_window_prior_lookback_days))
        self.time_window_prior_minute_span = max(0, int(settings.suggestion_monitor_time_window_prior_minute_span))
        self.time_window_prior_region_span = max(0, int(settings.suggestion_monitor_time_window_prior_region_span))
        self.time_window_prior_current_weight = float(settings.suggestion_monitor_time_window_prior_current_weight)
        self.time_window_prior_exact_weight = float(settings.suggestion_monitor_time_window_prior_exact_weight)
        self.time_window_prior_region_weight = float(settings.suggestion_monitor_time_window_prior_region_weight)
        self.ml_meta_rank_enabled = bool(settings.suggestion_monitor_ml_meta_rank_enabled)
        self.ml_meta_rank_learning_rate = float(settings.suggestion_monitor_ml_meta_rank_learning_rate)
        self.ml_meta_rank_positive_class_weight = float(settings.suggestion_monitor_ml_meta_rank_positive_class_weight)
        self.ml_meta_rank_negative_class_weight = float(settings.suggestion_monitor_ml_meta_rank_negative_class_weight)
        self.ml_meta_rank_l2_decay = float(settings.suggestion_monitor_ml_meta_rank_l2_decay)
        self.ml_meta_rank_warmup_events = max(6, int(settings.suggestion_monitor_ml_meta_rank_warmup_events))
        self.ml_entry_gate_enabled = bool(settings.suggestion_monitor_ml_entry_gate_enabled)
        self.ml_entry_gate_learning_rate = float(settings.suggestion_monitor_ml_entry_gate_learning_rate)
        self.ml_entry_gate_positive_class_weight = float(settings.suggestion_monitor_ml_entry_gate_positive_class_weight)
        self.ml_entry_gate_negative_class_weight = float(settings.suggestion_monitor_ml_entry_gate_negative_class_weight)
        self.ml_entry_gate_l2_decay = float(settings.suggestion_monitor_ml_entry_gate_l2_decay)
        self.ml_entry_gate_warmup_events = max(8, int(settings.suggestion_monitor_ml_entry_gate_warmup_events))
        self.ml_entry_gate_threshold = float(settings.suggestion_monitor_ml_entry_gate_threshold)
        self.dynamic_pattern_weights: Dict[str, float] = {}
        self.fast_forward_on_backlog = bool(settings.suggestion_monitor_fast_forward_on_backlog)
        self.max_backlog_results = max(50, int(settings.suggestion_monitor_max_backlog_results))
        self.shadow_compare_enabled = bool(settings.suggestion_monitor_shadow_compare_enabled)
        self.shadow_compare_max_numbers = max(
            self.max_numbers,
            min(37, int(settings.suggestion_monitor_shadow_compare_max_numbers)),
        )
        self.poll_interval_seconds = max(1.0, float(settings.suggestion_monitor_poll_interval_seconds))
        self.api_timeout_seconds = max(3.0, float(settings.suggestion_monitor_api_timeout_seconds))
        self.base_url = settings.api_base_url.rstrip("/")
        self.simple_path = settings.suggestion_monitor_simple_path.strip()
        self.repo = SuggestionMonitorRepository()
        self.config_key = build_config_key(
            roulette_id=self.roulette_id,
            suggestion_type="simple_http",
            max_numbers=self.max_numbers,
            history_window_size=self.history_window_size,
        )
        self.base_config_key = f"{self.config_key}|variant=base_v1"
        self.time_window_prior_config_key = f"{self.config_key}|variant=time_window_prior_v1"
        self.ranking_v2_top26_config_key = f"{self.config_key}|variant=ranking_v2_top26"
        self.ml_meta_rank_config_key = f"{self.config_key}|variant=ml_meta_rank_v1"
        self.ml_top12_reference_config_key = f"{self.config_key}|variant=ml_top12_reference_12x4_v1"
        self.ml_entry_gate_config_key = f"{self.config_key}|variant=ml_entry_gate_12x4_v1"
        self.top26_selective_config_key = f"{self.config_key}|variant=top26_selective_16x4_v1"
        self.top26_selective_dynamic_config_key = f"{self.config_key}|variant=top26_selective_16x4_dynamic_v1"
        self.pending_events: Dict[str, Dict[str, Any]] = {}
        self.offset_doc: Dict[str, Any] | None = None
        self.last_resolved_base_event: Dict[str, Any] | None = None
        self.recent_resolved_base_events: List[Dict[str, Any]] = []
        self.last_resolved_top26_event: Dict[str, Any] | None = None
        self.last_generated_top26_event: Dict[str, Any] | None = None
        self.recent_resolved_top26_events: List[Dict[str, Any]] = []
        self.recent_resolved_ml_events: List[Dict[str, Any]] = []
        self.ml_meta_rank_state: Dict[str, Any] = build_default_ml_meta_rank_state(
            roulette_id=self.roulette_id,
            config_key=self.ml_meta_rank_config_key,
            learning_rate=self.ml_meta_rank_learning_rate,
            positive_class_weight=self.ml_meta_rank_positive_class_weight,
            negative_class_weight=self.ml_meta_rank_negative_class_weight,
            l2_decay=self.ml_meta_rank_l2_decay,
            warmup_events=self.ml_meta_rank_warmup_events,
        )
        self.ml_entry_gate_state: Dict[str, Any] = build_default_ml_entry_gate_state(
            roulette_id=self.roulette_id,
            config_key=self.ml_entry_gate_config_key,
            learning_rate=self.ml_entry_gate_learning_rate,
            positive_class_weight=self.ml_entry_gate_positive_class_weight,
            negative_class_weight=self.ml_entry_gate_negative_class_weight,
            l2_decay=self.ml_entry_gate_l2_decay,
            warmup_events=self.ml_entry_gate_warmup_events,
            threshold=self.ml_entry_gate_threshold,
        )
        self.resolved_base_history_limit = max(8, self.dynamic_weights_lookback)
        self.resolved_top26_history_limit = max(8, self.dynamic_weights_lookback)
        self.resolved_ml_history_limit = max(8, self.dynamic_weights_lookback)
        self.results_redis = None
        self._startup_reconcile_done = False

    def _sync_ml_entry_gate_runtime_config(self) -> bool:
        changed = False
        desired_warmup_events = int(self.ml_entry_gate_warmup_events)
        desired_threshold = round(float(self.ml_entry_gate_threshold), 6)
        current_warmup_events = int(self.ml_entry_gate_state.get("warmup_events") or 0)
        current_threshold = round(float(self.ml_entry_gate_state.get("threshold") or 0.0), 6)
        if current_warmup_events != desired_warmup_events:
            self.ml_entry_gate_state["warmup_events"] = desired_warmup_events
            changed = True
        if current_threshold != desired_threshold:
            self.ml_entry_gate_state["threshold"] = desired_threshold
            changed = True
        return changed

    async def run(self) -> None:
        if not settings.suggestion_monitor_enabled:
            logger.warning("Suggestion monitor desabilitado por configuracao.")
            return

        logger.info(
            "Iniciando suggestion monitor | roulette=%s | channel=%s | api=%s | history_window=%s | max_numbers=%s | poll_interval=%.1fs",
            self.roulette_id,
            settings.result_channel,
            self.base_url,
            self.history_window_size,
            self.max_numbers,
            self.poll_interval_seconds,
        )
        logger.info(
            "Suggestion monitor | fast_forward_on_backlog=%s | max_backlog_results=%s",
            self.fast_forward_on_backlog,
            self.max_backlog_results,
        )
        logger.info("Suggestion monitor | endpoint simple=%s", self.simple_path)
        logger.info("Suggestion monitor | control_channel=%s", settings.suggestion_monitor_control_channel)
        logger.info(
            "Suggestion monitor | payload_config base_weight=%.3f optimized_weight=%.3f optimized_max_numbers=%s block_bets=%s inversion=%s protected_mode=%s weight_profile=%s runtime_overrides=%s",
            settings.suggestion_monitor_base_weight,
            settings.suggestion_monitor_optimized_weight,
            settings.suggestion_monitor_optimized_max_numbers,
            settings.suggestion_monitor_block_bets_enabled,
            settings.suggestion_monitor_inversion_enabled,
            settings.suggestion_monitor_protected_mode_enabled,
            settings.suggestion_monitor_weight_profile_id or "-",
            settings.suggestion_monitor_runtime_overrides,
        )
        logger.info(
            "Suggestion monitor | realtime_weights enabled=%s lookback=%s floor=%.2f ceil=%.2f smoothing=%.2f sample_target=%.1f top_rank_bonus=%.2f",
            self.dynamic_weights_enabled,
            self.dynamic_weights_lookback,
            self.dynamic_weight_floor,
            self.dynamic_weight_ceil,
            self.dynamic_weight_smoothing,
            self.dynamic_weight_sample_target,
            self.dynamic_top_rank_bonus,
        )
        logger.info(
            "Suggestion monitor | variants base=%s time_window=%s top26=%s ml=%s top26_selective=%s",
            self.base_config_key,
            self.time_window_prior_config_key,
            self.ranking_v2_top26_config_key,
            self.ml_meta_rank_config_key,
            self.top26_selective_config_key,
        )
        logger.info(
            "Suggestion monitor | variants ml_ref=%s ml_gate=%s top26_selective_dynamic=%s",
            self.ml_top12_reference_config_key,
            self.ml_entry_gate_config_key,
            self.top26_selective_dynamic_config_key,
        )
        await asyncio.to_thread(self.repo.ensure_indexes)
        logger.info("Suggestion monitor | indices Mongo garantidos.")
        await self._bootstrap_state()

        self.results_redis = aioredis.from_url(settings.results_redis_url, decode_responses=True)
        pubsub = self.results_redis.pubsub()
        await pubsub.subscribe(settings.result_channel, settings.suggestion_monitor_control_channel)
        logger.info(
            "Suggestion monitor ativo para %s via %s",
            self.roulette_id,
            settings.result_channel,
        )
        last_reconcile_monotonic = 0.0

        try:
            await self._reconcile_new_history(reason="startup", log_empty=True)
            last_reconcile_monotonic = time.monotonic()
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if self._is_control_message(message):
                    await self._handle_control_message(message)
                    last_reconcile_monotonic = time.monotonic()
                    continue
                if self._message_matches_target(message):
                    logger.info("Suggestion monitor | trigger Redis recebido para %s.", self.roulette_id)
                    await self._reconcile_new_history(reason="redis")
                    last_reconcile_monotonic = time.monotonic()
                    continue
                now = time.monotonic()
                if now - last_reconcile_monotonic >= self.poll_interval_seconds:
                    await self._reconcile_new_history(reason="poll")
                    last_reconcile_monotonic = now
        finally:
            await pubsub.unsubscribe(settings.result_channel, settings.suggestion_monitor_control_channel)
            await pubsub.close()
            await self.results_redis.close()

    @staticmethod
    def _parse_message_payload(message: Any) -> Dict[str, Any] | None:
        if not isinstance(message, Mapping):
            return None
        raw_data = message.get("data")
        if raw_data is None:
            return None
        try:
            payload = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, Mapping):
            return None
        return dict(payload)

    def _message_matches_target(self, message: Any) -> bool:
        payload = self._parse_message_payload(message)
        if not payload:
            return False
        slug = str(payload.get("slug") or payload.get("roulette_id") or "").strip()
        return slug == self.roulette_id

    def _history_doc_matches_target(self, history_doc: Mapping[str, Any]) -> bool:
        if not isinstance(history_doc, Mapping):
            return False
        candidate = str(
            history_doc.get("roulette_id")
            or history_doc.get("slug")
            or history_doc.get("roulette_name")
            or ""
        ).strip()
        return candidate == self.roulette_id

    def _is_control_message(self, message: Any) -> bool:
        if not isinstance(message, Mapping):
            return False
        channel = str(message.get("channel") or "").strip()
        return channel == settings.suggestion_monitor_control_channel

    async def _handle_control_message(self, message: Any) -> None:
        payload = self._parse_message_payload(message)
        if not payload:
            return
        action = str(payload.get("action") or "").strip().lower()
        roulette_id = str(payload.get("roulette_id") or "").strip()
        config_key = str(payload.get("config_key") or "").strip()
        if action != "reset_monitor":
            return
        if roulette_id and roulette_id != self.roulette_id:
            return
        if config_key and config_key not in {
            self.config_key,
            self.base_config_key,
            self.time_window_prior_config_key,
            self.ranking_v2_top26_config_key,
            self.ml_meta_rank_config_key,
            self.ml_top12_reference_config_key,
            self.ml_entry_gate_config_key,
            self.top26_selective_config_key,
            self.top26_selective_dynamic_config_key,
        }:
            return

        logger.warning(
            "Suggestion monitor reset recebido | roulette=%s | config_key=%s",
            self.roulette_id,
            self.config_key,
        )
        self.pending_events = {}
        self.last_resolved_base_event = None
        self.recent_resolved_base_events = []
        self.last_resolved_top26_event = None
        self.last_generated_top26_event = None
        self.recent_resolved_top26_events = []
        self.recent_resolved_ml_events = []
        self.dynamic_pattern_weights = {}
        self.ml_meta_rank_state = build_default_ml_meta_rank_state(
            roulette_id=self.roulette_id,
            config_key=self.ml_meta_rank_config_key,
            learning_rate=self.ml_meta_rank_learning_rate,
            positive_class_weight=self.ml_meta_rank_positive_class_weight,
            negative_class_weight=self.ml_meta_rank_negative_class_weight,
            l2_decay=self.ml_meta_rank_l2_decay,
            warmup_events=self.ml_meta_rank_warmup_events,
        )
        self.ml_entry_gate_state = build_default_ml_entry_gate_state(
            roulette_id=self.roulette_id,
            config_key=self.ml_entry_gate_config_key,
            learning_rate=self.ml_entry_gate_learning_rate,
            positive_class_weight=self.ml_entry_gate_positive_class_weight,
            negative_class_weight=self.ml_entry_gate_negative_class_weight,
            l2_decay=self.ml_entry_gate_l2_decay,
            warmup_events=self.ml_entry_gate_warmup_events,
            threshold=self.ml_entry_gate_threshold,
        )
        await asyncio.to_thread(self.repo.save_model_state, self.ml_meta_rank_state)
        await asyncio.to_thread(self.repo.save_model_state, self.ml_entry_gate_state)
        latest_history_doc = await asyncio.to_thread(self.repo.get_latest_history_doc, self.roulette_id)
        if latest_history_doc is None:
            self.offset_doc = None
            logger.warning("Suggestion monitor reset | nenhum historico encontrado para bootstrap.")
            return
        self.offset_doc = await asyncio.to_thread(
            self.repo.save_offset,
            config_key=self.config_key,
            roulette_id=self.roulette_id,
            history_doc=latest_history_doc,
        )
        logger.info(
            "Suggestion monitor reset aplicado | novo_offset_numero=%s | timestamp=%s",
            latest_history_doc["value"],
            latest_history_doc["history_timestamp_br"],
        )

    async def _bootstrap_state(self) -> None:
        base_pending = await asyncio.to_thread(
            self.repo.load_pending_events,
            roulette_id=self.roulette_id,
            config_key=self.base_config_key,
        )
        time_window_prior_pending = await asyncio.to_thread(
            self.repo.load_pending_events,
            roulette_id=self.roulette_id,
            config_key=self.time_window_prior_config_key,
        )
        ranking_v2_top26_pending = await asyncio.to_thread(
            self.repo.load_pending_events,
            roulette_id=self.roulette_id,
            config_key=self.ranking_v2_top26_config_key,
        )
        ml_meta_rank_pending = await asyncio.to_thread(
            self.repo.load_pending_events,
            roulette_id=self.roulette_id,
            config_key=self.ml_meta_rank_config_key,
        )
        ml_top12_reference_pending = await asyncio.to_thread(
            self.repo.load_pending_events,
            roulette_id=self.roulette_id,
            config_key=self.ml_top12_reference_config_key,
        )
        ml_entry_gate_pending = await asyncio.to_thread(
            self.repo.load_pending_events,
            roulette_id=self.roulette_id,
            config_key=self.ml_entry_gate_config_key,
        )
        top26_selective_pending = await asyncio.to_thread(
            self.repo.load_pending_events,
            roulette_id=self.roulette_id,
            config_key=self.top26_selective_config_key,
        )
        top26_selective_dynamic_pending = await asyncio.to_thread(
            self.repo.load_pending_events,
            roulette_id=self.roulette_id,
            config_key=self.top26_selective_dynamic_config_key,
        )
        pending = [
            *base_pending,
            *time_window_prior_pending,
            *ranking_v2_top26_pending,
            *ml_meta_rank_pending,
            *ml_top12_reference_pending,
            *ml_entry_gate_pending,
            *top26_selective_pending,
            *top26_selective_dynamic_pending,
        ]
        self.pending_events = {str(event["_id"]): dict(event) for event in pending}
        self.offset_doc = await asyncio.to_thread(self.repo.get_offset, config_key=self.config_key)
        self.last_resolved_base_event = await asyncio.to_thread(
            self.repo.get_latest_resolved_event,
            roulette_id=self.roulette_id,
            config_key=self.base_config_key,
        )
        self.recent_resolved_base_events = await asyncio.to_thread(
            self.repo.get_recent_resolved_events,
            roulette_id=self.roulette_id,
            config_key=self.base_config_key,
            limit=self.resolved_base_history_limit,
        )
        self.last_resolved_top26_event = await asyncio.to_thread(
            self.repo.get_latest_resolved_event,
            roulette_id=self.roulette_id,
            config_key=self.ranking_v2_top26_config_key,
        )
        self.last_generated_top26_event = await asyncio.to_thread(
            self.repo.get_latest_event,
            roulette_id=self.roulette_id,
            config_key=self.ranking_v2_top26_config_key,
        )
        self.recent_resolved_top26_events = await asyncio.to_thread(
            self.repo.get_recent_resolved_events,
            roulette_id=self.roulette_id,
            config_key=self.ranking_v2_top26_config_key,
            limit=self.resolved_top26_history_limit,
        )
        self.recent_resolved_ml_events = await asyncio.to_thread(
            self.repo.get_recent_resolved_events,
            roulette_id=self.roulette_id,
            config_key=self.ml_meta_rank_config_key,
            limit=self.resolved_ml_history_limit,
        )
        self.ml_meta_rank_state = await asyncio.to_thread(
            self.repo.get_model_state,
            roulette_id=self.roulette_id,
            config_key=self.ml_meta_rank_config_key,
            model_name="ml_meta_rank_v1",
        ) or build_default_ml_meta_rank_state(
            roulette_id=self.roulette_id,
            config_key=self.ml_meta_rank_config_key,
            learning_rate=self.ml_meta_rank_learning_rate,
            positive_class_weight=self.ml_meta_rank_positive_class_weight,
            negative_class_weight=self.ml_meta_rank_negative_class_weight,
            l2_decay=self.ml_meta_rank_l2_decay,
            warmup_events=self.ml_meta_rank_warmup_events,
        )
        self.ml_entry_gate_state = await asyncio.to_thread(
            self.repo.get_model_state,
            roulette_id=self.roulette_id,
            config_key=self.ml_entry_gate_config_key,
            model_name="ml_entry_gate_v1",
        ) or build_default_ml_entry_gate_state(
            roulette_id=self.roulette_id,
            config_key=self.ml_entry_gate_config_key,
            learning_rate=self.ml_entry_gate_learning_rate,
            positive_class_weight=self.ml_entry_gate_positive_class_weight,
            negative_class_weight=self.ml_entry_gate_negative_class_weight,
            l2_decay=self.ml_entry_gate_l2_decay,
            warmup_events=self.ml_entry_gate_warmup_events,
            threshold=self.ml_entry_gate_threshold,
        )
        if self._sync_ml_entry_gate_runtime_config():
            await asyncio.to_thread(self.repo.save_model_state, self.ml_entry_gate_state)
        if self.ml_entry_gate_enabled and int(self.ml_entry_gate_state.get("trained_events") or 0) <= 0:
            bootstrap_ml_events = await asyncio.to_thread(
                self.repo.get_recent_resolved_events,
                roulette_id=self.roulette_id,
                config_key=self.ml_meta_rank_config_key,
                limit=240,
            )
            for event_doc in reversed(list(bootstrap_ml_events or [])):
                future_results = await asyncio.to_thread(
                    self.repo.get_new_history_docs,
                    roulette_id=self.roulette_id,
                    last_history_timestamp_utc=event_doc["anchor_timestamp_utc"],
                    last_history_id=event_doc["anchor_history_id"],
                    limit=4,
                )
                self.ml_entry_gate_state = train_ml_entry_gate_state_from_ml_meta_event(
                    self.ml_entry_gate_state,
                    event_doc,
                    future_results,
                    roulette_id=self.roulette_id,
                    config_key=self.ml_entry_gate_config_key,
                    suggestion_size=12,
                    evaluation_window_attempts=4,
                )
            await asyncio.to_thread(self.repo.save_model_state, self.ml_entry_gate_state)
        self.dynamic_pattern_weights = self._compute_runtime_pattern_weights()
        if self.offset_doc is not None:
            await self._maybe_fast_forward_stale_offset(context="resume")
            logger.info(
                "Suggestion monitor retomado | pendencias=%d | ultimo_history_id=%s | ultimo_numero=%s | ultimo_timestamp=%s",
                len(self.pending_events),
                self.offset_doc.get("last_history_id"),
                self.offset_doc.get("last_history_number"),
                self.offset_doc.get("last_history_timestamp_utc"),
            )
            return

        latest_history_doc = await asyncio.to_thread(self.repo.get_latest_history_doc, self.roulette_id)
        if latest_history_doc is None:
            logger.warning("Nenhum historico encontrado para %s.", self.roulette_id)
            return

        self.offset_doc = await asyncio.to_thread(
            self.repo.save_offset,
            config_key=self.config_key,
            roulette_id=self.roulette_id,
            history_doc=latest_history_doc,
        )
        logger.info(
            "Suggestion monitor bootstrap | ultimo resultado existente=%s | timestamp=%s | monitor vai observar a partir do proximo giro",
            latest_history_doc["value"],
            latest_history_doc["history_timestamp_br"],
        )

    def _all_config_keys(self) -> List[str]:
        return [
            self.base_config_key,
            self.time_window_prior_config_key,
            self.ranking_v2_top26_config_key,
            self.top26_selective_config_key,
            self.top26_selective_dynamic_config_key,
        ]

    async def _maybe_fast_forward_stale_offset(self, *, context: str) -> bool:
        if not self.fast_forward_on_backlog or self.offset_doc is None:
            return False

        backlog_count = await asyncio.to_thread(
            self.repo.count_new_history_docs,
            roulette_id=self.roulette_id,
            last_history_timestamp_utc=self.offset_doc["last_history_timestamp_utc"],
            last_history_id=self.offset_doc["last_history_id"],
        )
        if backlog_count <= self.max_backlog_results:
            return False

        latest_history_doc = await asyncio.to_thread(self.repo.get_latest_history_doc, self.roulette_id)
        if latest_history_doc is None:
            return False

        marked_unavailable = await asyncio.to_thread(
            self.repo.mark_pending_events_unavailable,
            roulette_id=self.roulette_id,
            config_keys=self._all_config_keys(),
            reason=(
                f"Monitor fast-forwarded after backlog of {backlog_count} results; "
                "pending suggestions were closed to resume realtime tracking."
            ),
        )
        self.pending_events = {}
        self.dynamic_pattern_weights = {}
        self.last_generated_top26_event = None
        self.offset_doc = await asyncio.to_thread(
            self.repo.save_offset,
            config_key=self.config_key,
            roulette_id=self.roulette_id,
            history_doc=latest_history_doc,
        )
        logger.warning(
            "Suggestion monitor %s | backlog=%d excede limite=%d. Fast-forward para latest result=%s timestamp=%s | pendencias_encerradas=%d",
            context,
            backlog_count,
            self.max_backlog_results,
            latest_history_doc["value"],
            latest_history_doc["history_timestamp_br"],
            marked_unavailable,
        )
        return True

    async def _reconcile_new_history(self, *, reason: str, log_empty: bool = False) -> None:
        if self.offset_doc is None:
            await self._bootstrap_state()
            if self.offset_doc is None:
                return
        elif reason in {"startup", "poll"}:
            await self._maybe_fast_forward_stale_offset(context=reason)

        new_docs = await asyncio.to_thread(
            self.repo.get_new_history_docs,
            roulette_id=self.roulette_id,
            last_history_timestamp_utc=self.offset_doc["last_history_timestamp_utc"],
            last_history_id=self.offset_doc["last_history_id"],
        )
        filtered_docs = [doc for doc in new_docs if self._history_doc_matches_target(doc)]
        dropped_docs = len(new_docs) - len(filtered_docs)
        if dropped_docs > 0:
            logger.warning(
                "Suggestion monitor %s | %d resultado(s) descartado(s) por roulette_id divergente. target=%s",
                reason,
                dropped_docs,
                self.roulette_id,
            )
        new_docs = filtered_docs
        if not new_docs and log_empty:
            logger.info(
                "Suggestion monitor %s | nenhum novo resultado apos offset atual | pendencias=%d",
                reason,
                len(self.pending_events),
            )
        for history_doc in new_docs:
            await self._process_history_doc(history_doc)
        if new_docs:
            logger.info(
                "Suggestion monitor %s | resultados_processados=%d | pendencias_ativas=%d | ultimo_numero=%s",
                reason,
                len(new_docs),
                len(self.pending_events),
                new_docs[-1]["value"],
            )
        self._startup_reconcile_done = True

    async def _process_history_doc(self, history_doc: Mapping[str, Any]) -> None:
        started_at = time.perf_counter()
        if not self._history_doc_matches_target(history_doc):
            logger.warning(
                "Suggestion monitor | resultado ignorado por roulette_id divergente. target=%s recebido=%s history_id=%s",
                self.roulette_id,
                history_doc.get("roulette_id") or history_doc.get("slug") or history_doc.get("roulette_name"),
                history_doc.get("history_id"),
            )
            return
        pending_before = len(self.pending_events)
        await self._resolve_pending_with_result(history_doc)
        resolved_now = max(0, pending_before - len(self.pending_events))

        history_started_at = time.perf_counter()
        history_docs = await asyncio.to_thread(
            self.repo.get_history_window_up_to,
            roulette_id=self.roulette_id,
            anchor_history_timestamp_utc=history_doc["history_timestamp_utc"],
            anchor_history_id=history_doc["history_id"],
            limit=self.history_window_size,
        )
        history_elapsed_ms = (time.perf_counter() - history_started_at) * 1000.0
        history_values = [int(item["value"]) for item in history_docs]
        fetch_started_at = time.perf_counter()
        simple_payload, status_override, error_message = await self._fetch_simple_suggestion(
            history_values=history_values,
            focus_number=int(history_doc["value"]),
        )
        fetch_elapsed_ms = (time.perf_counter() - fetch_started_at) * 1000.0
        total_elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        if status_override == "generation_error":
            logger.warning(
                "Suggestion monitor stage timings | history_id=%s | numero=%s | history_ms=%.2f | fetch_ms=%.2f | total_ms=%.2f | history_len=%d | api=%s | detalhe=%s",
                history_doc.get("history_id"),
                history_doc.get("value"),
                history_elapsed_ms,
                fetch_elapsed_ms,
                total_elapsed_ms,
                len(history_values),
                self.base_url,
                error_message or "-",
            )
        elif total_elapsed_ms >= 3000.0:
            logger.info(
                "Suggestion monitor stage timings | history_id=%s | numero=%s | history_ms=%.2f | fetch_ms=%.2f | total_ms=%.2f | history_len=%d",
                history_doc.get("history_id"),
                history_doc.get("value"),
                history_elapsed_ms,
                fetch_elapsed_ms,
                total_elapsed_ms,
                len(history_values),
            )
        if status_override is None and isinstance(simple_payload, Mapping):
            simple_payload = apply_rank_confidence_feedback(
                simple_payload,
                self.recent_resolved_base_events,
            )
        base_event_doc = build_monitor_event_document(
            anchor_doc=history_doc,
            simple_payload=simple_payload,
            history_values=history_values,
            config_key=self.base_config_key,
            ranking_variant="base_v1",
            suggestion_type="simple_http",
            status_override=status_override,
            error_message=error_message,
        )
        time_window_prior_docs_by_day = (
            await asyncio.to_thread(
                self.repo.get_history_docs_by_time_window_days,
                roulette_id=self.roulette_id,
                reference_timestamp_utc=history_doc["history_timestamp_utc"],
                lookback_days=self.time_window_prior_lookback_days,
                minute_span=self.time_window_prior_minute_span,
            )
            if self.time_window_prior_enabled and status_override is None and isinstance(simple_payload, Mapping)
            else {}
        )
        time_window_prior_payload = (
            build_time_window_prior_payload_from_base(
                base_payload=simple_payload,
                docs_by_day=time_window_prior_docs_by_day,
                lookback_days=self.time_window_prior_lookback_days,
                minute_span=self.time_window_prior_minute_span,
                region_span=self.time_window_prior_region_span,
                current_weight=self.time_window_prior_current_weight,
                exact_weight=self.time_window_prior_exact_weight,
                region_weight=self.time_window_prior_region_weight,
            )
            if self.time_window_prior_enabled and status_override is None and isinstance(simple_payload, Mapping)
            else None
        )
        if status_override is None and isinstance(time_window_prior_payload, Mapping):
            time_window_prior_payload = apply_rank_confidence_feedback(
                time_window_prior_payload,
                self.recent_resolved_base_events,
            )
        ranking_v2_top26_payload = (
            build_ranking_v2_top26_payload_from_base(
                base_payload=simple_payload,
                recent_resolved_base_events=self.recent_resolved_base_events,
                history_values=history_values,
            )
            if status_override is None and isinstance(simple_payload, Mapping)
            else None
        )
        if status_override is None and isinstance(ranking_v2_top26_payload, Mapping):
            ranking_v2_top26_payload = apply_rank_confidence_feedback(
                ranking_v2_top26_payload,
                self.recent_resolved_top26_events,
            )
        ml_meta_rank_payload = (
            build_ml_meta_rank_payload_from_context(
                base_payload=simple_payload,
                top26_payload=ranking_v2_top26_payload,
                time_window_prior_payload=time_window_prior_payload,
                history_values=history_values,
                model_state=self.ml_meta_rank_state,
                roulette_id=self.roulette_id,
                config_key=self.ml_meta_rank_config_key,
            )
            if self.ml_meta_rank_enabled and status_override is None and isinstance(simple_payload, Mapping)
            else None
        )
        if status_override is None and isinstance(ml_meta_rank_payload, Mapping):
            ml_meta_rank_payload = apply_rank_confidence_feedback(
                ml_meta_rank_payload,
                self.recent_resolved_ml_events,
            )
        ml_top12_reference_payload = (
            build_ml_top12_reference_payload_from_ml_meta(
                ml_meta_rank_payload,
                suggestion_size=12,
                evaluation_window_attempts=4,
            )
            if self.ml_entry_gate_enabled and status_override is None and isinstance(ml_meta_rank_payload, Mapping)
            else None
        )
        ml_entry_gate_payload = (
            build_ml_entry_gate_payload_from_ml_meta(
                ml_meta_rank_payload,
                self.ml_entry_gate_state,
                roulette_id=self.roulette_id,
                config_key=self.ml_entry_gate_config_key,
                suggestion_size=12,
                evaluation_window_attempts=4,
            )
            if self.ml_entry_gate_enabled and status_override is None and isinstance(ml_meta_rank_payload, Mapping)
            else None
        )
        top26_selective_payload = (
            build_top26_selective_16x4_payload_from_top26(
                top26_payload=ranking_v2_top26_payload,
                recent_resolved_top26_events=self.recent_resolved_top26_events,
                compact_size=14,
                evaluation_window_attempts=4,
            )
            if status_override is None and isinstance(ranking_v2_top26_payload, Mapping)
            else None
        )
        top26_selective_dynamic_payload = (
            build_top26_selective_16x4_dynamic_payload_from_top26(
                top26_payload=ranking_v2_top26_payload,
                recent_resolved_top26_events=self.recent_resolved_top26_events,
                compact_size=14,
                evaluation_window_attempts=4,
            )
            if status_override is None and isinstance(ranking_v2_top26_payload, Mapping)
            else None
        )
        time_window_prior_status_override = status_override
        time_window_prior_error_message = error_message
        if self.time_window_prior_enabled and time_window_prior_payload is None and time_window_prior_status_override is None:
            time_window_prior_status_override = "unavailable"
            time_window_prior_error_message = "Prior temporal por janela horária indisponível: sem histórico suficiente."
        ranking_v2_top26_status_override = status_override
        ranking_v2_top26_error_message = error_message
        if ranking_v2_top26_payload is None and ranking_v2_top26_status_override is None:
            ranking_v2_top26_status_override = "unavailable"
            ranking_v2_top26_error_message = "Ranking v2 top26 indisponivel: ranking base sem dados suficientes."
        ml_meta_rank_status_override = status_override
        ml_meta_rank_error_message = error_message
        if self.ml_meta_rank_enabled and ml_meta_rank_payload is None and ml_meta_rank_status_override is None:
            ml_meta_rank_status_override = "unavailable"
            ml_meta_rank_error_message = "ML meta-ranker indisponível: sem dados suficientes para montar features."
        ml_top12_reference_status_override = status_override
        ml_top12_reference_error_message = error_message
        if self.ml_entry_gate_enabled and ml_top12_reference_payload is None and ml_top12_reference_status_override is None:
            ml_top12_reference_status_override = "unavailable"
            ml_top12_reference_error_message = "Referência ML top12 12x4 indisponível: meta-ranker sem dados suficientes."
        ml_entry_gate_status_override = status_override
        ml_entry_gate_error_message = error_message
        if self.ml_entry_gate_enabled and ml_entry_gate_payload is None and ml_entry_gate_status_override is None:
            ml_entry_gate_status_override = "unavailable"
            ml_entry_gate_error_message = "Gate ML 12x4 indisponível: sem dados suficientes para previsão de entrada."
        top26_selective_status_override = status_override
        top26_selective_error_message = error_message
        if top26_selective_payload is None and top26_selective_status_override is None:
            top26_selective_status_override = "unavailable"
            top26_selective_error_message = "Top26 selective 16x4 indisponivel: descida não confirmada."
        top26_selective_dynamic_status_override = status_override
        top26_selective_dynamic_error_message = error_message
        if top26_selective_dynamic_payload is None and top26_selective_dynamic_status_override is None:
            top26_selective_dynamic_status_override = "unavailable"
            top26_selective_dynamic_error_message = "Top26 selective dinâmico 16x4 indisponivel: descida não confirmada."
        time_window_prior_event_doc = build_monitor_event_document(
            anchor_doc=history_doc,
            simple_payload=time_window_prior_payload,
            history_values=history_values,
            config_key=self.time_window_prior_config_key,
            ranking_variant="time_window_prior_v1",
            source_base_event_id=str(base_event_doc["_id"]),
            source_base_config_key=self.base_config_key,
            ranking_source_variant="base_v1",
            suggestion_type="simple_http",
            status_override=time_window_prior_status_override,
            error_message=time_window_prior_error_message,
        )
        ranking_v2_top26_event_doc = build_monitor_event_document(
            anchor_doc=history_doc,
            simple_payload=ranking_v2_top26_payload,
            history_values=history_values,
            config_key=self.ranking_v2_top26_config_key,
            ranking_variant="ranking_v2_top26",
            source_base_event_id=str(base_event_doc["_id"]),
            source_base_config_key=self.base_config_key,
            ranking_source_variant="base_v1",
            suggestion_type="simple_http",
            status_override=ranking_v2_top26_status_override,
            error_message=ranking_v2_top26_error_message,
        )
        ml_meta_rank_event_doc = build_monitor_event_document(
            anchor_doc=history_doc,
            simple_payload=ml_meta_rank_payload,
            history_values=history_values,
            config_key=self.ml_meta_rank_config_key,
            ranking_variant="ml_meta_rank_v1",
            source_base_event_id=str(base_event_doc["_id"]),
            source_base_config_key=self.base_config_key,
            ranking_source_variant="base_v1",
            suggestion_type="simple_http",
            status_override=ml_meta_rank_status_override,
            error_message=ml_meta_rank_error_message,
        )
        ml_top12_reference_event_doc = build_monitor_event_document(
            anchor_doc=history_doc,
            simple_payload=ml_top12_reference_payload,
            history_values=history_values,
            config_key=self.ml_top12_reference_config_key,
            ranking_variant="ml_top12_reference_12x4_v1",
            source_base_event_id=str(ml_meta_rank_event_doc["_id"]),
            source_base_config_key=self.ml_meta_rank_config_key,
            ranking_source_variant="ml_meta_rank_v1",
            suggestion_type="simple_http",
            status_override=ml_top12_reference_status_override,
            error_message=ml_top12_reference_error_message,
        )
        ml_entry_gate_event_doc = build_monitor_event_document(
            anchor_doc=history_doc,
            simple_payload=ml_entry_gate_payload,
            history_values=history_values,
            config_key=self.ml_entry_gate_config_key,
            ranking_variant="ml_entry_gate_12x4_v1",
            source_base_event_id=str(ml_meta_rank_event_doc["_id"]),
            source_base_config_key=self.ml_meta_rank_config_key,
            ranking_source_variant="ml_meta_rank_v1",
            suggestion_type="simple_http",
            status_override=ml_entry_gate_status_override,
            error_message=ml_entry_gate_error_message,
        )
        top26_selective_event_doc = build_monitor_event_document(
            anchor_doc=history_doc,
            simple_payload=top26_selective_payload,
            history_values=history_values,
            config_key=self.top26_selective_config_key,
            ranking_variant="top26_selective_16x4_v1",
            source_base_event_id=str(ranking_v2_top26_event_doc["_id"]),
            source_base_config_key=self.ranking_v2_top26_config_key,
            ranking_source_variant="ranking_v2_top26",
            suggestion_type="simple_http",
            status_override=top26_selective_status_override,
            error_message=top26_selective_error_message,
        )
        top26_selective_dynamic_event_doc = build_monitor_event_document(
            anchor_doc=history_doc,
            simple_payload=top26_selective_dynamic_payload,
            history_values=history_values,
            config_key=self.top26_selective_dynamic_config_key,
            ranking_variant="top26_selective_16x4_dynamic_v1",
            source_base_event_id=str(ranking_v2_top26_event_doc["_id"]),
            source_base_config_key=self.ranking_v2_top26_config_key,
            ranking_source_variant="ranking_v2_top26",
            suggestion_type="simple_http",
            status_override=top26_selective_dynamic_status_override,
            error_message=top26_selective_dynamic_error_message,
        )

        event_docs = [
            base_event_doc,
            time_window_prior_event_doc,
            ranking_v2_top26_event_doc,
            ml_meta_rank_event_doc,
            ml_top12_reference_event_doc,
            ml_entry_gate_event_doc,
            top26_selective_event_doc,
            top26_selective_dynamic_event_doc,
        ]
        for event_doc in event_docs:
            pattern_docs = build_pattern_outcome_documents(event_doc)
            await asyncio.to_thread(self.repo.upsert_event, event_doc)
            if pattern_docs:
                await asyncio.to_thread(self.repo.upsert_pattern_outcomes, pattern_docs)
            if event_doc.get("status") == "pending":
                self.pending_events[str(event_doc["_id"])] = dict(event_doc)

        self.last_generated_top26_event = dict(ranking_v2_top26_event_doc)

        logger.info(
            "Suggestion monitor evento | numero=%s | timestamp=%s | resolvidas_agora=%d | base_status=%s | time_window_status=%s | top26_status=%s | ml_status=%s | ml_ref_status=%s | ml_gate_status=%s | strategy_fixed_status=%s | strategy_dynamic_status=%s | base_size=%d | time_window_size=%d | top26_size=%d | ml_size=%d | ml_ref_size=%d | ml_gate_size=%d | strategy_fixed_size=%d | strategy_dynamic_size=%d | pendencias=%d | detalhe=%s",
            history_doc["value"],
            history_doc["history_timestamp_br"],
            resolved_now,
            base_event_doc.get("status"),
            time_window_prior_event_doc.get("status"),
            ranking_v2_top26_event_doc.get("status"),
            ml_meta_rank_event_doc.get("status"),
            ml_top12_reference_event_doc.get("status"),
            ml_entry_gate_event_doc.get("status"),
            top26_selective_event_doc.get("status"),
            top26_selective_dynamic_event_doc.get("status"),
            int(base_event_doc.get("suggestion_size") or 0),
            int(time_window_prior_event_doc.get("suggestion_size") or 0),
            int(ranking_v2_top26_event_doc.get("suggestion_size") or 0),
            int(ml_meta_rank_event_doc.get("suggestion_size") or 0),
            int(ml_top12_reference_event_doc.get("suggestion_size") or 0),
            int(ml_entry_gate_event_doc.get("suggestion_size") or 0),
            int(top26_selective_event_doc.get("suggestion_size") or 0),
            int(top26_selective_dynamic_event_doc.get("suggestion_size") or 0),
            len(self.pending_events),
            (
                error_message
                or base_event_doc.get("generation_error")
                or base_event_doc.get("explanation")
                or "-"
            ),
        )

        self.offset_doc = await asyncio.to_thread(
            self.repo.save_offset,
            config_key=self.config_key,
            roulette_id=self.roulette_id,
            history_doc=history_doc,
        )

    async def _resolve_pending_with_result(self, result_doc: Mapping[str, Any]) -> None:
        if not self.pending_events:
            return
        if not self._history_doc_matches_target(result_doc):
            logger.warning(
                "Suggestion monitor | tentativa ignorada por roulette_id divergente. target=%s recebido=%s history_id=%s",
                self.roulette_id,
                result_doc.get("roulette_id") or result_doc.get("slug") or result_doc.get("roulette_name"),
                result_doc.get("history_id"),
            )
            return

        for event_id, event_doc in list(self.pending_events.items()):
            effective_event_doc = dict(event_doc)
            follow_fields: Dict[str, Any] = {}
            if str(event_doc.get("ranking_variant") or "").strip() == "top26_selective_16x4_dynamic_v1":
                follow_fields = build_top26_dynamic_follow_fields(
                    effective_event_doc,
                    self.last_generated_top26_event,
                )
                if follow_fields:
                    effective_event_doc.update(follow_fields)

            attempt_doc = build_attempt_document(effective_event_doc, result_doc)
            resolution_fields = dict(follow_fields)
            resolution_fields.update(build_event_resolution_fields(effective_event_doc, attempt_doc))
            pattern_resolution_docs = build_pattern_resolution_documents(effective_event_doc, attempt_doc)
            updated_event = await asyncio.to_thread(
                self.repo.apply_attempt,
                event_doc=effective_event_doc,
                attempt_doc=attempt_doc,
                resolution_fields=resolution_fields,
                pattern_resolution_docs=pattern_resolution_docs,
            )
            if updated_event.get("status") == "resolved":
                logger.info(
                    "Suggestion monitor hit | anchor=%s | result=%s | attempt=%s | rank=%s | event_id=%s",
                    event_doc.get("anchor_number"),
                    updated_event.get("resolved_number"),
                    updated_event.get("resolved_attempt"),
                    updated_event.get("resolved_rank_position"),
                    event_id,
                )
                if str(updated_event.get("ranking_variant") or "") == "base_v1":
                    self.last_resolved_base_event = dict(updated_event)
                    self.recent_resolved_base_events = [dict(updated_event), *self.recent_resolved_base_events]
                    deduped: Dict[str, Dict[str, Any]] = {}
                    for item in self.recent_resolved_base_events:
                        event_key = str(item.get("_id") or "").strip()
                        if event_key and event_key not in deduped:
                            deduped[event_key] = item
                    self.recent_resolved_base_events = list(deduped.values())[: self.resolved_base_history_limit]
                    self.dynamic_pattern_weights = self._compute_runtime_pattern_weights()
                if str(updated_event.get("ranking_variant") or "") == "ranking_v2_top26":
                    self.last_resolved_top26_event = dict(updated_event)
                    self.recent_resolved_top26_events = [dict(updated_event), *self.recent_resolved_top26_events]
                    deduped_top26: Dict[str, Dict[str, Any]] = {}
                    for item in self.recent_resolved_top26_events:
                        event_key = str(item.get("_id") or "").strip()
                        if event_key and event_key not in deduped_top26:
                            deduped_top26[event_key] = item
                    self.recent_resolved_top26_events = list(deduped_top26.values())[: self.resolved_top26_history_limit]
                if str(updated_event.get("ranking_variant") or "") == "ml_meta_rank_v1":
                    self.ml_meta_rank_state = train_ml_meta_rank_state_from_resolved_event(
                        self.ml_meta_rank_state,
                        updated_event,
                        roulette_id=self.roulette_id,
                        config_key=self.ml_meta_rank_config_key,
                    )
                    await asyncio.to_thread(self.repo.save_model_state, self.ml_meta_rank_state)
                    self.recent_resolved_ml_events = [dict(updated_event), *self.recent_resolved_ml_events]
                    deduped_ml: Dict[str, Dict[str, Any]] = {}
                    for item in self.recent_resolved_ml_events:
                        event_key = str(item.get("_id") or "").strip()
                        if event_key and event_key not in deduped_ml:
                            deduped_ml[event_key] = item
                    self.recent_resolved_ml_events = list(deduped_ml.values())[: self.resolved_ml_history_limit]
                self.pending_events.pop(event_id, None)
            elif bool(updated_event.get("window_result_finalized")):
                if str(updated_event.get("ranking_variant") or "").strip() == "ml_top12_reference_12x4_v1":
                    self.ml_entry_gate_state = train_ml_entry_gate_state_from_reference_event(
                        self.ml_entry_gate_state,
                        updated_event,
                        roulette_id=self.roulette_id,
                        config_key=self.ml_entry_gate_config_key,
                    )
                    await asyncio.to_thread(self.repo.save_model_state, self.ml_entry_gate_state)
                logger.info(
                    "Suggestion monitor strategy window | anchor=%s | outcome=%s | attempt=%s | event_id=%s",
                    event_doc.get("anchor_number"),
                    updated_event.get("window_result_status"),
                    updated_event.get("window_result_attempt"),
                    event_id,
                )
                self.pending_events.pop(event_id, None)
            else:
                self.pending_events[event_id] = updated_event

    def _compute_runtime_pattern_weights(self) -> Dict[str, float]:
        if not self.dynamic_weights_enabled:
            return {}
        summary = build_realtime_pattern_weights(
            self.recent_resolved_base_events,
            previous_weights=self.dynamic_pattern_weights,
            lookback=self.dynamic_weights_lookback,
            weight_floor=self.dynamic_weight_floor,
            weight_ceil=self.dynamic_weight_ceil,
            smoothing_alpha=self.dynamic_weight_smoothing,
            sample_target=self.dynamic_weight_sample_target,
            top_rank_bonus=self.dynamic_top_rank_bonus,
        )
        return {
            str(pattern_id): float(weight)
            for pattern_id, weight in dict(summary.get("weights") or {}).items()
            if str(pattern_id).strip()
        }

    async def _fetch_simple_suggestion(
        self,
        *,
        history_values: List[int],
        focus_number: int,
    ) -> tuple[Dict[str, Any] | None, str | None, str | None]:
        url = f"{self.base_url}{self.simple_path}"
        runtime_dynamic_summary = (
            build_realtime_pattern_weights(
                self.recent_resolved_base_events,
                previous_weights=self.dynamic_pattern_weights,
                lookback=self.dynamic_weights_lookback,
                weight_floor=self.dynamic_weight_floor,
                weight_ceil=self.dynamic_weight_ceil,
                smoothing_alpha=self.dynamic_weight_smoothing,
                sample_target=self.dynamic_weight_sample_target,
                top_rank_bonus=self.dynamic_top_rank_bonus,
            )
            if self.dynamic_weights_enabled
            else {
                "enabled": False,
                "applied": False,
                "weight_count": 0,
                "weights": {},
                "top_weights": [],
                "details": {},
            }
        )
        runtime_dynamic_weights = {
            str(pattern_id): float(weight)
            for pattern_id, weight in dict(runtime_dynamic_summary.get("weights") or {}).items()
            if str(pattern_id).strip()
        }
        if runtime_dynamic_weights:
            self.dynamic_pattern_weights = dict(runtime_dynamic_weights)
        payload = {
            "history": history_values,
            "focus_number": int(focus_number),
            "from_index": 0,
            "max_numbers": self.max_numbers,
            "optimized_max_numbers": int(settings.suggestion_monitor_optimized_max_numbers),
            "base_weight": float(settings.suggestion_monitor_base_weight),
            "optimized_weight": float(settings.suggestion_monitor_optimized_weight),
            "runtime_overrides": dict(settings.suggestion_monitor_runtime_overrides),
            "siege_window": int(settings.suggestion_monitor_siege_window),
            "siege_min_occurrences": int(settings.suggestion_monitor_siege_min_occurrences),
            "siege_min_streak": int(settings.suggestion_monitor_siege_min_streak),
            "siege_veto_relief": float(settings.suggestion_monitor_siege_veto_relief),
            "block_bets_enabled": bool(settings.suggestion_monitor_block_bets_enabled),
            "inversion_enabled": bool(settings.suggestion_monitor_inversion_enabled),
            "inversion_context_window": int(settings.suggestion_monitor_inversion_context_window),
            "inversion_penalty_factor": float(settings.suggestion_monitor_inversion_penalty_factor),
            "weight_profile_id": settings.suggestion_monitor_weight_profile_id,
            "weight_profile_weights": runtime_dynamic_weights,
            "protected_mode_enabled": bool(settings.suggestion_monitor_protected_mode_enabled),
            "protected_suggestion_size": int(settings.suggestion_monitor_protected_suggestion_size),
            "protected_swap_enabled": bool(settings.suggestion_monitor_protected_swap_enabled),
            "cold_count": int(settings.suggestion_monitor_cold_count),
        }
        started_at = time.perf_counter()
        try:
            timeout = aiohttp.ClientTimeout(
                total=self.api_timeout_seconds,
                connect=min(10.0, self.api_timeout_seconds),
            )
            connector = aiohttp.TCPConnector(
                force_close=True,
                enable_cleanup_closed=True,
                ttl_dns_cache=300,
            )
            async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
                async with session.post(url, json=payload, headers={"Connection": "close"}) as response:
                    body_text = await response.text()
                    if response.status >= 400:
                        if response.status == 404:
                            logger.error(
                                "Suggestion monitor HTTP 404 | endpoint=%s | resposta=%s",
                                url,
                                body_text[:300],
                            )
                        return None, "generation_error", (
                            f"API simple-suggestion respondeu {response.status} em {url}: {body_text[:300]}"
                        )
                    try:
                        data = json.loads(body_text)
                    except json.JSONDecodeError:
                        return None, "generation_error", f"Resposta JSON invalida da API simple-suggestion em {url}."
                    if not isinstance(data, dict):
                        return None, "generation_error", f"Resposta inesperada da API simple-suggestion em {url}."
                    data = dict(data)
                    data["dynamic_weighting"] = {
                        "enabled": bool(runtime_dynamic_summary.get("enabled", False)),
                        "applied": bool(runtime_dynamic_summary.get("applied", False)),
                        "weight_count": int(runtime_dynamic_summary.get("weight_count", 0) or 0),
                        "weights": {
                            str(pattern_id): float(weight)
                            for pattern_id, weight in dict(runtime_dynamic_summary.get("weights") or {}).items()
                            if str(pattern_id).strip()
                        },
                        "top_weights": [
                            item
                            for item in (runtime_dynamic_summary.get("top_weights") or [])
                            if isinstance(item, Mapping)
                        ],
                        "details": {
                            str(pattern_id): dict(detail)
                            for pattern_id, detail in dict(runtime_dynamic_summary.get("details") or {}).items()
                            if str(pattern_id).strip() and isinstance(detail, Mapping)
                        },
                    }
                    logger.info(
                        "Suggestion monitor dynamic weights | applied=%s | count=%d | top=%s",
                        data["dynamic_weighting"]["applied"],
                        data["dynamic_weighting"]["weight_count"],
                        data["dynamic_weighting"]["top_weights"][:3],
                    )
                    elapsed_ms = (time.perf_counter() - started_at) * 1000.0
                    if elapsed_ms >= 1000.0:
                        logger.warning(
                            "Suggestion monitor simple-suggestion lento | elapsed_ms=%.2f | history=%d | from_index=%d | focus=%d",
                            elapsed_ms,
                            len(history_values),
                            0,
                            int(focus_number),
                        )
                    return data, None, None
        except asyncio.TimeoutError:
            return None, "generation_error", f"Timeout ao consultar simple-suggestion em {url}."
        except aiohttp.ClientError as exc:
            return None, "generation_error", f"Falha HTTP ao consultar simple-suggestion em {url}: {exc}"
        except Exception as exc:
            logger.exception("Erro inesperado ao consultar simple-suggestion")
            return None, "generation_error", f"Erro inesperado ao consultar simple-suggestion em {url}: {exc}"


async def main() -> None:
    worker = SuggestionMonitorWorker()
    await worker.run()
