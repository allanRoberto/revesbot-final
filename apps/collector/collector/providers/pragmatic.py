from __future__ import annotations

import json
import logging
import threading
import time
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import websocket

from ..config import CollectorSettings
from ..models import RouletteResult
from ..state import CollectorState


ROULETTE_NAMES = {
    "210": "pragmatic-auto-mega-roulette", "204": "pragmatic-mega-roulette",
    "292": "pragmatic-immersive-roulette-deluxe", "213": "pragmatic-korean-roulette",
    "225": "pragmatic-auto-roulette", "201": "pragmatic-roulette-2",
    "266": "pragmatic-vip-auto-roulette", "226": "pragmatic-speed-auto-roulette",
    "230": "pragmatic-roulete-3", "203": "pragmatic-speed-roulette-1",
    "227": "pragmatic-roulette-1", "545": "pragmatic-vip-roulette",
    "208": "pragmatic-turkish-mega-roulette", "287": "pragmatic-mega-roulette-brazilian",
    "298": "pragmatic-italian-mega-roulette", "224": "pragmatic-turkish-roulette",
    "205": "pragmatic-speed-roulette-2", "233": "pragmatic-romanian-roulette",
    "234": "pragmatic-roulette-italian", "237": "pragmatic-brazilian-roulette",
    "222": "pragmatic-german-roulette", "221": "pragmatic-russian-roulette",
    "223": "pragmatic-roulette-italia-tricolore", "262": "pragmatic-vietnamese-roulette",
    "206": "pragmatic-roulette-macao",
}


class PragmaticCollector:
    websocket_url = "wss://dga.pragmaticplaylive.net/ws"

    def __init__(self, settings: CollectorSettings, repository, publisher, state: CollectorState):
        self.settings = settings
        self.repository = repository
        self.publisher = publisher
        self.state = state
        self.logger = logging.getLogger("collector.pragmatic")

    def _event_payload(self, result: RouletteResult, inserted_id: str | None) -> str:
        br_time = result.timestamp.astimezone(ZoneInfo("America/Sao_Paulo"))
        return json.dumps({
            "slug": result.roulette_id,
            "result": result.value,
            "full_result": {
                "_id": inserted_id,
                "roulette_id": result.roulette_id,
                "roulette_name": result.roulette_id,
                "external_game_id": result.external_game_id,
                "value": result.value,
                "timestamp": result.timestamp.isoformat(),
                "timestamp_br": br_time.isoformat(),
                "date": br_time.strftime("%Y-%m-%d"),
                "time": br_time.strftime("%H:%M:%S"),
                "hour": br_time.hour,
                "minute": br_time.minute,
                "day_of_week": br_time.strftime("%A"),
                "formatted": br_time.strftime("%d/%m/%Y %H:%M:%S"),
            },
        })

    def process_message(self, ws, message: str, subscription: dict[str, bool]) -> int:
        self.state.record_message()
        try:
            data = json.loads(message)
        except (TypeError, json.JSONDecodeError):
            self.state.record_invalid()
            self.logger.warning("invalid_message")
            return 0
        if isinstance(data, list):
            return sum(
                self.process_message(ws, json.dumps(item), subscription)
                for item in data if isinstance(item, dict)
            )
        if not isinstance(data, dict):
            return 0
        if isinstance(data.get("tableKey"), list) and not subscription["sent"]:
            self._send_subscribe(ws)
            subscription["sent"] = True
            return 0
        if data.get("error"):
            self.state.record_error(str(data["error"]))
            self.logger.error("subscription_error=%s", data["error"])
            return 0

        raw_table_id = data.get("tableId", data.get("key"))
        results = data.get("last20Results")
        if raw_table_id is None or not isinstance(results, list) or not results:
            return 0
        table_id = str(raw_table_id)
        roulette_id = ROULETTE_NAMES.get(table_id, f"pragmatic-table-{table_id}")
        inserted_count = 0

        # Oldest first so a reconnect backfills the snapshot in order.
        for item in reversed(results):
            if not isinstance(item, dict):
                continue
            try:
                value = int(item["result"])
            except (KeyError, TypeError, ValueError):
                self.state.record_invalid()
                continue
            raw_game_id = item.get("gameId")
            game_id = str(raw_game_id).strip() if raw_game_id is not None else ""
            if game_id and self.state.was_seen(roulette_id, game_id):
                continue
            result = RouletteResult(roulette_id, value, datetime.now(UTC), game_id or None)
            try:
                inserted, inserted_id = self.repository.insert_if_new(result)
                with self.state._lock:
                    self.state.mongo_ok = True
            except Exception as exc:
                self.state.record_mongo_error(str(exc))
                self.logger.exception("mongo_write_failed roulette_id=%s", roulette_id)
                continue
            if game_id:
                self.state.mark_seen(roulette_id, game_id)
            if not inserted:
                self.state.record_duplicate()
                continue
            self.state.record_persisted(roulette_id)
            inserted_count += 1
            try:
                self.publisher.publish(self._event_payload(result, inserted_id))
                self.state.record_published()
            except Exception as exc:
                self.state.record_redis_error(str(exc))
                self.logger.exception("redis_publish_failed roulette_id=%s", roulette_id)
            self.logger.info(
                "result_saved roulette_id=%s value=%s game_id=%s",
                roulette_id, value, game_id or "none",
            )
        return inserted_count

    def _send_subscribe(self, ws) -> None:
        ws.send(json.dumps({
            "type": "subscribe", "isDeltaEnabled": True,
            "casinoId": self.settings.casino_id,
            "key": list(self.settings.subscribe_keys), "currency": "BRL",
        }))
        self.logger.info("subscription_sent tables=%s", len(self.settings.subscribe_keys))

    def run_session(self) -> None:
        heartbeat_stop = threading.Event()
        subscription = {"sent": False}

        def application_ping(ws) -> None:
            while not heartbeat_stop.wait(15):
                try:
                    if ws.sock and ws.sock.connected:
                        ws.send(json.dumps({"type": "ping", "pingTime": str(int(time.time() * 1000))}))
                except Exception:
                    return

        def on_open(ws) -> None:
            self.state.set_connection(True)
            ws.send(json.dumps({"type": "available", "casinoId": self.settings.casino_id}))
            threading.Thread(target=application_ping, args=(ws,), name="pragmatic-ping", daemon=True).start()
            self.logger.info("websocket_open catalog_requested")

        def on_close(_ws, code, reason) -> None:
            heartbeat_stop.set()
            self.state.set_connection(False)
            self.logger.warning("websocket_closed code=%s reason=%s", code, reason)

        ws = websocket.WebSocketApp(
            self.websocket_url,
            on_open=on_open,
            on_message=lambda socket, message: self.process_message(socket, message, subscription),
            on_error=lambda _socket, error: self.state.record_error(str(error)),
            on_close=on_close,
        )
        try:
            ws.run_forever(
                ping_interval=20, ping_timeout=10, ping_payload="revesbot-keepalive",
                origin="https://client.pragmaticplaylive.net",
            )
        finally:
            heartbeat_stop.set()
            self.state.set_connection(False)

    def run_forever(self) -> None:
        attempts = 0
        while True:
            try:
                self.run_session()
                attempts += 1
            except Exception as exc:
                attempts += 1
                self.state.record_error(str(exc))
                self.logger.exception("collector_session_failed")
            self.state.record_reconnect()
            delay = min(30, 2 ** min(attempts, 5))
            self.logger.warning("reconnecting delay_seconds=%s", delay)
            time.sleep(delay)
