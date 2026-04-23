from __future__ import annotations

import json

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.exceptions import RedisError
from starlette.websockets import WebSocketState

from api.core.db import format_timestamp_br
from api.core.redis_client import create_pubsub_redis_client, r


STREAM_NEW = "streams:signals:new"
RESULT_CHANNEL_REAL = "new_result"
RESULT_CHANNEL_SIMULATION = "new_result_simulate"
_RESULT_CHANNEL_ALIASES = {
    "real": RESULT_CHANNEL_REAL,
    "live": RESULT_CHANNEL_REAL,
    RESULT_CHANNEL_REAL: RESULT_CHANNEL_REAL,
    "simulation": RESULT_CHANNEL_SIMULATION,
    "simulate": RESULT_CHANNEL_SIMULATION,
    "simulacao": RESULT_CHANNEL_SIMULATION,
    "simulação": RESULT_CHANNEL_SIMULATION,
    RESULT_CHANNEL_SIMULATION: RESULT_CHANNEL_SIMULATION,
}


router = APIRouter()
_invalid_contract_counts: dict[str, int] = {}


async def _close_async_resource(resource) -> None:
    if resource is None:
        return
    close_method = getattr(resource, "aclose", None)
    if close_method is not None:
        await close_method()
        return
    close_method = getattr(resource, "close", None)
    if close_method is not None:
        maybe_result = close_method()
        if asyncio.iscoroutine(maybe_result):
            await maybe_result


def _warn_invalid_contract(contract: str, reason: str, context: str = "") -> None:
    key = f"{contract}:{reason}"
    count = _invalid_contract_counts.get(key, 0) + 1
    _invalid_contract_counts[key] = count
    if count <= 5 or count % 100 == 0:
        ctx = f" ({context})" if context else ""
        logging.warning("[redis:%s] payload descartado: %s%s", contract, reason, ctx)


def _coerce_int_safe(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text and (text.isdigit() or (text.startswith("-") and text[1:].isdigit())):
            try:
                return int(text)
            except ValueError:
                return None
    return None


def _parse_json_object(raw_data, contract: str, context: str = ""):
    try:
        data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
    except json.JSONDecodeError:
        _warn_invalid_contract(contract, "json_invalido", context)
        return None
    if not isinstance(data, dict):
        _warn_invalid_contract(contract, "payload_nao_dict", context)
        return None
    return data


def _normalize_result_event(raw_data, contract: str):
    data = _parse_json_object(raw_data, contract)
    if not data:
        return None

    slug = data.get("slug") or data.get("roulette_id")
    if not isinstance(slug, str) or not slug.strip():
        _warn_invalid_contract(contract, "slug_ausente")
        return None
    slug = slug.strip()

    raw_result = data.get("result")
    if raw_result is None:
        raw_result = data.get("value", data.get("number"))
    result = _coerce_int_safe(raw_result)
    if result is None:
        _warn_invalid_contract(contract, "result_invalido")
        return None

    data["slug"] = slug
    data["result"] = result
    return data


def _resolve_result_channel(raw_value) -> str:
    key = str(raw_value or "").strip().lower()
    return _RESULT_CHANNEL_ALIASES.get(key, RESULT_CHANNEL_REAL)


def _normalize_stream_payload(stream_name: str, message_id: str, fields):
    if not isinstance(fields, dict):
        _warn_invalid_contract(stream_name, "envelope_nao_dict", f"id={message_id}")
        return None

    raw_data = fields.get("data")
    if raw_data is None:
        _warn_invalid_contract(stream_name, "campo_data_ausente", f"id={message_id}")
        return None

    data = _parse_json_object(raw_data, stream_name, f"id={message_id}")
    if not data:
        return None

    signal_id_raw = fields.get("signal_id")
    if signal_id_raw is None:
        signal_id_raw = data.get("id")
    signal_id = str(signal_id_raw).strip() if signal_id_raw is not None else ""
    if not signal_id:
        _warn_invalid_contract(stream_name, "signal_id_ausente", f"id={message_id}")
        return None

    status = fields.get("status", data.get("status"))
    if status is not None and not isinstance(status, str):
        _warn_invalid_contract(stream_name, "status_invalido", f"id={message_id}")
        return None

    data.setdefault("signal_id", signal_id)
    if status is not None:
        data.setdefault("status", status)

    return data


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    channel = _resolve_result_channel(websocket.query_params.get("channel"))
    await websocket.accept()
    pubsub_client = create_pubsub_redis_client()
    pubsub = pubsub_client.pubsub()
    await pubsub.subscribe(channel)
    disconnected = False
    try:
        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                data = _normalize_result_event(message.get("data"), channel)
                if not data:
                    continue
                try:
                    await websocket.send_json(data)
                except WebSocketDisconnect:
                    disconnected = True
                    break
        except RedisError as exc:
            logging.warning("[ws] Redis pubsub interrompido em %s: %s", channel, exc)
    finally:
        try:
            await _close_async_resource(pubsub)
        except Exception as exc:
            logging.warning("[ws] Falha ao fechar pubsub em %s: %s", channel, exc)
        try:
            await _close_async_resource(pubsub_client)
        except Exception as exc:
            logging.warning("[ws] Falha ao fechar cliente Redis do pubsub em %s: %s", channel, exc)
        if not disconnected and websocket.client_state != WebSocketState.DISCONNECTED:
            try:
                await websocket.close()
            except Exception:
                pass


@router.websocket("/ws/signals")
async def websocket_signals(websocket: WebSocket):
    await websocket.accept()

    logging.info("[WS-signals] WebSocket conectado")

    last_ids = {
        STREAM_NEW: "0-0",
        "streams:signals:updates": "0-0",
    }

    try:
        while True:
            try:
                results = await r.xread(
                    streams=last_ids,
                    count=10,
                    block=5000,
                )

                if not results:
                    continue

                for stream_name, messages in results:
                    for message_id, fields in messages:
                        last_ids[stream_name] = message_id

                        data = _normalize_stream_payload(stream_name, message_id, fields)
                        if not data:
                            continue

                        if stream_name == STREAM_NEW:
                            data.setdefault("type", "new_signal")
                        else:
                            data.setdefault("type", "signal_update")

                        created = data.get("created_at")
                        if created:
                            try:
                                data["created_at_formatted"] = format_timestamp_br(int(created))
                            except Exception:
                                data["created_at_formatted"] = "-"
                        else:
                            data["created_at_formatted"] = "-"

                        await websocket.send_json(data)

            except WebSocketDisconnect:
                logging.info("[WS-signals] cliente desconectou")
                break
            except Exception:
                logging.error("[WS-signals] erro no loop XREAD", exc_info=True)
                await asyncio.sleep(2)

    finally:
        try:
            await websocket.close()
        except Exception:
            pass
        logging.info("[WS-signals] conexão fechada")
