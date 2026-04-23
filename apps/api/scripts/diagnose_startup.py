from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict

import httpx


REPO_ROOT = Path(__file__).resolve().parents[3]
APPS_ROOT = REPO_ROOT / "apps"
if str(APPS_ROOT) not in sys.path:
    sys.path.insert(0, str(APPS_ROOT))


def _now_ms() -> float:
    return time.perf_counter() * 1000.0


def _duration_ms(start_ms: float) -> float:
    return round((_now_ms() - start_ms), 2)


def _measure_fresh_import() -> Dict[str, Any]:
    code = (
        "import json, sys, time; "
        f"sys.path.insert(0, {str(APPS_ROOT)!r}); "
        "start = time.perf_counter(); "
        "import api.main; "
        "print(json.dumps({'import_api_main_ms': round((time.perf_counter()-start)*1000, 2)}))"
    )
    started_at = _now_ms()
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    payload: Dict[str, Any] = {
        "subprocess_elapsed_ms": _duration_ms(started_at),
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }
    if result.returncode == 0:
        try:
            payload.update(json.loads(result.stdout.strip()))
        except Exception as exc:  # pragma: no cover - diagnostic only
            payload["parse_error"] = str(exc)
    return payload


async def _measure_runtime_probes(roulette_id: str, config_key: str | None) -> Dict[str, Any]:
    runtime: Dict[str, Any] = {}

    import_started = _now_ms()
    from api.main import app
    from api.core.db import ensure_suggestion_monitor_indexes, history_coll, mongo_db

    runtime["warm_import_api_main_ms"] = _duration_ms(import_started)

    ping_started = _now_ms()
    try:
        ping_result = await asyncio.wait_for(mongo_db.command("ping"), timeout=15)
        runtime["mongo_ping_ms"] = _duration_ms(ping_started)
        runtime["mongo_ping_ok"] = bool(ping_result.get("ok"))
    except Exception as exc:  # pragma: no cover - diagnostic only
        runtime["mongo_ping_ms"] = _duration_ms(ping_started)
        runtime["mongo_ping_error"] = str(exc)

    first_query_started = _now_ms()
    try:
        latest_doc = await asyncio.wait_for(
            history_coll.find_one(
                {"roulette_id": roulette_id},
                {"_id": 1, "value": 1, "timestamp": 1, "roulette_id": 1},
                sort=[("timestamp", -1)],
            ),
            timeout=15,
        )
        runtime["mongo_first_query_ms"] = _duration_ms(first_query_started)
        runtime["mongo_first_query_found"] = latest_doc is not None
        if latest_doc is not None:
            runtime["mongo_first_query_preview"] = {
                "roulette_id": latest_doc.get("roulette_id"),
                "value": latest_doc.get("value"),
            }
    except Exception as exc:  # pragma: no cover - diagnostic only
        runtime["mongo_first_query_ms"] = _duration_ms(first_query_started)
        runtime["mongo_first_query_error"] = str(exc)

    indexes_started = _now_ms()
    try:
        await asyncio.wait_for(ensure_suggestion_monitor_indexes(), timeout=20)
        runtime["ensure_monitor_indexes_ms"] = _duration_ms(indexes_started)
        runtime["ensure_monitor_indexes_ok"] = True
    except Exception as exc:  # pragma: no cover - diagnostic only
        runtime["ensure_monitor_indexes_ms"] = _duration_ms(indexes_started)
        runtime["ensure_monitor_indexes_error"] = str(exc)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://diagnostic.local") as client:
        roulettes_started = _now_ms()
        try:
            response = await asyncio.wait_for(client.get("/api/roulettes"), timeout=20)
            runtime["route_api_roulettes_ms"] = _duration_ms(roulettes_started)
            runtime["route_api_roulettes_status"] = response.status_code
            payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else None
            runtime["route_api_roulettes_items"] = len(payload) if isinstance(payload, list) else None
        except Exception as exc:  # pragma: no cover - diagnostic only
            runtime["route_api_roulettes_ms"] = _duration_ms(roulettes_started)
            runtime["route_api_roulettes_error"] = str(exc)

        overview_started = _now_ms()
        try:
            params = {"roulette_id": roulette_id, "ranking_variant": "base"}
            if config_key:
                params["config_key"] = config_key
            response = await asyncio.wait_for(
                client.get("/api/suggestion-monitor/overview", params=params),
                timeout=20,
            )
            runtime["route_monitor_overview_ms"] = _duration_ms(overview_started)
            runtime["route_monitor_overview_status"] = response.status_code
            payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else None
            if isinstance(payload, dict):
                runtime["route_monitor_overview_total_events"] = payload.get("total_events")
                runtime["route_monitor_overview_resolved_events"] = payload.get("resolved_events")
        except Exception as exc:  # pragma: no cover - diagnostic only
            runtime["route_monitor_overview_ms"] = _duration_ms(overview_started)
            runtime["route_monitor_overview_error"] = str(exc)

    return runtime


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Diagnostica tempo de boot e primeiro acesso da API.")
    parser.add_argument("--roulette-id", default="pragmatic-auto-roulette")
    parser.add_argument("--config-key", default=None)
    args = parser.parse_args()

    result = {
        "python": sys.executable,
        "cwd": str(REPO_ROOT),
        "roulette_id": args.roulette_id,
        "config_key": args.config_key,
        "fresh_import": _measure_fresh_import(),
        "runtime": await _measure_runtime_probes(args.roulette_id, args.config_key),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
