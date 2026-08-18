from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.exceptions import RedisError
from starlette.websockets import WebSocketState

from api.core.redis_client import create_pubsub_redis_client


router = APIRouter()
RESULT_CHANNEL = "new_result"


def normalize_result_event(raw_data):
    try:
        data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    slug = data.get("slug") or data.get("roulette_id")
    if not isinstance(slug, str) or not slug.strip():
        return None
    raw_result = data.get("result", data.get("value", data.get("number")))
    if isinstance(raw_result, bool):
        return None
    try:
        result = int(raw_result)
    except (TypeError, ValueError):
        return None
    if not 0 <= result <= 36:
        return None
    data["slug"] = slug.strip()
    data["result"] = result
    return data


async def _close(resource) -> None:
    if resource is None:
        return
    close_method = getattr(resource, "aclose", None) or getattr(resource, "close", None)
    if close_method is None:
        return
    result = close_method()
    if asyncio.iscoroutine(result):
        await result


@router.websocket("/ws")
async def results_websocket(websocket: WebSocket) -> None:
    requested_slug = str(websocket.query_params.get("slug") or "").strip()
    await websocket.accept()
    client = create_pubsub_redis_client()
    pubsub = client.pubsub()
    disconnected = False
    try:
        await pubsub.subscribe(RESULT_CHANNEL)
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            event = normalize_result_event(message.get("data"))
            if event is None or (requested_slug and event["slug"] != requested_slug):
                continue
            try:
                await websocket.send_json(event)
            except WebSocketDisconnect:
                disconnected = True
                break
    except RedisError as exc:
        logging.warning("[results-ws] Redis interrompido: %s", exc)
    finally:
        await _close(pubsub)
        await _close(client)
        if not disconnected and websocket.client_state != WebSocketState.DISCONNECTED:
            try:
                await websocket.close()
            except Exception:
                pass
