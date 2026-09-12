from __future__ import annotations

import asyncio
import logging
import os
import uuid
from contextlib import suppress
from typing import Any

from .config import BehaviorLabConfig, load_config
from .contracts import Spin, utc_now_iso
from .engine import BehaviorEngine
from .source_api import ResultAPIClient
from .state_store import RedisStateStore


LOGGER = logging.getLogger("behavior_lab.worker")
MAX_RECONCILE_RESULTS = 50_000
RESOLVED_SIGNAL_RETENTION = max(
    1, int(os.getenv("BEHAVIOR_LAB_RESOLVED_SIGNAL_RETENTION", "50000"))
)
IDENTITY_RETENTION = 1_200


class BehaviorLabWorker:
    def __init__(
        self,
        *,
        config: BehaviorLabConfig,
        source: ResultAPIClient,
        store: RedisStateStore,
        reconcile_interval_seconds: float = 30.0,
    ) -> None:
        self.config = config
        self.source = source
        self.store = store
        self.reconcile_interval_seconds = max(2.0, float(reconcile_interval_seconds))
        self.engine: BehaviorEngine | None = None
        self._lock = asyncio.Lock()
        self._reconcile_lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._ws_connected = False
        self._last_event_at: str | None = None
        self._release_id = os.getenv("BEHAVIOR_LAB_RELEASE_ID", "development")
        self._instance_id = uuid.uuid4().hex
        self._started_at = utc_now_iso()

    async def initialize(self) -> None:
        try:
            restored = await self.store.load_engine(
                resolved_signal_retention=RESOLVED_SIGNAL_RETENTION,
                identity_retention=IDENTITY_RETENTION,
            )
        except (TypeError, ValueError):
            LOGGER.exception("discarding incompatible derived worker state")
            restored = None
        self.engine = restored or BehaviorEngine(
            self.config,
            resolved_signal_retention=RESOLVED_SIGNAL_RETENTION,
            identity_retention=IDENTITY_RETENTION,
        )
        if self.engine.history:
            self._last_event_at = self.engine.history[-1].timestamp
        await self.store.write_health(
            status="starting",
            last_event_at=self._last_event_at,
            ws_connected=False,
            processed_count=self.engine.processed_count,
            active_signals=len(self.engine.ledger.active),
            error=None,
            release_id=self._release_id,
            worker_instance_id=self._instance_id,
            worker_started_at=self._started_at,
        )
        if restored is None:
            spins = await self.source.fetch_history(self.config.context_size)
            for spin in spins:
                self.engine.process(spin, source="bootstrap")
            if spins:
                self._last_event_at = spins[-1].timestamp or utc_now_iso()
            self.engine.reset_prospective_metrics()
            await self.store.save_engine(self.engine)
            await self._persist_health(status="starting")
        else:
            # Re-publish all projections once so state restored from an older
            # non-transactional writer cannot leave a stale public snapshot.
            await self.store.save_engine(self.engine)
            await self.reconcile()

    async def _persist_health(self, *, status: str, error: str | None = None) -> None:
        assert self.engine is not None
        await self.store.write_health(
            status=status,
            last_event_at=self._last_event_at,
            ws_connected=self._ws_connected,
            processed_count=self.engine.processed_count,
            state_revision=self.engine.processed_count,
            active_signals=len(self.engine.ledger.active),
            error=error,
            release_id=self._release_id,
            worker_instance_id=self._instance_id,
            worker_started_at=self._started_at,
        )

    async def process_event(self, spin: Spin, *, count_duplicate: bool = True) -> bool:
        assert self.engine is not None
        async with self._lock:
            outcome = self.engine.process(
                spin,
                source=spin.source,
                count_duplicate=count_duplicate,
            )
            if not outcome.accepted:
                return False
            self._last_event_at = spin.timestamp or utc_now_iso()
            await self.store.save_engine(self.engine)
            await self._persist_health(
                status="healthy" if self._ws_connected else "degraded",
                error=None if self._ws_connected else "websocket_disconnected",
            )
            return True

    async def _reconcile_locked(self) -> int:
        assert self.engine is not None
        spins = await self.source.fetch_history(self.config.context_size)
        if self.engine.history:
            last_keys = set(self.engine.history[-1].identity_keys)
            if not last_keys:
                raise RuntimeError("ultimo evento processado nao possui identidade")

            cursor_index = next(
                (
                    index
                    for index in range(len(spins) - 1, -1, -1)
                    if last_keys.intersection(spins[index].identity_keys)
                ),
                None,
            )
            if cursor_index is None and self.config.context_size < MAX_RECONCILE_RESULTS:
                spins = await self.source.fetch_history(MAX_RECONCILE_RESULTS)
                cursor_index = next(
                    (
                        index
                        for index in range(len(spins) - 1, -1, -1)
                        if last_keys.intersection(spins[index].identity_keys)
                    ),
                    None,
                )
            if cursor_index is None:
                raise RuntimeError(
                    "lacuna de historico: ultimo evento processado nao foi localizado"
                )
            spins = spins[cursor_index + 1 :]

        accepted = 0
        async with self._lock:
            for spin in spins:
                outcome = self.engine.process(
                    spin,
                    source=spin.source,
                    count_duplicate=False,
                )
                if not outcome.accepted:
                    continue
                accepted += 1
                self._last_event_at = spin.timestamp or utc_now_iso()
            if accepted:
                await self.store.save_engine(self.engine)
            await self._persist_health(
                status="healthy" if self._ws_connected else "degraded",
                error=None if self._ws_connected else "websocket_disconnected",
            )
        return accepted

    async def reconcile(self) -> int:
        async with self._reconcile_lock:
            return await self._reconcile_locked()

    async def process_websocket_event(self, _spin: Spin) -> int:
        """Reconcile persisted history before accepting a live notification.

        The collector stores a result before publishing it on Redis/WebSocket.
        Fetching history therefore fills any missed events in causal order.
        The socket payload is deliberately only a low-latency notification;
        persisted history remains the single ingestion source, so a delayed
        retransmission can never be appended out of order.
        """

        async with self._reconcile_lock:
            return await self._reconcile_locked()

    async def _mark_websocket_connected(self) -> None:
        self._ws_connected = True
        try:
            # Close the startup/reconnect gap before a live suggestion can be
            # exposed as healthy. Events published before the subscription are
            # recovered from persisted history here.
            await self.reconcile()
        except Exception as exc:
            self._ws_connected = False
            await self._persist_health(status="degraded", error=str(exc))
            raise

    async def _maintenance_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self.reconcile_interval_seconds
                )
                break
            except asyncio.TimeoutError:
                pass
            try:
                await self.reconcile()
            except Exception as exc:  # keep the live stream alive
                LOGGER.exception("history reconciliation failed")
                await self._persist_health(status="degraded", error=str(exc))

    async def run_forever(self) -> None:
        await self.initialize()
        maintenance = asyncio.create_task(self._maintenance_loop())
        delay = 1.0
        try:
            while not self._stop.is_set():
                try:
                    self._ws_connected = False
                    await self._persist_health(
                        status="degraded",
                        error="websocket_connecting",
                    )
                    async for spin in self.source.websocket_events(
                        on_connected=self._mark_websocket_connected
                    ):
                        if self._stop.is_set():
                            break
                        await self.process_websocket_event(spin)
                    if not self._stop.is_set():
                        raise ConnectionError("websocket encerrado")
                    delay = 1.0
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._ws_connected = False
                    LOGGER.warning("websocket unavailable: %s", exc)
                    await self._persist_health(status="degraded", error=str(exc))
                    try:
                        await self.reconcile()
                    except Exception as reconcile_exc:
                        LOGGER.warning("reconciliation unavailable: %s", reconcile_exc)
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=delay)
                    except asyncio.TimeoutError:
                        pass
                    delay = min(delay * 2.0, 30.0)
        finally:
            self._stop.set()
            maintenance.cancel()
            with suppress(asyncio.CancelledError):
                await maintenance
            self._ws_connected = False
            if self.engine is not None:
                try:
                    await self._persist_health(status="stopped")
                except Exception:
                    LOGGER.warning("could not persist stopped health", exc_info=True)
            try:
                await self.store.close()
            except Exception:
                LOGGER.warning("could not close Redis cleanly", exc_info=True)

    def stop(self) -> None:
        self._stop.set()


def build_worker_from_env() -> BehaviorLabWorker:
    config = load_config()
    base_url = os.getenv("BEHAVIOR_LAB_API_BASE_URL", "https://api.revesbot.com.br")
    ws_url = os.getenv("BEHAVIOR_LAB_WS_URL") or None
    redis_url = (
        os.getenv("BEHAVIOR_LAB_REDIS_URL")
        or os.getenv("REDIS_CONNECT")
        or "redis://127.0.0.1:6379/0"
    )
    interval = float(os.getenv("BEHAVIOR_LAB_RECONCILE_INTERVAL_SECONDS", "30"))
    return BehaviorLabWorker(
        config=config,
        source=ResultAPIClient(
            base_url=base_url,
            roulette_id=config.roulette_id,
            ws_url=ws_url,
        ),
        store=RedisStateStore(config, redis_url=redis_url),
        reconcile_interval_seconds=interval,
    )


async def run_worker() -> None:
    worker = build_worker_from_env()
    await worker.run_forever()
