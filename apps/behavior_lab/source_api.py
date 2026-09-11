from __future__ import annotations

import inspect
import json
from collections.abc import AsyncIterator, Mapping
from typing import Any
from urllib.parse import quote, urlencode, urlparse, urlunparse

from .contracts import Spin


def history_url(base_url: str, roulette_id: str, limit: int) -> str:
    return f"{base_url.rstrip('/')}/history/{quote(roulette_id, safe='')}?{urlencode({'limit': limit})}"


def websocket_url(base_url: str, roulette_id: str) -> str:
    parsed = urlparse(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse((scheme, parsed.netloc, "/ws", "", urlencode({"slug": roulette_id}), ""))


def normalize_history_payload(payload: Any) -> list[Mapping[str, Any] | int]:
    if isinstance(payload, Mapping):
        if isinstance(payload.get("items"), list):
            return list(payload["items"])
        if isinstance(payload.get("results"), list):
            return list(payload["results"])
    if isinstance(payload, list):
        return list(payload)
    raise ValueError("resposta de historico sem lista de resultados")


class ResultAPIClient:
    def __init__(
        self,
        *,
        base_url: str,
        roulette_id: str,
        ws_url: str | None = None,
        timeout_seconds: float = 15.0,
        http_client: Any = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.roulette_id = roulette_id
        self.ws_url = ws_url or websocket_url(self.base_url, roulette_id)
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client

    async def fetch_history(self, limit: int = 500) -> list[Spin]:
        bounded = max(1, min(int(limit), 50_000))
        if self._http_client is None:
            try:
                import httpx
            except ImportError as exc:  # pragma: no cover - deploy dependency guard
                raise RuntimeError("instale a dependencia httpx") from exc
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(history_url(self.base_url, self.roulette_id, bounded))
                response.raise_for_status()
                payload = response.json()
        else:
            response = await self._http_client.get(
                history_url(self.base_url, self.roulette_id, bounded)
            )
            response.raise_for_status()
            payload = response.json()

        newest_first = normalize_history_payload(payload)
        spins = [
            Spin.from_raw(item, expected_roulette_id=self.roulette_id, source="history_api")
            for item in reversed(newest_first)
        ]
        if any(not spin.identity_keys for spin in spins):
            raise ValueError(
                "historico ao vivo precisa de items com _id ou external_game_id para reconciliacao"
            )
        return spins

    async def websocket_events(self, *, on_connected: Any = None) -> AsyncIterator[Spin]:
        """Yield one normalized event per WebSocket message.

        Reconnect/reconciliation policy intentionally remains in the worker so
        the transport can be replaced in tests.
        """

        try:
            import websockets
        except ImportError as exc:  # pragma: no cover - deploy dependency guard
            raise RuntimeError("instale a dependencia websockets") from exc

        async with websockets.connect(
            self.ws_url,
            open_timeout=self.timeout_seconds,
            ping_interval=20,
            ping_timeout=20,
        ) as socket:
            if on_connected is not None:
                callback_result = on_connected()
                if inspect.isawaitable(callback_result):
                    await callback_result
            async for raw in socket:
                payload = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
                yield Spin.from_raw(
                    payload,
                    expected_roulette_id=self.roulette_id,
                    source="websocket",
                )
