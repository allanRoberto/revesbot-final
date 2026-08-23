from __future__ import annotations

import logging
import os
import socket
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .contracts import LoadedPattern, PatternCandidate, Spin
from .mongo_history import MongoHistorySource
from .redis_projection import RedisProjection
from .repository import PatternRepository


log = logging.getLogger("patterns.runtime")
TZ_BR = ZoneInfo("America/Sao_Paulo")


def payout_for_roulette(roulette_id: str) -> int:
    return 30 if "mega" in roulette_id.lower() else 36


def is_hour_eligible(schedules: dict[str, tuple[int, ...]] | Any, spin: Spin) -> bool:
    configured = tuple(int(hour) for hour in (schedules.get(spin.roulette_id) or ()))
    if not configured:
        return False
    return spin.timestamp.astimezone(TZ_BR).hour in configured


def _signal_has_spin(signal: dict[str, Any], history_id: str) -> bool:
    for field in ("attempts", "waiting_spins"):
        if any(str(item.get("history_id")) == history_id for item in signal.get(field) or []):
            return True
    return False


def build_signal_document(
    *,
    loaded: LoadedPattern,
    pattern_id: Any,
    roulette_id: str,
    trigger: Spin,
    candidate: PatternCandidate,
    eligible_hour: bool,
) -> dict[str, Any]:
    definition = loaded.definition
    status = "active" if eligible_hour else "skipped_outside_schedule"
    now = datetime.now(timezone.utc)
    payout = payout_for_roulette(roulette_id)
    runtime = dict(candidate.runtime)
    phase = "waiting" if int(runtime.get("delay_remaining") or 0) > 0 else "betting"
    return {
        "pattern_id": pattern_id,
        "pattern_key": definition.key,
        "pattern_version": definition.version,
        "roulette_id": roulette_id,
        "trigger_history_id": trigger.history_id,
        "trigger_number": candidate.trigger_number,
        "trigger_timestamp": trigger.timestamp,
        "trigger_hour_br": trigger.timestamp.astimezone(TZ_BR).hour,
        "eligible_hour": eligible_hour,
        "schedule_applied": list(definition.schedules.get(roulette_id) or ()),
        "status": status,
        "phase": phase if eligible_hour else "skipped",
        "target_name": candidate.target_name,
        "bet_numbers": list(candidate.bet_numbers),
        "bet_count": len(candidate.bet_numbers),
        "max_attempts": definition.max_attempts,
        "chip_profile": list(definition.default_chip_profile),
        "payout": payout,
        "attempts": [],
        "waiting_spins": [],
        "won_at_attempt": None,
        "result": None,
        "financial": {
            "currency": "BRL",
            "base_chip_per_number": 1.0,
            "total_wagered": 0.0,
            "gross_return": 0.0,
            "net_profit": 0.0,
        },
        "runtime": runtime,
        "details": dict(candidate.details),
        "created_at": now,
        "resolved_at": now if not eligible_hour else None,
        "updated_at": now,
    }


def apply_spin_to_signal(
    loaded: LoadedPattern,
    signal: dict[str, Any],
    spin: Spin,
) -> tuple[dict[str, Any], bool]:
    """Aplica um giro de forma idempotente. Retorna (sinal, mudou)."""
    if signal.get("status") != "active" or _signal_has_spin(signal, spin.history_id):
        return signal, False

    gate = loaded.engine.before_attempt(signal, spin)
    signal["runtime"] = dict(gate.runtime)
    signal["updated_at"] = datetime.now(timezone.utc)

    if not gate.count_attempt:
        signal.setdefault("waiting_spins", []).append(
            {**spin.audit_dict(), "reason": gate.reason or "pattern_wait"}
        )
        signal["phase"] = "waiting"
        return signal, True

    attempts = signal.setdefault("attempts", [])
    attempt_number = len(attempts) + 1
    max_attempts = int(signal.get("max_attempts") or loaded.definition.max_attempts)
    if attempt_number > max_attempts:
        return signal, False

    chip_profile = [float(value) for value in signal.get("chip_profile") or ()]
    if len(chip_profile) < max_attempts:
        chip_profile.extend([1.0] * (max_attempts - len(chip_profile)))
    chip = chip_profile[attempt_number - 1]
    bet_numbers = {int(value) for value in signal.get("bet_numbers") or ()}
    bet_count = len(bet_numbers)
    cost = bet_count * chip
    hit = spin.value in bet_numbers
    attempts.append(
        {
            **spin.audit_dict(),
            "attempt_number": attempt_number,
            "chip_per_number": chip,
            "bet_count": bet_count,
            "cost": cost,
            "hit": hit,
        }
    )

    total_wagered = float(sum(float(item.get("cost") or 0) for item in attempts))
    payout = int(signal.get("payout") or 36)
    gross_return = payout * chip if hit else 0.0
    financial = signal.setdefault("financial", {})
    financial.update(
        {
            "currency": "BRL",
            "base_chip_per_number": 1.0,
            "total_wagered": total_wagered,
            "gross_return": gross_return,
            "net_profit": gross_return - total_wagered if hit else -total_wagered,
        }
    )
    signal["phase"] = "betting"

    if hit:
        signal["status"] = "won"
        signal["won_at_attempt"] = attempt_number
        signal["result"] = spin.audit_dict()
        signal["resolved_at"] = spin.timestamp
        signal["phase"] = "resolved"
    elif attempt_number >= max_attempts:
        signal["status"] = "lost"
        signal["result"] = spin.audit_dict()
        signal["resolved_at"] = spin.timestamp
        signal["phase"] = "resolved"
    return signal, True


@dataclass
class TableContext:
    roulette_id: str
    history: list[Spin]
    cursor_id: Any
    last_timestamp: datetime
    active_signal: dict[str, Any] | None = None
    processed_count: int = 0
    late_count: int = 0
    gap_count: int = 0


@dataclass(frozen=True)
class RuntimeSettings:
    poll_seconds: float = 1.0
    batch_size: int = 200
    gap_seconds: int = 300
    lease_seconds: int = 30
    projection_every_seconds: int = 30

    @classmethod
    def from_env(cls) -> "RuntimeSettings":
        return cls(
            poll_seconds=float(os.getenv("PATTERN_POLL_SECONDS", "1")),
            batch_size=int(os.getenv("PATTERN_BATCH_SIZE", "200")),
            gap_seconds=int(os.getenv("PATTERN_GAP_SECONDS", "300")),
            lease_seconds=int(os.getenv("PATTERN_LEASE_SECONDS", "30")),
            projection_every_seconds=int(os.getenv("PATTERN_PROJECTION_SECONDS", "30")),
        )


class PatternRuntime:
    def __init__(
        self,
        *,
        loaded: LoadedPattern,
        repository: PatternRepository,
        history_source: MongoHistorySource,
        projection: RedisProjection | None = None,
        settings: RuntimeSettings | None = None,
        owner: str | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.loaded = loaded
        self.repository = repository
        self.history_source = history_source
        self.projection = projection or RedisProjection()
        self.settings = settings or RuntimeSettings.from_env()
        self.owner = owner or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self.monotonic = monotonic
        self.pattern_document: dict[str, Any] | None = None
        self.tables: dict[str, TableContext] = {}
        self._last_lease = 0.0
        self._last_projection = 0.0
        self._running = False

    @property
    def key(self) -> str:
        return self.loaded.definition.key

    def initialize(self) -> None:
        self.repository.ensure_indexes()
        self.pattern_document = self.repository.upsert_definition(self.loaded.definition)
        if not self.repository.acquire_lease(
            self.key,
            self.owner,
            ttl_seconds=self.settings.lease_seconds,
        ):
            raise RuntimeError(f"pattern {self.key} ja esta em execucao")
        self._last_lease = self.monotonic()

        for roulette_id in self.loaded.definition.roulette_ids:
            state = self.repository.load_state(self.key, roulette_id)
            if (
                state
                and state.get("last_history_id") is not None
                and isinstance(state.get("last_history_timestamp"), datetime)
            ):
                history = self.history_source.ending_at(
                    roulette_id,
                    state["last_history_id"],
                    state["last_history_timestamp"],
                    self.loaded.definition.history_size,
                )
                cursor_id = state["last_history_id"]
                last_timestamp = state.get("last_history_timestamp")
                if not isinstance(last_timestamp, datetime):
                    last_timestamp = history[0].timestamp if history else datetime.now(timezone.utc)
            else:
                history = self.history_source.latest(
                    roulette_id,
                    self.loaded.definition.history_size,
                )
                if not history:
                    log.warning("%s sem historico inicial", roulette_id)
                    continue
                cursor_id = history[0].source_id
                last_timestamp = history[0].timestamp

            active_signal = self.repository.load_active_signal(self.key, roulette_id)
            context = TableContext(
                roulette_id=roulette_id,
                history=history,
                cursor_id=cursor_id,
                last_timestamp=last_timestamp,
                active_signal=active_signal,
                processed_count=int((state or {}).get("processed_count") or 0),
                late_count=int((state or {}).get("late_count") or 0),
                gap_count=int((state or {}).get("gap_count") or 0),
            )
            self.tables[roulette_id] = context
            self._save_table_state(context)

        self._publish_dashboard()
        log.info(
            "Pattern %s %s iniciado | mesas=%d | fonte=MongoDB",
            self.key,
            self.loaded.definition.version,
            len(self.tables),
        )

    def _save_table_state(self, context: TableContext) -> None:
        self.repository.save_state(
            {
                "pattern_id": self.pattern_document.get("_id") if self.pattern_document else None,
                "pattern_key": self.key,
                "roulette_id": context.roulette_id,
                "last_history_id": context.cursor_id,
                "last_history_timestamp": context.last_timestamp,
                "active_signal_id": (
                    context.active_signal.get("_id") if context.active_signal else None
                ),
                "processed_count": context.processed_count,
                "late_count": context.late_count,
                "gap_count": context.gap_count,
                "status": "monitoring",
            }
        )

    def _publish_dashboard(self) -> None:
        snapshot = self.repository.dashboard_snapshot(self.key)
        self.projection.publish_dashboard(self.key, snapshot)
        self._last_projection = self.monotonic()

    def _cancel_for_gap(self, context: TableContext, spin: Spin, gap_seconds: float) -> None:
        if context.active_signal:
            signal = context.active_signal
            signal["status"] = "cancelled_gap"
            signal["phase"] = "cancelled"
            signal["resolved_at"] = spin.timestamp
            signal["updated_at"] = datetime.now(timezone.utc)
            signal["details"] = {
                **dict(signal.get("details") or {}),
                "cancelled_gap_seconds": gap_seconds,
                "cancelled_before_history_id": spin.history_id,
            }
            self.repository.save_signal(signal)
            context.active_signal = None
        context.history = [spin]
        context.gap_count += 1

    def _create_candidate_signal(
        self,
        context: TableContext,
        spin: Spin,
        candidate: PatternCandidate,
    ) -> None:
        eligible = is_hour_eligible(dict(self.loaded.definition.schedules), spin)
        document = build_signal_document(
            loaded=self.loaded,
            pattern_id=self.pattern_document.get("_id") if self.pattern_document else None,
            roulette_id=context.roulette_id,
            trigger=spin,
            candidate=candidate,
            eligible_hour=eligible,
        )
        stored, created = self.repository.create_signal(document)
        if created:
            log.info(
                "%s | %s | sinal=%s | numeros=%s | horario=%s",
                self.key,
                context.roulette_id,
                stored.get("status"),
                stored.get("bet_numbers"),
                stored.get("trigger_hour_br"),
            )
        if stored.get("status") == "active":
            context.active_signal = stored

    def process_spin(self, context: TableContext, spin: Spin) -> None:
        if spin.timestamp <= context.last_timestamp:
            context.cursor_id = spin.source_id
            context.late_count += 1
            self._save_table_state(context)
            return

        gap_seconds = (spin.timestamp - context.last_timestamp).total_seconds()
        if gap_seconds >= self.settings.gap_seconds:
            self._cancel_for_gap(context, spin, gap_seconds)
            context.cursor_id = spin.source_id
            context.last_timestamp = spin.timestamp
            context.processed_count += 1
            self._save_table_state(context)
            self._publish_dashboard()
            return

        signal_changed = False
        if context.active_signal:
            context.active_signal, signal_changed = apply_spin_to_signal(
                self.loaded,
                context.active_signal,
                spin,
            )
            if signal_changed:
                self.repository.save_signal(context.active_signal)
            if context.active_signal.get("status") != "active":
                context.active_signal = None

        context.history.insert(0, spin)
        del context.history[self.loaded.definition.history_size :]

        if context.active_signal is None and len(context.history) >= self.loaded.definition.required_history:
            candidate = self.loaded.engine.analyze(
                context.history,
                roulette_id=context.roulette_id,
                payout=payout_for_roulette(context.roulette_id),
            )
            if candidate:
                self._create_candidate_signal(context, spin, candidate)
                signal_changed = True

        context.cursor_id = spin.source_id
        context.last_timestamp = spin.timestamp
        context.processed_count += 1
        self._save_table_state(context)
        if signal_changed:
            self._publish_dashboard()

    def poll_once(self) -> int:
        processed = 0
        for context in self.tables.values():
            spins = self.history_source.after(
                context.roulette_id,
                context.cursor_id,
                context.last_timestamp,
                self.settings.batch_size,
            )
            for spin in spins:
                self.process_spin(context, spin)
                processed += 1
        now = self.monotonic()
        if now - self._last_lease >= max(1, self.settings.lease_seconds / 3):
            if not self.repository.acquire_lease(
                self.key,
                self.owner,
                ttl_seconds=self.settings.lease_seconds,
            ):
                raise RuntimeError(f"lease perdida para pattern {self.key}")
            self._last_lease = now
        if now - self._last_projection >= self.settings.projection_every_seconds:
            self._publish_dashboard()
        return processed

    def run_forever(self) -> None:
        self.initialize()
        self._running = True
        try:
            while self._running:
                processed = self.poll_once()
                if processed == 0:
                    time.sleep(self.settings.poll_seconds)
        finally:
            self.repository.release_lease(self.key, self.owner)

    def stop(self) -> None:
        self._running = False
