from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Mapping

import aiohttp
import redis.asyncio as aioredis

from src.config import settings
from src.suggestion_monitor_repo import SuggestionMonitorRepository
from src.suggestion_monitor_runtime import (
    build_attempt_document,
    build_config_key,
    build_event_resolution_fields,
    build_monitor_event_document,
    build_oscillation_payload_from_base,
    build_temporal_blend_payload_from_base,
    build_selective_compact_payload_from_base,
    build_pattern_outcome_documents,
    build_pattern_resolution_documents,
)


logger = logging.getLogger(__name__)


class SuggestionMonitorWorker:
    def __init__(self) -> None:
        self.roulette_id = settings.suggestion_monitor_roulette_id
        self.max_numbers = max(1, min(37, int(settings.suggestion_monitor_max_numbers)))
        self.history_window_size = max(10, int(settings.suggestion_monitor_history_window))
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
        self.optimized_config_key = f"{self.config_key}|variant=oscillation_v1"
        self.aggressive_config_key = f"{self.config_key}|variant=oscillation_v2_aggressive"
        self.selective_config_key = f"{self.config_key}|variant=oscillation_v3_selective"
        self.selective_protected_config_key = f"{self.config_key}|variant=oscillation_v3_selective_protected"
        self.temporal_blend_config_key = f"{self.config_key}|variant=temporal_blend_v1"
        self.selective_compact_config_key = f"{self.config_key}|variant=oscillation_v4_selective_compact"
        self.pending_events: Dict[str, Dict[str, Any]] = {}
        self.offset_doc: Dict[str, Any] | None = None
        self.last_resolved_base_event: Dict[str, Any] | None = None
        self.recent_resolved_base_events: List[Dict[str, Any]] = []
        self.selective_compact_hold_state: Dict[str, Any] = {}
        self.results_redis = None
        self.session: aiohttp.ClientSession | None = None
        self._startup_reconcile_done = False

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
            "Suggestion monitor | variants base=%s optimized=%s aggressive=%s selective=%s selective_protected=%s temporal=%s compact=%s",
            self.base_config_key,
            self.optimized_config_key,
            self.aggressive_config_key,
            self.selective_config_key,
            self.selective_protected_config_key,
            self.temporal_blend_config_key,
            self.selective_compact_config_key,
        )
        await asyncio.to_thread(self.repo.ensure_indexes)
        logger.info("Suggestion monitor | indices Mongo garantidos.")
        await self._bootstrap_state()

        timeout = aiohttp.ClientTimeout(total=self.api_timeout_seconds)
        self.results_redis = aioredis.from_url(settings.results_redis_url, decode_responses=True)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            self.session = session
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
                self.session = None

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
            self.optimized_config_key,
            self.aggressive_config_key,
            self.selective_config_key,
            self.selective_protected_config_key,
            self.temporal_blend_config_key,
            self.selective_compact_config_key,
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
        self.selective_compact_hold_state = {}
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
        optimized_pending = await asyncio.to_thread(
            self.repo.load_pending_events,
            roulette_id=self.roulette_id,
            config_key=self.optimized_config_key,
        )
        aggressive_pending = await asyncio.to_thread(
            self.repo.load_pending_events,
            roulette_id=self.roulette_id,
            config_key=self.aggressive_config_key,
        )
        selective_pending = await asyncio.to_thread(
            self.repo.load_pending_events,
            roulette_id=self.roulette_id,
            config_key=self.selective_config_key,
        )
        selective_protected_pending = await asyncio.to_thread(
            self.repo.load_pending_events,
            roulette_id=self.roulette_id,
            config_key=self.selective_protected_config_key,
        )
        temporal_blend_pending = await asyncio.to_thread(
            self.repo.load_pending_events,
            roulette_id=self.roulette_id,
            config_key=self.temporal_blend_config_key,
        )
        selective_compact_pending = await asyncio.to_thread(
            self.repo.load_pending_events,
            roulette_id=self.roulette_id,
            config_key=self.selective_compact_config_key,
        )
        pending = [
            *base_pending,
            *optimized_pending,
            *aggressive_pending,
            *selective_pending,
            *selective_protected_pending,
            *temporal_blend_pending,
            *selective_compact_pending,
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
            limit=8,
        )
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
            self.optimized_config_key,
            self.aggressive_config_key,
            self.selective_config_key,
            self.selective_protected_config_key,
            self.temporal_blend_config_key,
            self.selective_compact_config_key,
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
        self.selective_compact_hold_state = {}
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

        history_docs = await asyncio.to_thread(
            self.repo.get_history_window_up_to,
            roulette_id=self.roulette_id,
            anchor_history_timestamp_utc=history_doc["history_timestamp_utc"],
            anchor_history_id=history_doc["history_id"],
            limit=self.history_window_size,
        )
        history_values = [int(item["value"]) for item in history_docs]
        simple_payload, status_override, error_message = await self._fetch_simple_suggestion(
            history_values=history_values,
            focus_number=int(history_doc["value"]),
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
        optimized_payload = (
            build_oscillation_payload_from_base(
                base_payload=simple_payload,
                recent_resolved_base_events=self.recent_resolved_base_events,
                profile="oscillation_v1",
            )
            if status_override is None and isinstance(simple_payload, Mapping)
            else None
        )
        aggressive_payload = (
            build_oscillation_payload_from_base(
                base_payload=simple_payload,
                recent_resolved_base_events=self.recent_resolved_base_events,
                profile="oscillation_v2_aggressive",
            )
            if status_override is None and isinstance(simple_payload, Mapping)
            else None
        )
        selective_payload = (
            build_oscillation_payload_from_base(
                base_payload=simple_payload,
                recent_resolved_base_events=self.recent_resolved_base_events,
                profile="oscillation_v3_selective",
            )
            if status_override is None and isinstance(simple_payload, Mapping)
            else None
        )
        selective_protected_payload = (
            build_oscillation_payload_from_base(
                base_payload=simple_payload,
                recent_resolved_base_events=self.recent_resolved_base_events,
                profile="oscillation_v3_selective_protected",
            )
            if status_override is None and isinstance(simple_payload, Mapping)
            else None
        )
        temporal_blend_payload = (
            build_temporal_blend_payload_from_base(
                base_payload=simple_payload,
                recent_resolved_base_events=self.recent_resolved_base_events,
                history_values=history_values,
            )
            if status_override is None and isinstance(simple_payload, Mapping)
            else None
        )
        selective_compact_payload = (
            build_selective_compact_payload_from_base(
                base_payload=simple_payload,
                recent_resolved_base_events=self.recent_resolved_base_events,
                hold_state=self.selective_compact_hold_state,
                compact_size=18,
                hold_rounds=3,
            )
            if status_override is None and isinstance(simple_payload, Mapping)
            else None
        )
        optimized_status_override = status_override
        optimized_error_message = error_message
        if optimized_payload is None and optimized_status_override is None:
            optimized_status_override = "unavailable"
            optimized_error_message = "Oscillation v1 indisponivel: ranking base sem dados suficientes."
        aggressive_status_override = status_override
        aggressive_error_message = error_message
        if aggressive_payload is None and aggressive_status_override is None:
            aggressive_status_override = "unavailable"
            aggressive_error_message = "Oscillation v2 aggressive indisponivel: ranking base sem dados suficientes."
        selective_status_override = status_override
        selective_error_message = error_message
        if selective_payload is None and selective_status_override is None:
            selective_status_override = "unavailable"
            selective_error_message = "Oscillation v3 selective indisponivel: gate sem tendência confirmada."
        selective_protected_status_override = status_override
        selective_protected_error_message = error_message
        if selective_protected_payload is None and selective_protected_status_override is None:
            selective_protected_status_override = "unavailable"
            selective_protected_error_message = "Oscillation v3 selective protected indisponivel: gate sem tendência confirmada."
        temporal_blend_status_override = status_override
        temporal_blend_error_message = error_message
        if temporal_blend_payload is None and temporal_blend_status_override is None:
            temporal_blend_status_override = "unavailable"
            temporal_blend_error_message = "Temporal blend v1 indisponivel: ranking base sem dados suficientes."
        selective_compact_status_override = status_override
        selective_compact_error_message = error_message
        if selective_compact_payload is None and selective_compact_status_override is None:
            selective_compact_status_override = "unavailable"
            selective_compact_error_message = "Oscillation v4 selective compact indisponivel."
        optimized_event_doc = build_monitor_event_document(
            anchor_doc=history_doc,
            simple_payload=optimized_payload,
            history_values=history_values,
            config_key=self.optimized_config_key,
            ranking_variant="oscillation_v1",
            source_base_event_id=str(base_event_doc["_id"]),
            source_base_config_key=self.base_config_key,
            suggestion_type="simple_http",
            status_override=optimized_status_override,
            error_message=optimized_error_message,
        )
        aggressive_event_doc = build_monitor_event_document(
            anchor_doc=history_doc,
            simple_payload=aggressive_payload,
            history_values=history_values,
            config_key=self.aggressive_config_key,
            ranking_variant="oscillation_v2_aggressive",
            source_base_event_id=str(base_event_doc["_id"]),
            source_base_config_key=self.base_config_key,
            suggestion_type="simple_http",
            status_override=aggressive_status_override,
            error_message=aggressive_error_message,
        )
        selective_event_doc = build_monitor_event_document(
            anchor_doc=history_doc,
            simple_payload=selective_payload,
            history_values=history_values,
            config_key=self.selective_config_key,
            ranking_variant="oscillation_v3_selective",
            source_base_event_id=str(base_event_doc["_id"]),
            source_base_config_key=self.base_config_key,
            suggestion_type="simple_http",
            status_override=selective_status_override,
            error_message=selective_error_message,
        )
        selective_protected_event_doc = build_monitor_event_document(
            anchor_doc=history_doc,
            simple_payload=selective_protected_payload,
            history_values=history_values,
            config_key=self.selective_protected_config_key,
            ranking_variant="oscillation_v3_selective_protected",
            source_base_event_id=str(base_event_doc["_id"]),
            source_base_config_key=self.base_config_key,
            suggestion_type="simple_http",
            status_override=selective_protected_status_override,
            error_message=selective_protected_error_message,
        )
        temporal_blend_event_doc = build_monitor_event_document(
            anchor_doc=history_doc,
            simple_payload=temporal_blend_payload,
            history_values=history_values,
            config_key=self.temporal_blend_config_key,
            ranking_variant="temporal_blend_v1",
            source_base_event_id=str(base_event_doc["_id"]),
            source_base_config_key=self.base_config_key,
            suggestion_type="simple_http",
            status_override=temporal_blend_status_override,
            error_message=temporal_blend_error_message,
        )
        selective_compact_event_doc = build_monitor_event_document(
            anchor_doc=history_doc,
            simple_payload=selective_compact_payload,
            history_values=history_values,
            config_key=self.selective_compact_config_key,
            ranking_variant="oscillation_v4_selective_compact",
            source_base_event_id=str(base_event_doc["_id"]),
            source_base_config_key=self.base_config_key,
            suggestion_type="simple_http",
            status_override=selective_compact_status_override,
            error_message=selective_compact_error_message,
        )

        event_docs = [
            base_event_doc,
            optimized_event_doc,
            aggressive_event_doc,
            selective_event_doc,
            selective_protected_event_doc,
            temporal_blend_event_doc,
            selective_compact_event_doc,
        ]
        compact_hold = (
            ((selective_compact_payload or {}).get("oscillation") or {}).get("compact_hold")
            if isinstance(selective_compact_payload, Mapping)
            else None
        )
        self.selective_compact_hold_state = dict(compact_hold) if isinstance(compact_hold, Mapping) else {}
        for event_doc in event_docs:
            pattern_docs = build_pattern_outcome_documents(event_doc)
            await asyncio.to_thread(self.repo.upsert_event, event_doc)
            if pattern_docs:
                await asyncio.to_thread(self.repo.upsert_pattern_outcomes, pattern_docs)
            if event_doc.get("status") == "pending":
                self.pending_events[str(event_doc["_id"])] = dict(event_doc)

        logger.info(
            "Suggestion monitor evento | numero=%s | timestamp=%s | resolvidas_agora=%d | base_status=%s | optimized_status=%s | aggressive_status=%s | selective_status=%s | selective_protected_status=%s | temporal_status=%s | compact_status=%s | base_size=%d | optimized_size=%d | aggressive_size=%d | selective_size=%d | selective_protected_size=%d | temporal_size=%d | compact_size=%d | pendencias=%d | detalhe=%s",
            history_doc["value"],
            history_doc["history_timestamp_br"],
            resolved_now,
            base_event_doc.get("status"),
            optimized_event_doc.get("status"),
            aggressive_event_doc.get("status"),
            selective_event_doc.get("status"),
            selective_protected_event_doc.get("status"),
            temporal_blend_event_doc.get("status"),
            selective_compact_event_doc.get("status"),
            int(base_event_doc.get("suggestion_size") or 0),
            int(optimized_event_doc.get("suggestion_size") or 0),
            int(aggressive_event_doc.get("suggestion_size") or 0),
            int(selective_event_doc.get("suggestion_size") or 0),
            int(selective_protected_event_doc.get("suggestion_size") or 0),
            int(temporal_blend_event_doc.get("suggestion_size") or 0),
            int(selective_compact_event_doc.get("suggestion_size") or 0),
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
            attempt_doc = build_attempt_document(event_doc, result_doc)
            resolution_fields = build_event_resolution_fields(event_doc, attempt_doc)
            pattern_resolution_docs = build_pattern_resolution_documents(event_doc, attempt_doc)
            updated_event = await asyncio.to_thread(
                self.repo.apply_attempt,
                event_doc=event_doc,
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
                    self.recent_resolved_base_events = list(deduped.values())[:8]
                self.pending_events.pop(event_id, None)
            elif bool(updated_event.get("window_result_finalized")):
                logger.info(
                    "Suggestion monitor compact window | anchor=%s | outcome=%s | attempt=%s | event_id=%s",
                    event_doc.get("anchor_number"),
                    updated_event.get("window_result_status"),
                    updated_event.get("window_result_attempt"),
                    event_id,
                )
                self.pending_events.pop(event_id, None)
            else:
                self.pending_events[event_id] = updated_event

    async def _fetch_simple_suggestion(
        self,
        *,
        history_values: List[int],
        focus_number: int,
    ) -> tuple[Dict[str, Any] | None, str | None, str | None]:
        if self.session is None:
            return None, "generation_error", "Sessao HTTP indisponivel."

        url = f"{self.base_url}{self.simple_path}"
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
            "protected_mode_enabled": bool(settings.suggestion_monitor_protected_mode_enabled),
            "protected_suggestion_size": int(settings.suggestion_monitor_protected_suggestion_size),
            "protected_swap_enabled": bool(settings.suggestion_monitor_protected_swap_enabled),
            "cold_count": int(settings.suggestion_monitor_cold_count),
        }
        try:
            async with self.session.post(url, json=payload) as response:
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
