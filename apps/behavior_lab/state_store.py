from __future__ import annotations

import inspect
import json
import os
from collections.abc import Mapping
from typing import Any

from .config import BehaviorLabConfig
from .contracts import utc_now_iso
from .engine import BehaviorEngine


class RedisStateStore:
    """Owns only derived keys under ``behavior_lab:v1``."""

    def __init__(
        self,
        config: BehaviorLabConfig,
        *,
        redis_url: str | None = None,
        redis_client: Any = None,
    ) -> None:
        self.config = config
        self._client = redis_client
        self._redis_url = redis_url
        self._owns_client = redis_client is None

    @property
    def keys(self) -> dict[str, str]:
        prefix = self.config.redis_prefix
        return {
            "state": f"{prefix}:state",
            "snapshot": f"{prefix}:snapshot",
            "signals": f"{prefix}:signals",
            "health": f"{prefix}:health",
        }

    async def client(self):
        if self._client is None:
            try:
                from redis.asyncio import Redis
            except ImportError as exc:  # pragma: no cover - deploy dependency guard
                raise RuntimeError("instale a dependencia redis") from exc
            selected_url = (
                self._redis_url
                or os.getenv("BEHAVIOR_LAB_REDIS_URL")
                or os.getenv("REDIS_CONNECT")
                or "redis://127.0.0.1:6379/0"
            )
            self._client = Redis.from_url(
                selected_url,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=5,
                health_check_interval=30,
            )
        return self._client

    @staticmethod
    async def _decode(value: Any) -> Any:
        if inspect.isawaitable(value):
            value = await value
        if value is None:
            return None
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        return json.loads(value)

    async def get_json(self, name: str) -> Any:
        client = await self.client()
        return await self._decode(client.get(self.keys[name]))

    async def set_json(self, name: str, value: Any) -> None:
        client = await self.client()
        result = client.set(
            self.keys[name],
            json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        )
        if inspect.isawaitable(result):
            await result

    async def load_engine(
        self,
        *,
        resolved_signal_retention: int | None = None,
        identity_retention: int | None = None,
    ) -> BehaviorEngine | None:
        raw = await self.get_json("state")
        if not raw:
            return None
        return BehaviorEngine.from_state_dict(
            raw,
            self.config,
            resolved_signal_retention=resolved_signal_retention,
            identity_retention=identity_retention,
        )

    async def save_engine(self, engine: BehaviorEngine) -> None:
        payloads = {
            "state": engine.to_state_dict(),
            "snapshot": engine.snapshot(),
            "signals": [
                signal.as_dict() for signal in engine.ledger.recent(limit=250)
            ],
        }
        client = await self.client()
        pipeline_factory = getattr(client, "pipeline", None)
        if pipeline_factory is None:
            for name, value in payloads.items():
                await self.set_json(name, value)
            return

        pipeline = pipeline_factory(transaction=True)
        for name, value in payloads.items():
            pipeline.set(
                self.keys[name],
                json.dumps(value, ensure_ascii=False, separators=(",", ":")),
            )
        result = pipeline.execute()
        if inspect.isawaitable(result):
            await result

    async def write_health(self, **fields: Any) -> dict[str, Any]:
        previous = await self.get_json("health") or {}
        health = {
            **previous,
            "version": self.config.version,
            "config_fingerprint": self.config.fingerprint,
            "roulette_id": self.config.roulette_id,
            "heartbeat_at": utc_now_iso(),
            **fields,
        }
        await self.set_json("health", health)
        return health

    async def close(self) -> None:
        if self._client is None or not self._owns_client:
            return
        close = getattr(self._client, "aclose", None) or getattr(self._client, "close", None)
        if close is not None:
            result = close()
            if inspect.isawaitable(result):
                await result
        self._client = None
