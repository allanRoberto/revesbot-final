from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from redis.exceptions import RedisError


REPO_ROOT = Path(__file__).resolve().parents[3]
APPS_ROOT = REPO_ROOT / "apps"
if str(APPS_ROOT) not in sys.path:
    sys.path.insert(0, str(APPS_ROOT))

from api.core.db import ensure_suggestion_snapshot_indexes  # noqa: E402
from api.core.redis_client import create_pubsub_redis_client  # noqa: E402
from api.services.suggestion_snapshot_service import (  # noqa: E402
    build_suggestion_snapshot_config_key,
    get_or_create_global_suggestion_snapshot_config,
    resolve_latest_suggestion_snapshot,
    resolve_suggestion_snapshot_by_history_id,
)


logger = logging.getLogger("suggestion_snapshot_worker")

RESULT_CHANNEL = (os.getenv("SUGGESTION_SNAPSHOT_RESULT_CHANNEL") or "new_result").strip() or "new_result"
LOG_EVERY = max(1, int(os.getenv("SUGGESTION_SNAPSHOT_LOG_EVERY", "25")))
LOG_LEVEL = (os.getenv("SUGGESTION_SNAPSHOT_LOG_LEVEL") or "INFO").upper()
DEFAULT_LOG_PATH = REPO_ROOT / "apps" / "monitoring" / "Logs" / "suggestion_snapshot_worker.log"
LOG_PATH = Path(os.getenv("SUGGESTION_SNAPSHOT_LOG_PATH") or DEFAULT_LOG_PATH)
ROULETTE_FILTER_RAW = os.getenv("SUGGESTION_SNAPSHOT_ROULETTES") or os.getenv("SUGGESTION_SNAPSHOT_ROULETTE_IDS") or ""
WORKER_CONCURRENCY = max(1, int(os.getenv("SUGGESTION_SNAPSHOT_WORKER_CONCURRENCY", "4")))
QUEUE_MAXSIZE = max(0, int(os.getenv("SUGGESTION_SNAPSHOT_QUEUE_SIZE", "500")))


def _parse_roulette_allowlist(raw_value: str) -> set[str]:
    if not raw_value:
        return set()
    return {
        str(item).strip()
        for item in raw_value.split(",")
        if str(item).strip()
    }


ROULETTE_ALLOWLIST = _parse_roulette_allowlist(ROULETTE_FILTER_RAW)


def _configure_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    logger.handlers.clear()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger.propagate = False


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        parsed = int(str(value).strip())
    except Exception:
        return None
    return parsed


def _parse_result_message(raw_data: Any) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    roulette_id = str(payload.get("slug") or payload.get("roulette_id") or "").strip()
    if not roulette_id:
        return None
    result_number = _coerce_int(payload.get("result"))
    if result_number is None or not (0 <= result_number <= 36):
        return None
    full_result = payload.get("full_result") if isinstance(payload.get("full_result"), dict) else {}
    history_id = str(
        full_result.get("_id")
        or payload.get("history_id")
        or payload.get("_id")
        or ""
    ).strip()
    return {
        "roulette_id": roulette_id,
        "result_number": result_number,
        "history_id": history_id,
    }


def _build_inflight_key(parsed: dict[str, Any]) -> str:
    roulette_id = str(parsed.get("roulette_id") or "").strip()
    history_id = str(parsed.get("history_id") or "").strip()
    result_number = parsed.get("result_number")
    if history_id:
        return f"{roulette_id}|history:{history_id}"
    return f"{roulette_id}|latest:{result_number}"


async def _process_snapshot_message(
    *,
    parsed: dict[str, Any],
    counters: dict[str, int],
) -> None:
    roulette_id = str(parsed.get("roulette_id") or "").strip()
    result_number = int(parsed.get("result_number"))
    history_id = str(parsed.get("history_id") or "").strip()
    try:
        if history_id:
            snapshot = await resolve_suggestion_snapshot_by_history_id(
                roulette_id=roulette_id,
                history_id=history_id,
                take=37,
                source="worker_live",
                create_if_missing=True,
            )
            resolver = "history_id"
        else:
            snapshot = await resolve_latest_suggestion_snapshot(
                roulette_id=roulette_id,
                take=37,
                source="worker_live",
            )
            resolver = "latest_fallback"

        snapshot_meta = snapshot.get("snapshot") or {}
        result_payload = snapshot.get("result") or {}
        ranking = (
            result_payload.get("simple_payload", {}).get("ordered_suggestion")
            or result_payload.get("simple_suggestion")
            or []
        )
        cache_status = str(snapshot_meta.get("cache_status") or "hit")
        if cache_status == "created":
            counters["created"] += 1
        else:
            counters["hit"] += 1
        logger.info(
            "Snapshot %s | resolver=%s | roulette=%s | result=%s | history_id=%s | anchor=%s | anchor_history_id=%s | snapshot_id=%s | ranking=%s | created=%s | hit=%s | invalid=%s | skipped=%s | queued=%s | processed=%s",
            cache_status,
            resolver,
            roulette_id,
            result_number,
            history_id or "-",
            snapshot_meta.get("anchor_number"),
            snapshot_meta.get("anchor_history_id"),
            snapshot_meta.get("snapshot_id"),
            len(ranking),
            counters["created"],
            counters["hit"],
            counters["invalid"],
            counters["skipped"],
            counters["queued"],
            counters["processed"],
        )
    except Exception as exc:
        logger.exception("Falha ao gerar snapshot live para %s: %s", roulette_id, exc)


async def _worker_loop(
    *,
    worker_id: int,
    queue: asyncio.Queue[dict[str, Any] | None],
    counters: dict[str, int],
    inflight: set[str],
) -> None:
    while True:
        parsed = await queue.get()
        if parsed is None:
            queue.task_done()
            return

        inflight_key = _build_inflight_key(parsed)
        try:
            await _process_snapshot_message(parsed=parsed, counters=counters)
        finally:
            counters["processed"] += 1
            inflight.discard(inflight_key)
            if counters["processed"] % LOG_EVERY == 0:
                logger.info(
                    "Resumo worker | workers=%s | queued=%s | processed=%s | created=%s | hit=%s | invalid=%s | skipped=%s | queue_size=%s",
                    WORKER_CONCURRENCY,
                    counters["queued"],
                    counters["processed"],
                    counters["created"],
                    counters["hit"],
                    counters["invalid"],
                    counters["skipped"],
                    queue.qsize(),
                )
            queue.task_done()


async def run_worker() -> None:
    _configure_logging()
    await ensure_suggestion_snapshot_indexes()
    config_doc = await get_or_create_global_suggestion_snapshot_config()
    config_key = build_suggestion_snapshot_config_key(config_doc)
    client = create_pubsub_redis_client()
    pubsub = client.pubsub()
    await pubsub.subscribe(RESULT_CHANNEL)
    logger.info(
        "Suggestion snapshot worker iniciado | channel=%s | log=%s | config_id=%s | config_key=%s | history_limit=%s | ranking=%s | workers=%s | queue_maxsize=%s | roulette_filter=%s",
        RESULT_CHANNEL,
        str(LOG_PATH),
        config_doc.get("config_id"),
        config_key,
        config_doc.get("history_limit"),
        37,
        WORKER_CONCURRENCY,
        QUEUE_MAXSIZE,
        ",".join(sorted(ROULETTE_ALLOWLIST)) if ROULETTE_ALLOWLIST else "ALL",
    )

    counters = {
        "messages": 0,
        "invalid": 0,
        "skipped": 0,
        "created": 0,
        "hit": 0,
        "queued": 0,
        "processed": 0,
    }
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
    inflight: set[str] = set()
    workers = [
        asyncio.create_task(
            _worker_loop(
                worker_id=index + 1,
                queue=queue,
                counters=counters,
                inflight=inflight,
            )
        )
        for index in range(WORKER_CONCURRENCY)
    ]

    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue

            counters["messages"] += 1
            parsed = _parse_result_message(message.get("data"))
            if not parsed:
                counters["invalid"] += 1
                if counters["invalid"] <= 5 or counters["invalid"] % LOG_EVERY == 0:
                    logger.warning(
                        "Payload ignorado | invalid=%s | total_messages=%s | raw=%r",
                        counters["invalid"],
                        counters["messages"],
                        message.get("data"),
                    )
                continue

            roulette_id = str(parsed.get("roulette_id") or "").strip()
            if ROULETTE_ALLOWLIST and roulette_id not in ROULETTE_ALLOWLIST:
                counters["skipped"] += 1
                if counters["skipped"] <= 5 or counters["skipped"] % LOG_EVERY == 0:
                    logger.info(
                        "Payload ignorado por filtro de roleta | roulette=%s | skipped=%s | total_messages=%s",
                        roulette_id,
                        counters["skipped"],
                        counters["messages"],
                    )
                continue
            inflight_key = _build_inflight_key(parsed)
            if inflight_key in inflight:
                counters["skipped"] += 1
                if counters["skipped"] <= 5 or counters["skipped"] % LOG_EVERY == 0:
                    logger.info(
                        "Payload ignorado por duplicidade em voo | key=%s | skipped=%s | total_messages=%s",
                        inflight_key,
                        counters["skipped"],
                        counters["messages"],
                    )
                continue
            inflight.add(inflight_key)
            await queue.put(parsed)
            counters["queued"] += 1
    except RedisError as exc:
        logger.error("Suggestion snapshot worker interrompido pelo Redis: %s", exc)
        raise
    finally:
        for _ in workers:
            await queue.put(None)
        await queue.join()
        for task in workers:
            with contextlib.suppress(Exception):
                await task
        try:
            await pubsub.close()
        except Exception:
            pass
        try:
            await client.close()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(run_worker())
