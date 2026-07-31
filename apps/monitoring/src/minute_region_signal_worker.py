from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict
from zoneinfo import ZoneInfo

import redis.asyncio as aioredis

from .core.redis_connections import get_results_redis_url
from .minute_region_signal_repo import MinuteRegionSignalRepository
from .minute_region_signal_runtime import build_signal_document


logger = logging.getLogger(__name__)
BR_TZ = ZoneInfo("America/Sao_Paulo")


def _env_int(name: str, default: int, *, minimum: int = 0, maximum: int = 1000) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


class MinuteRegionSignalWorker:
    def __init__(self, repo: MinuteRegionSignalRepository | None = None) -> None:
        self.repo = repo or MinuteRegionSignalRepository()
        self.roulette_id = os.getenv(
            "MINUTE_REGION_SIGNAL_ROULETTE_ID", "pragmatic-auto-roulette"
        ).strip() or "pragmatic-auto-roulette"
        self.training_days = _env_int("MINUTE_REGION_SIGNAL_TRAINING_DAYS", 10, minimum=1, maximum=60)
        self.window_minutes = _env_int("MINUTE_REGION_SIGNAL_WINDOW_MINUTES", 3, minimum=1, maximum=15)
        self.analysis_neighbors = _env_int("MINUTE_REGION_SIGNAL_ANALYSIS_NEIGHBORS", 3, maximum=18)
        self.centers_count = _env_int("MINUTE_REGION_SIGNAL_CENTERS_COUNT", 2, minimum=1, maximum=10)
        self.bet_neighbors = _env_int("MINUTE_REGION_SIGNAL_BET_NEIGHBORS", 3, maximum=18)
        self.previous_results_count = _env_int("MINUTE_REGION_SIGNAL_PREVIOUS_RESULTS", 5, minimum=1, maximum=20)
        self.max_attempts = _env_int("MINUTE_REGION_SIGNAL_MAX_ATTEMPTS", 10, minimum=1, maximum=50)
        self.reconcile_seconds = float(os.getenv("MINUTE_REGION_SIGNAL_RECONCILE_SECONDS", "2"))
        self.result_channel = os.getenv("RESULT_CHANNEL", "new_result").strip() or "new_result"
        self.redis_url = get_results_redis_url()

    async def generate_current_minute(self, now_utc: datetime | None = None) -> Dict[str, Any]:
        generated_at_utc = now_utc or datetime.now(timezone.utc)
        if generated_at_utc.tzinfo is None:
            generated_at_utc = generated_at_utc.replace(tzinfo=timezone.utc)
        generated_at_utc = generated_at_utc.astimezone(timezone.utc)
        signal_minute_br = generated_at_utc.astimezone(BR_TZ).replace(second=0, microsecond=0)
        signal_minute_utc = signal_minute_br.astimezone(timezone.utc)
        signal_key = f"{self.roulette_id}|{signal_minute_br.isoformat()}"

        training = await asyncio.to_thread(
            self.repo.fetch_training_days,
            roulette_id=self.roulette_id,
            signal_minute_br=signal_minute_br,
            training_days=self.training_days,
            window_minutes=self.window_minutes,
        )
        previous = await asyncio.to_thread(
            self.repo.fetch_previous_results,
            roulette_id=self.roulette_id,
            before_utc=generated_at_utc,
            limit=self.previous_results_count,
        )
        document = build_signal_document(
            roulette_id=self.roulette_id,
            signal_key=signal_key,
            signal_minute_utc=signal_minute_utc,
            signal_minute_br=signal_minute_br,
            generated_at_utc=generated_at_utc,
            training_days_source=training,
            previous_results=previous,
            training_days=self.training_days,
            window_minutes=self.window_minutes,
            analysis_neighbors=self.analysis_neighbors,
            centers_count=self.centers_count,
            bet_neighbors=self.bet_neighbors,
            max_attempts=self.max_attempts,
            previous_results_count=self.previous_results_count,
        )
        stored, created = await asyncio.to_thread(self.repo.create_signal_if_missing, document)
        if created:
            logger.info(
                "Sinal criado | minuto=%s | centros=%s | cobertura=%s | anteriores_na_regiao=%s",
                signal_minute_br.isoformat(),
                [item["value"] for item in stored.get("selected_centers", [])],
                stored.get("coverage"),
                stored.get("previous_region_hit_count"),
            )
        return stored

    async def reconcile_active_signals(self) -> int:
        active = await asyncio.to_thread(self.repo.list_active_signals, self.roulette_id)
        applied = 0
        for signal in active:
            results = await asyncio.to_thread(self.repo.fetch_results_for_signal, signal)
            current = signal
            for result in results:
                current = await asyncio.to_thread(self.repo.apply_result, current, result)
                applied += 1
        if applied:
            logger.info("Reconciliação | sinais_ativos=%s | tentativas_registradas=%s", len(active), applied)
        return applied

    async def run(self) -> None:
        await asyncio.to_thread(self.repo.ensure_indexes)
        await self.generate_current_minute()
        await self.reconcile_active_signals()

        redis_client = None
        pubsub = None
        next_redis_connect = 0.0
        logger.info(
            "Worker minuto/região ativo | roleta=%s | canal=%s | tentativas=%s | fallback_mongo=ativo",
            self.roulette_id,
            self.result_channel,
            self.max_attempts,
        )
        last_minute_key = None
        last_reconcile = 0.0

        try:
            while True:
                monotonic_now = time.monotonic()
                if pubsub is None and monotonic_now >= next_redis_connect:
                    try:
                        redis_client = aioredis.from_url(self.redis_url, decode_responses=True)
                        pubsub = redis_client.pubsub()
                        await pubsub.subscribe(self.result_channel)
                        logger.info("Redis conectado | canal=%s", self.result_channel)
                    except Exception as exc:
                        logger.warning(
                            "Redis indisponível; monitoramento continua pelo Mongo e tentará reconectar: %s",
                            exc,
                        )
                        if pubsub is not None:
                            await pubsub.close()
                        if redis_client is not None:
                            await redis_client.close()
                        pubsub = None
                        redis_client = None
                        next_redis_connect = monotonic_now + 15.0

                now_utc = datetime.now(timezone.utc)
                minute_key = now_utc.astimezone(BR_TZ).strftime("%Y-%m-%dT%H:%M")
                if minute_key != last_minute_key:
                    await self.generate_current_minute(now_utc)
                    last_minute_key = minute_key

                message = None
                if pubsub is not None:
                    try:
                        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    except Exception as exc:
                        logger.warning("Conexão Redis perdida; usando fallback Mongo: %s", exc)
                        await pubsub.close()
                        if redis_client is not None:
                            await redis_client.close()
                        pubsub = None
                        redis_client = None
                        next_redis_connect = time.monotonic() + 15.0
                else:
                    await asyncio.sleep(1.0)
                matching_result = False
                if message and message.get("type") == "message":
                    try:
                        payload = json.loads(message.get("data") or "{}")
                        matching_result = str(payload.get("slug") or "") == self.roulette_id
                    except (TypeError, ValueError, json.JSONDecodeError):
                        matching_result = False

                monotonic_now = time.monotonic()
                if matching_result or monotonic_now - last_reconcile >= self.reconcile_seconds:
                    await self.reconcile_active_signals()
                    last_reconcile = monotonic_now
        finally:
            if pubsub is not None:
                await pubsub.unsubscribe(self.result_channel)
                await pubsub.close()
            if redis_client is not None:
                await redis_client.close()


async def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    worker = MinuteRegionSignalWorker()
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
