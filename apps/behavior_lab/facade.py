from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .backtest import replay
from .config import BehaviorLabConfig, load_config as _load_config
from .state_store import RedisStateStore


def load_config(path: str | Path | None = None) -> BehaviorLabConfig:
    return _load_config(path)


def run_backtest(
    events: Sequence[int | Mapping[str, Any]],
    *,
    config: BehaviorLabConfig | None = None,
    input_order: str = "chronological",
    include_decisions: bool = True,
    include_signals: bool = True,
) -> dict[str, Any]:
    return replay(
        events,
        config=config or load_config(),
        input_order=input_order,
        include_decisions=include_decisions,
        include_signals=include_signals,
    )


def _empty_snapshot(config: BehaviorLabConfig) -> dict[str, Any]:
    return {
        "version": config.version,
        "config_fingerprint": config.fingerprint,
        "roulette_id": config.roulette_id,
        "processed_count": 0,
        "state_revision": 0,
        "context_size": 0,
        "last_result": None,
        "suggestion": [],
        "decision": "NO_BET",
        "reason": "worker_state_unavailable",
        "active_signals": [],
        "generated_at": None,
    }


def _health_with_freshness(
    raw: Mapping[str, Any] | None,
    config: BehaviorLabConfig,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    payload = dict(raw or {})
    heartbeat_at = payload.get("heartbeat_at")
    age_seconds: float | None = None
    if heartbeat_at:
        try:
            heartbeat = datetime.fromisoformat(str(heartbeat_at).replace("Z", "+00:00"))
            if heartbeat.tzinfo is None:
                heartbeat = heartbeat.replace(tzinfo=timezone.utc)
            current = now or datetime.now(timezone.utc)
            age_seconds = (
                current.astimezone(timezone.utc) - heartbeat.astimezone(timezone.utc)
            ).total_seconds()
        except (TypeError, ValueError):
            age_seconds = None

    try:
        max_age = max(
            1,
            int(os.getenv("BEHAVIOR_LAB_HEARTBEAT_MAX_AGE_SECONDS", "90")),
        )
    except ValueError:
        max_age = 90
    fresh = age_seconds is not None and -30 <= age_seconds <= max_age
    expected_release = os.getenv("BEHAVIOR_LAB_RELEASE_ID")
    release_matches = (
        expected_release is None or payload.get("release_id") == expected_release
    )

    payload.setdefault("roulette_id", config.roulette_id)
    payload.setdefault("version", config.version)
    payload.setdefault("config_fingerprint", config.fingerprint)
    payload.setdefault("heartbeat_at", None)
    payload.setdefault("last_event_at", None)
    payload.setdefault("ws_connected", False)
    payload.setdefault("processed_count", 0)
    payload.setdefault("state_revision", payload["processed_count"])
    payload.setdefault("active_signals", 0)
    payload.setdefault("error", "worker_state_unavailable" if not raw else None)
    payload.setdefault("status", "unavailable")
    payload["fresh"] = fresh
    payload["release_matches"] = release_matches
    payload["heartbeat_age_seconds"] = (
        round(max(0.0, age_seconds), 3) if age_seconds is not None else None
    )
    if raw and not fresh:
        payload["reported_status"] = payload["status"]
        payload["status"] = "stale"
        payload["error"] = "worker_heartbeat_stale"
    elif raw and not release_matches:
        payload["reported_status"] = payload["status"]
        payload["status"] = "stale_release"
        payload["error"] = "worker_release_mismatch"
    return payload


async def read_live_state(
    *,
    redis_url: str | None = None,
    redis_client: Any = None,
    config: BehaviorLabConfig | None = None,
) -> dict[str, Any]:
    selected = config or load_config()
    store = RedisStateStore(selected, redis_url=redis_url, redis_client=redis_client)
    try:
        snapshot = await store.get_json("snapshot")
        raw_health = await store.get_json("health")
    finally:
        await store.close()
    health = _health_with_freshness(raw_health, selected)
    result = dict(snapshot or _empty_snapshot(selected))
    state_revision = result.get("state_revision", result.get("processed_count"))
    health_revision = health.get("state_revision", health.get("processed_count"))
    revisions_match = state_revision == health_revision
    ready = (
        health["fresh"]
        and health["status"] == "healthy"
        and health["ws_connected"] is True
        and revisions_match
    )
    if not ready:
        result["suggestion"] = []
        result["decision"] = "NO_BET"
        result["active_signals"] = []
        if not raw_health:
            result["reason"] = "worker_state_unavailable"
        elif not health["fresh"]:
            result["reason"] = "worker_state_stale"
        elif not revisions_match:
            result["reason"] = "worker_state_lagging"
        else:
            result["reason"] = "worker_not_ready"
    result["worker"] = health
    return result


async def read_signals(
    *,
    limit: int = 50,
    status: str | None = None,
    redis_url: str | None = None,
    redis_client: Any = None,
    config: BehaviorLabConfig | None = None,
) -> dict[str, Any]:
    selected = config or load_config()
    safe_limit = max(1, min(int(limit), 250))
    allowed_statuses = {None, "active", "won", "lost", "censored"}
    if status not in allowed_statuses:
        raise ValueError("status invalido")
    store = RedisStateStore(selected, redis_url=redis_url, redis_client=redis_client)
    try:
        rows = await store.get_json("signals") or []
    finally:
        await store.close()
    if status:
        rows = [row for row in rows if row.get("status") == status]
    rows = rows[:safe_limit]
    return {"roulette_id": selected.roulette_id, "signals": rows, "count": len(rows)}


async def read_health(
    *,
    redis_url: str | None = None,
    redis_client: Any = None,
    config: BehaviorLabConfig | None = None,
) -> dict[str, Any]:
    selected = config or load_config()
    store = RedisStateStore(selected, redis_url=redis_url, redis_client=redis_client)
    try:
        raw = await store.get_json("health")
    finally:
        await store.close()
    return _health_with_freshness(raw, selected)
