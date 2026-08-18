from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime


def _iso(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, UTC).isoformat()


@dataclass
class CollectorState:
    started_at: float = field(default_factory=time.time)
    websocket_connected: bool = False
    mongo_ok: bool = False
    redis_ok: bool = False
    last_message_at: float | None = None
    last_result_at: float | None = None
    last_db_write_at: float | None = None
    last_redis_publish_at: float | None = None
    last_error: str | None = None
    results_total: int = 0
    duplicates_total: int = 0
    reconnects_total: int = 0
    mongo_errors_total: int = 0
    redis_errors_total: int = 0
    invalid_messages_total: int = 0
    watchdog_failures_total: int = 0
    table_last_result_at: dict[str, float] = field(default_factory=dict)
    _recent_ids: dict[str, deque[str]] = field(default_factory=lambda: defaultdict(lambda: deque(maxlen=200)))
    _recent_sets: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def set_connection(self, connected: bool) -> None:
        with self._lock:
            self.websocket_connected = connected

    def record_message(self) -> None:
        with self._lock:
            self.last_message_at = time.time()

    def record_reconnect(self) -> None:
        with self._lock:
            self.reconnects_total += 1

    def record_invalid(self) -> None:
        with self._lock:
            self.invalid_messages_total += 1

    def record_error(self, message: str) -> None:
        with self._lock:
            self.last_error = message[:500]

    def mark_seen(self, roulette_id: str, game_id: str) -> None:
        with self._lock:
            recent = self._recent_ids[roulette_id]
            seen = self._recent_sets[roulette_id]
            if game_id in seen:
                return
            if len(recent) == recent.maxlen:
                seen.discard(recent[0])
            recent.append(game_id)
            seen.add(game_id)

    def was_seen(self, roulette_id: str, game_id: str) -> bool:
        with self._lock:
            return game_id in self._recent_sets[roulette_id]

    def record_duplicate(self) -> None:
        with self._lock:
            self.duplicates_total += 1

    def record_persisted(self, roulette_id: str) -> None:
        now = time.time()
        with self._lock:
            self.results_total += 1
            self.last_result_at = now
            self.last_db_write_at = now
            self.mongo_ok = True
            self.table_last_result_at[roulette_id] = now

    def record_published(self) -> None:
        with self._lock:
            self.last_redis_publish_at = time.time()
            self.redis_ok = True

    def record_mongo_error(self, message: str) -> None:
        with self._lock:
            self.mongo_ok = False
            self.mongo_errors_total += 1
            self.last_error = message[:500]

    def record_redis_error(self, message: str) -> None:
        with self._lock:
            self.redis_ok = False
            self.redis_errors_total += 1
            self.last_error = message[:500]

    def readiness(self, ws_stale_seconds: int, result_stale_seconds: int, startup_grace_seconds: int) -> tuple[bool, list[str]]:
        now = time.time()
        with self._lock:
            reasons: list[str] = []
            if not self.mongo_ok:
                reasons.append("mongo_unavailable")
            if not self.redis_ok:
                reasons.append("redis_unavailable")
            if not self.websocket_connected:
                reasons.append("websocket_disconnected")
            if now - self.started_at >= startup_grace_seconds:
                if self.last_message_at is None or now - self.last_message_at > ws_stale_seconds:
                    reasons.append("websocket_stale")
                if self.last_result_at is None or now - self.last_result_at > result_stale_seconds:
                    reasons.append("results_stale")
            return not reasons, reasons

    def snapshot(self, ws_stale_seconds: int, result_stale_seconds: int, startup_grace_seconds: int) -> dict:
        ready, reasons = self.readiness(ws_stale_seconds, result_stale_seconds, startup_grace_seconds)
        with self._lock:
            return {
                "status": "ready" if ready else "not_ready",
                "reasons": reasons,
                "started_at": _iso(self.started_at),
                "websocket_connected": self.websocket_connected,
                "mongo_ok": self.mongo_ok,
                "redis_ok": self.redis_ok,
                "last_message_at": _iso(self.last_message_at),
                "last_result_at": _iso(self.last_result_at),
                "last_db_write_at": _iso(self.last_db_write_at),
                "last_redis_publish_at": _iso(self.last_redis_publish_at),
                "last_error": self.last_error,
                "results_total": self.results_total,
                "duplicates_total": self.duplicates_total,
                "reconnects_total": self.reconnects_total,
                "mongo_errors_total": self.mongo_errors_total,
                "redis_errors_total": self.redis_errors_total,
                "invalid_messages_total": self.invalid_messages_total,
                "watchdog_failures_total": self.watchdog_failures_total,
                "tables_seen": len(self.table_last_result_at),
            }
