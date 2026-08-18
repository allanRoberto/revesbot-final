from __future__ import annotations

import json
import logging
import threading
import time
from datetime import UTC, datetime, timedelta
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


def _parse_slots(raw_slots: object) -> dict[str, int | float]:
    if not isinstance(raw_slots, dict):
        return {}
    slots: dict[str, int | float] = {}
    for raw_number, raw_multiplier in raw_slots.items():
        try:
            number = int(raw_number)
        except (TypeError, ValueError):
            continue
        if not 0 <= number <= 36 or isinstance(raw_multiplier, bool):
            continue
        if not isinstance(raw_multiplier, (int, float)):
            continue
        slots[str(number)] = raw_multiplier
    return slots


def _game_id(item: dict) -> str:
    raw_game_id = item.get("gameId")
    return str(raw_game_id).strip() if raw_game_id is not None else ""


def _provider_timestamp(item: dict) -> datetime | None:
    raw_time = item.get("time")
    if not isinstance(raw_time, str) or not raw_time.strip():
        return None
    try:
        return datetime.strptime(
            raw_time.strip(), "%b %d, %Y %I:%M:%S %p"
        ).replace(tzinfo=UTC)
    except ValueError:
        return None


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
                "slots": result.slots,
                "winning_multiplier": result.winning_multiplier,
                "captured_at": (result.captured_at or result.timestamp).isoformat(),
                "recovered": result.recovered,
                "timestamp_source": result.timestamp_source,
                "timestamp_br": br_time.isoformat(),
                "date": br_time.strftime("%Y-%m-%d"),
                "time": br_time.strftime("%H:%M:%S"),
                "hour": br_time.hour,
                "minute": br_time.minute,
                "day_of_week": br_time.strftime("%A"),
                "formatted": br_time.strftime("%d/%m/%Y %H:%M:%S"),
            },
        })

    def _build_result(
        self,
        roulette_id: str,
        item: dict,
        timestamp: datetime,
        captured_at: datetime,
        recovered: bool,
        timestamp_source: str,
    ) -> RouletteResult | None:
        try:
            value = int(item["result"])
        except (KeyError, TypeError, ValueError):
            self.state.record_invalid()
            return None
        game_id = _game_id(item)
        if not game_id:
            self.state.record_invalid()
            return None
        slots = _parse_slots(item.get("slots"))
        return RouletteResult(
            roulette_id=roulette_id,
            value=value,
            timestamp=timestamp,
            external_game_id=game_id,
            slots=slots,
            winning_multiplier=slots.get(str(value)),
            captured_at=captured_at,
            recovered=recovered,
            timestamp_source=timestamp_source,
        )

    def _timestamp_for_item(
        self,
        roulette_id: str,
        item: dict,
        captured_at: datetime,
        recovered: bool,
    ) -> tuple[datetime, str]:
        provider_timestamp = _provider_timestamp(item)
        if (
            provider_timestamp is not None
            and provider_timestamp <= captured_at + timedelta(minutes=5)
        ):
            return provider_timestamp, "provider"
        game_id = _game_id(item) or "unknown"
        reason = "future" if provider_timestamp is not None else "missing_or_invalid"
        message = (
            f"provider_timestamp_unusable roulette_id={roulette_id} "
            f"game_id={game_id} recovered={recovered} reason={reason}"
        )
        if recovered:
            self.state.record_recovery_failure(message)
        else:
            self.state.record_invalid()
            self.state.record_error(message)
        self.logger.error(message)
        return captured_at, "captured_fallback"

    def _persist(self, result: RouletteResult, publish_live: bool) -> int:
        game_id = result.external_game_id or ""
        if game_id and self.state.was_seen(result.roulette_id, game_id):
            return 0
        try:
            inserted, inserted_id = self.repository.insert_if_new(result)
            with self.state._lock:
                self.state.mongo_ok = True
        except Exception as exc:
            self.state.record_mongo_error(str(exc))
            self.logger.exception("mongo_write_failed roulette_id=%s", result.roulette_id)
            return 0
        if game_id:
            self.state.mark_seen(result.roulette_id, game_id)
        if not inserted:
            self.state.record_duplicate()
            return 0
        self.state.record_persisted(result.roulette_id, recovered=result.recovered)
        if publish_live:
            try:
                self.publisher.publish(self._event_payload(result, inserted_id))
                self.state.record_published()
            except Exception as exc:
                self.state.record_redis_error(str(exc))
                self.logger.exception("redis_publish_failed roulette_id=%s", result.roulette_id)
        self.logger.info(
            "result_saved roulette_id=%s value=%s game_id=%s recovered=%s",
            result.roulette_id,
            result.value,
            game_id,
            result.recovered,
        )
        return 1

    def _reconcile_snapshot(
        self,
        roulette_id: str,
        raw_results: list,
        captured_at: datetime,
    ) -> int:
        items = [
            item
            for item in raw_results
            if isinstance(item, dict)
            and _game_id(item)
            and item.get("result") is not None
        ]
        if not items:
            return 0
        recent = self.repository.recent_results(roulette_id, limit=20)
        if not recent:
            timestamp, source = self._timestamp_for_item(
                roulette_id, items[0], captured_at, recovered=False
            )
            result = self._build_result(
                roulette_id,
                items[0],
                timestamp,
                captured_at,
                recovered=False,
                timestamp_source=source,
            )
            return self._persist(result, publish_live=True) if result else 0

        stored_by_id = {
            str(item["external_game_id"]): item
            for item in recent
            if item.get("external_game_id")
        }
        overlap_index = next(
            (index for index, item in enumerate(items) if _game_id(item) in stored_by_id),
            None,
        )
        if overlap_index is None:
            missing_oldest_first = list(reversed(items))
            message = (
                f"recovery_window_exhausted roulette_id={roulette_id} "
                f"available_results={len(missing_oldest_first)}"
            )
            self.state.record_recovery_failure(message)
            self.logger.critical(message)
        else:
            missing_oldest_first = list(reversed(items[:overlap_index]))
            if not missing_oldest_first:
                return 0

        inserted = 0
        for item in missing_oldest_first:
            timestamp, source = self._timestamp_for_item(
                roulette_id, item, captured_at, recovered=True
            )
            result = self._build_result(
                roulette_id,
                item,
                timestamp,
                captured_at,
                recovered=True,
                timestamp_source=source,
            )
            if result:
                inserted += self._persist(result, publish_live=False)
        if inserted:
            self.logger.warning(
                "recovery_completed roulette_id=%s recovered=%s",
                roulette_id,
                inserted,
            )
        return inserted

    def process_message(self, ws, message: str, subscription: dict[str, object]) -> int:
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
        if raw_table_id is None:
            return 0
        table_id = str(raw_table_id)
        if table_id not in self.settings.subscribe_keys:
            return 0
        verified_tables = subscription.setdefault("verified_roulette_tables", set())
        if not isinstance(verified_tables, set):
            verified_tables = set()
            subscription["verified_roulette_tables"] = verified_tables
        table_type = data.get("tableType")
        if table_type is not None:
            if table_type != "ROULETTE":
                return 0
            verified_tables.add(table_id)
        elif table_id not in verified_tables:
            return 0
        results = data.get("last20Results")
        if not isinstance(results, list) or not results:
            return 0
        roulette_id = ROULETTE_NAMES.get(table_id, f"pragmatic-table-{table_id}")
        captured_at = datetime.now(UTC)
        reconciled_tables = subscription.setdefault("reconciled_tables", set())
        if not isinstance(reconciled_tables, set):
            reconciled_tables = set()
            subscription["reconciled_tables"] = reconciled_tables
        if roulette_id not in reconciled_tables:
            try:
                inserted = self._reconcile_snapshot(roulette_id, results, captured_at)
            except Exception as exc:
                self.state.record_mongo_error(str(exc))
                self.logger.exception("snapshot_reconciliation_failed roulette_id=%s", roulette_id)
                return 0
            reconciled_tables.add(roulette_id)
            return inserted

        newest = next(
            (
                item
                for item in results
                if isinstance(item, dict) and item.get("result") is not None
            ),
            None,
        )
        if newest is None:
            return 0
        result = self._build_result(
            roulette_id,
            newest,
            captured_at,
            captured_at,
            recovered=False,
            timestamp_source="captured",
        )
        return self._persist(result, publish_live=True) if result else 0

    def _send_subscribe(self, ws) -> None:
        ws.send(json.dumps({
            "type": "subscribe", "isDeltaEnabled": True,
            "casinoId": self.settings.casino_id,
            "key": list(self.settings.subscribe_keys), "currency": "BRL",
        }))
        self.logger.info("subscription_sent tables=%s", len(self.settings.subscribe_keys))

    def run_session(self) -> None:
        heartbeat_stop = threading.Event()
        subscription: dict[str, object] = {"sent": False, "reconciled_tables": set()}

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
