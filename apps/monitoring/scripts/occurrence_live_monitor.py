from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
from datetime import datetime, timezone
from typing import Any, Dict, List
from urllib.parse import urlencode, urlparse, urlunparse
from uuid import uuid4

import aiohttp
import certifi
from dotenv import load_dotenv
from pymongo import MongoClient


RUNS_COLL_NAME = "occurrence_analysis_runs"
EVENTS_COLL_NAME = "occurrence_analysis_events"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _build_client_kwargs(mongo_url: str) -> Dict[str, Any]:
    lowered = mongo_url.lower()
    tls_enabled = mongo_url.startswith("mongodb+srv://") or (
        "localhost" not in lowered
        and "127.0.0.1" not in lowered
        and "::1" not in lowered
    )
    kwargs: Dict[str, Any] = {}
    if tls_enabled:
        kwargs["tls"] = True
        kwargs["tlsCAFile"] = certifi.where()
    return kwargs


def _build_ws_url(base_url: str, channel: str) -> str:
    parsed = urlparse(base_url.rstrip("/"))
    scheme = "wss" if parsed.scheme == "https" else "ws"
    query = urlencode({"channel": channel})
    return urlunparse((scheme, parsed.netloc, "/ws", "", query, ""))


def _normalize_history(raw_history: List[Any], limit: int) -> List[int]:
    normalized: List[int] = []
    safe_limit = max(1, min(50_000, int(limit)))
    for raw in raw_history:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if 0 <= value <= 36:
            normalized.append(value)
        if len(normalized) >= safe_limit:
            break
    return normalized


def _extract_backlog(current_history: List[int], fresh_history: List[int], max_backlog: int) -> List[int]:
    if not current_history:
        return []
    if fresh_history[: len(current_history)] == current_history[: len(fresh_history)]:
        return []

    anchor = current_history[: min(20, len(current_history))]
    if anchor:
        for offset in range(0, len(fresh_history) - len(anchor) + 1):
            if fresh_history[offset: offset + len(anchor)] == anchor:
                backlog = list(reversed(fresh_history[:offset]))
                if len(backlog) > max_backlog:
                    return backlog[-max_backlog:]
                return backlog

    current_head = current_history[0]
    for offset, value in enumerate(fresh_history):
        if value == current_head:
            backlog = list(reversed(fresh_history[:offset]))
            if len(backlog) > max_backlog:
                return backlog[-max_backlog:]
            return backlog
    return []


class OccurrenceLiveMonitor:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.base_url = str(args.api_base_url).rstrip("/")
        self.ws_url = _build_ws_url(self.base_url, "new_result")
        self.roulette_id = str(args.slug).strip()
        self.history_limit = max(1, min(50_000, int(args.history_limit)))
        self.window_before = max(0, min(100, int(args.window_before)))
        self.window_after = max(0, min(100, int(args.window_after)))
        self.ranking_size = max(1, min(37, int(args.ranking_size)))
        self.attempts_window = max(1, min(100, int(args.attempts_window)))
        self.invert_check_window = max(0, min(100, int(args.invert_check_window)))
        self.max_backlog = max(1, min(1000, int(args.max_backlog)))
        self.mongo_url = str(args.mongo_url or "").strip()
        self.mongo_db_name = str(args.mongo_db or "roleta_db").strip() or "roleta_db"
        self.persist = bool(args.persist)
        self.history_desc: List[int] = []
        self.pending_events: Dict[str, Dict[str, Any]] = {}
        self.session: aiohttp.ClientSession | None = None
        self.mongo_client: MongoClient | None = None
        self.mongo_db = None
        self.runs_coll = None
        self.events_coll = None
        self.run_id = str(uuid4())
        self.run_created_at = _utcnow()
        self.generated_events = 0
        self.resolved_events = 0
        self.cancelled_inverted_events = 0
        self.events_with_hits = 0
        self.total_hits = 0
        self.total_attempts = 0
        self.first_hit_distribution: Dict[str, int] = {}
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        timeout = aiohttp.ClientTimeout(total=max(5.0, float(self.args.http_timeout)))
        self.session = aiohttp.ClientSession(timeout=timeout)
        if self.persist:
            self.mongo_client = MongoClient(self.mongo_url, **_build_client_kwargs(self.mongo_url))
            self.mongo_db = self.mongo_client[self.mongo_db_name]
            self.runs_coll = self.mongo_db[RUNS_COLL_NAME]
            self.events_coll = self.mongo_db[EVENTS_COLL_NAME]
            self._ensure_indexes()
            self._create_run_doc()

        self.history_desc = await self._fetch_history()
        logging.info(
            "Occurrence live monitor bootstrap | roulette=%s | history=%s | route=%s | ws=%s",
            self.roulette_id,
            len(self.history_desc),
            f"{self.base_url}/api/occurrences/ranking",
            self.ws_url,
        )

        try:
            await self._listen_forever()
        finally:
            await self._close()

    async def _close(self) -> None:
        if self.persist and self.runs_coll is not None:
            self.runs_coll.update_one(
                {"run_id": self.run_id},
                {
                    "$set": {
                        "status": "stopped" if self._stop_event.is_set() else "finished",
                        "updated_at_utc": _utcnow(),
                        "entries_processed": self.generated_events,
                        "generated_events": self.generated_events,
                        "resolved_events": self.resolved_events,
                        "pending_events": len(self.pending_events),
                        "eligible_entries": self.generated_events - self.cancelled_inverted_events,
                        "cancelled_inverted_events": self.cancelled_inverted_events,
                        "entries_analyzed": self.resolved_events,
                        "events_with_hits": self.events_with_hits,
                        "total_hits": self.total_hits,
                        "total_attempts": self.total_attempts,
                        "aggregate_hit_rate": self._aggregate_hit_rate(),
                        "event_hit_rate": self._event_hit_rate(),
                        "avg_hits_per_event": self._avg_hits_per_event(),
                        "first_hit_distribution": dict(self.first_hit_distribution),
                    }
                },
            )
        if self.session is not None:
            await self.session.close()
        if self.mongo_client is not None:
            self.mongo_client.close()

    def stop(self) -> None:
        self._stop_event.set()

    def _ensure_indexes(self) -> None:
        if self.runs_coll is None or self.events_coll is None:
            return
        self.runs_coll.create_index("run_id", unique=True, name="occ_runs_run_id")
        self.runs_coll.create_index(
            [("roulette_id", 1), ("created_at_utc", -1)],
            name="occ_runs_roulette_created_desc",
        )
        self.events_coll.create_index("event_id", unique=True, name="occ_events_event_id")
        self.events_coll.create_index(
            [("run_id", 1), ("created_at_utc", -1)],
            name="occ_events_run_created_desc",
        )
        self.events_coll.create_index(
            [("roulette_id", 1), ("status", 1), ("created_at_utc", -1)],
            name="occ_events_roulette_status_created_desc",
        )

    def _create_run_doc(self) -> None:
        if self.runs_coll is None:
            return
        self.runs_coll.insert_one(
            {
                "run_id": self.run_id,
                "roulette_id": self.roulette_id,
                "mode": "live",
                "status": "running",
                "config": {
                    "history_limit": self.history_limit,
                    "window_before": self.window_before,
                    "window_after": self.window_after,
                    "ranking_size": self.ranking_size,
                    "attempts_window": self.attempts_window,
                    "invert_check_window": self.invert_check_window,
                    "api_base_url": self.base_url,
                    "ws_url": self.ws_url,
                },
                "history_size": len(self.history_desc),
                "entries_processed": 0,
                "entries_analyzed": 0,
                "eligible_entries": 0,
                "cancelled_inverted_events": 0,
                "events_with_hits": 0,
                "total_hits": 0,
                "total_attempts": 0,
                "aggregate_hit_rate": 0.0,
                "event_hit_rate": 0.0,
                "avg_hits_per_event": 0.0,
                "first_hit_distribution": {},
                "generated_events": 0,
                "resolved_events": 0,
                "pending_events": 0,
                "created_at_utc": self.run_created_at,
                "updated_at_utc": self.run_created_at,
            }
        )

    def _aggregate_hit_rate(self) -> float:
        if self.total_attempts <= 0:
            return 0.0
        return round(float(self.total_hits) / float(self.total_attempts), 6)

    def _event_hit_rate(self) -> float:
        if self.resolved_events <= 0:
            return 0.0
        return round(float(self.events_with_hits) / float(self.resolved_events), 6)

    def _avg_hits_per_event(self) -> float:
        if self.resolved_events <= 0:
            return 0.0
        return round(float(self.total_hits) / float(self.resolved_events), 6)

    def _flush_run_metrics(self) -> None:
        if self.runs_coll is None:
            return
        self.runs_coll.update_one(
            {"run_id": self.run_id},
            {
                "$set": {
                    "updated_at_utc": _utcnow(),
                    "history_size": len(self.history_desc),
                    "entries_processed": self.generated_events,
                    "generated_events": self.generated_events,
                    "resolved_events": self.resolved_events,
                    "pending_events": len(self.pending_events),
                    "entries_analyzed": self.resolved_events,
                    "eligible_entries": self.generated_events - self.cancelled_inverted_events,
                    "cancelled_inverted_events": self.cancelled_inverted_events,
                    "events_with_hits": self.events_with_hits,
                    "total_hits": self.total_hits,
                    "total_attempts": self.total_attempts,
                    "aggregate_hit_rate": self._aggregate_hit_rate(),
                    "event_hit_rate": self._event_hit_rate(),
                    "avg_hits_per_event": self._avg_hits_per_event(),
                    "first_hit_distribution": dict(self.first_hit_distribution),
                }
            },
        )

    async def _fetch_history(self) -> List[int]:
        if self.session is None:
            raise RuntimeError("HTTP session nao inicializada.")
        url = f"{self.base_url}/history/{self.roulette_id}?limit={self.history_limit}"
        async with self.session.get(url) as response:
            response.raise_for_status()
            payload = await response.json()
        return _normalize_history(payload.get("results", []), self.history_limit)

    async def _request_ranking(self, focus_number: int) -> Dict[str, Any]:
        if self.session is None:
            raise RuntimeError("HTTP session nao inicializada.")
        url = f"{self.base_url}/api/occurrences/ranking"
        payload = {
            "roulette_id": self.roulette_id,
            "history": list(self.history_desc[: self.history_limit]),
            "focus_number": int(focus_number),
            "from_index": 0,
            "history_limit": self.history_limit,
            "window_before": self.window_before,
            "window_after": self.window_after,
            "ranking_size": self.ranking_size,
            "attempts_window": self.attempts_window,
            "invert_check_window": self.invert_check_window,
        }
        async with self.session.post(url, json=payload) as response:
            response.raise_for_status()
            return await response.json()

    async def _listen_forever(self) -> None:
        reconnect_delay = max(1.0, float(self.args.reconnect_delay))
        while not self._stop_event.is_set():
            try:
                await self._reconcile_history_backlog()
                await self._listen_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logging.warning("Occurrence live monitor reconnecting after error: %s", exc)
                await asyncio.sleep(reconnect_delay)

    async def _reconcile_history_backlog(self) -> None:
        fresh_history = await self._fetch_history()
        backlog = _extract_backlog(self.history_desc, fresh_history, self.max_backlog)
        if backlog:
            logging.warning("Occurrence live monitor backlog detected: %s resultado(s).", len(backlog))
            for number in backlog:
                await self._consume_number(int(number), source="backlog")
        self.history_desc = fresh_history[: self.history_limit]
        self._flush_run_metrics()

    async def _listen_once(self) -> None:
        if self.session is None:
            raise RuntimeError("HTTP session nao inicializada.")
        logging.info("Occurrence live monitor connecting to %s", self.ws_url)
        async with self.session.ws_connect(self.ws_url, heartbeat=30) as websocket:
            async for message in websocket:
                if self._stop_event.is_set():
                    break
                if message.type != aiohttp.WSMsgType.TEXT:
                    continue
                try:
                    payload = json.loads(message.data)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                if str(payload.get("slug") or payload.get("roulette_id") or "").strip() != self.roulette_id:
                    continue
                try:
                    number = int(payload.get("result"))
                except (TypeError, ValueError):
                    continue
                if not (0 <= number <= 36):
                    continue
                await self._consume_number(number, source="ws")

    async def _consume_number(self, number: int, source: str) -> None:
        await self._advance_pending_events(number)
        self.history_desc.insert(0, int(number))
        if len(self.history_desc) > self.history_limit:
            self.history_desc = self.history_desc[: self.history_limit]

        ranking_payload = await self._request_ranking(int(number))
        event_id = str(uuid4())
        created_at = _utcnow()
        ranking = [int(value) for value in (ranking_payload.get("ranking") or []) if 0 <= int(value) <= 36]
        evaluation_payload = dict(ranking_payload.get("evaluation") or {})
        inverted_payload = dict(ranking_payload.get("inverted_evaluation") or {})
        event_status = str(evaluation_payload.get("status") or "pending")
        cancelled_reason = ranking_payload.get("cancelled_reason")
        counted = bool(ranking_payload.get("counted", event_status != "cancelled_inverted"))
        event_state = {
            "event_id": event_id,
            "run_id": self.run_id,
            "roulette_id": self.roulette_id,
            "mode": "live",
            "status": event_status,
            "created_at_utc": created_at,
            "updated_at_utc": created_at,
            "anchor_number": int(number),
            "from_index": 0,
            "focus_number": int(ranking_payload.get("focus_number", number) or number),
            "occurrence_count": int(ranking_payload.get("occurrence_count", 0) or 0),
            "pulled_total": int(ranking_payload.get("pulled_total", 0) or 0),
            "ranking": ranking,
            "ranking_details": list(ranking_payload.get("ranking_details") or []),
            "window_before": int(ranking_payload.get("window_before", self.window_before) or self.window_before),
            "window_after": int(ranking_payload.get("window_after", self.window_after) or self.window_after),
            "ranking_size": int(ranking_payload.get("ranking_size", self.ranking_size) or self.ranking_size),
            "attempts_window": int(
                (ranking_payload.get("evaluation") or {}).get("attempts_window", self.attempts_window) or self.attempts_window
            ),
            "invert_check_window": int(ranking_payload.get("invert_check_window", self.invert_check_window) or self.invert_check_window),
            "history_size": int(ranking_payload.get("history_size", len(self.history_desc)) or len(self.history_desc)),
            "source": str(ranking_payload.get("source") or "tooltip_occurrences_v1"),
            "source_reason": source,
            "explanation": str(ranking_payload.get("explanation") or ""),
            "summary": str(evaluation_payload.get("summary") or "0/0 acertos observados"),
            "counted": counted,
            "cancelled_reason": cancelled_reason,
            "inverted_evaluation": inverted_payload,
            "hit_count": int(evaluation_payload.get("hit_count", 0) or 0),
            "hit_attempts": list(evaluation_payload.get("hit_attempts") or []),
            "hit_numbers": list(evaluation_payload.get("hit_numbers") or []),
            "first_hit_attempt": evaluation_payload.get("first_hit_attempt"),
            "future_numbers": list(evaluation_payload.get("future_numbers") or []),
            "attempts": list(evaluation_payload.get("attempts") or []),
            "attempts_seen": int(evaluation_payload.get("available_attempts", 0) or 0),
        }
        self.generated_events += 1
        if event_status == "cancelled_inverted":
            self.cancelled_inverted_events += 1
            logging.info(
                "Occurrence live monitor | evento cancelado por invertida=%s | numero=%s | ranking=%s",
                event_id,
                number,
                ranking,
            )
        else:
            self.pending_events[event_id] = {
                **event_state,
                "ranking_set": set(ranking),
            }
            logging.info(
                "Occurrence live monitor | novo evento=%s | numero=%s | ranking=%s",
                event_id,
                number,
                ranking,
            )
        if self.events_coll is not None:
            persisted_event = dict(event_state)
            persisted_event["evaluation"] = evaluation_payload or {
                "status": event_status,
                "attempts_window": event_state["attempts_window"],
                "available_attempts": event_state["attempts_seen"],
                "remaining_attempts": max(0, event_state["attempts_window"] - event_state["attempts_seen"]),
                "hit_count": event_state["hit_count"],
                "hit_attempts": list(event_state["hit_attempts"]),
                "hit_numbers": list(event_state["hit_numbers"]),
                "first_hit_attempt": event_state["first_hit_attempt"],
                "future_numbers": list(event_state["future_numbers"]),
                "attempts": list(event_state["attempts"]),
                "summary": event_state["summary"],
            }
            persisted_event["resolved_at_utc"] = created_at if event_status == "cancelled_inverted" else None
            self.events_coll.insert_one(persisted_event)
        self._flush_run_metrics()

    async def _advance_pending_events(self, number: int) -> None:
        resolved_event_ids: List[str] = []
        for event_id, state in list(self.pending_events.items()):
            state["attempts_seen"] += 1
            state["updated_at_utc"] = _utcnow()
            attempt_no = int(state["attempts_seen"])
            hit = int(number) in state["ranking_set"]
            attempt_payload = {
                "attempt": attempt_no,
                "number": int(number),
                "hit": hit,
                "rank_position": (
                    next(
                        (
                            index + 1
                            for index, ranked_number in enumerate(state["ranking"])
                            if int(ranked_number) == int(number)
                        ),
                        None,
                    )
                ),
            }
            state["attempts"].append(attempt_payload)
            state["future_numbers"].append(int(number))
            self.total_attempts += 1
            if hit:
                state["hit_count"] += 1
                state["hit_attempts"].append(attempt_no)
                state["hit_numbers"].append(int(number))
                self.total_hits += 1
                if state["first_hit_attempt"] is None:
                    state["first_hit_attempt"] = attempt_no
            state["summary"] = (
                f"{state['hit_count']}/{attempt_no} acertos observados ({state['attempts_window']} alvo)"
            )
            if attempt_no >= int(state["attempts_window"]):
                state["status"] = "resolved"
                state["summary"] = f"{state['hit_count']}/{state['attempts_window']} acertos"
                resolved_event_ids.append(event_id)
                self.resolved_events += 1
                if int(state["hit_count"]) > 0:
                    self.events_with_hits += 1
                if isinstance(state["first_hit_attempt"], int):
                    key = str(state["first_hit_attempt"])
                    self.first_hit_distribution[key] = self.first_hit_distribution.get(key, 0) + 1
            if self.events_coll is not None:
                self.events_coll.update_one(
                    {"event_id": event_id},
                    {
                        "$set": {
                            "updated_at_utc": state["updated_at_utc"],
                            "status": state["status"],
                            "attempts_seen": state["attempts_seen"],
                            "summary": state["summary"],
                            "hit_count": state["hit_count"],
                            "hit_attempts": list(state["hit_attempts"]),
                            "hit_numbers": list(state["hit_numbers"]),
                            "first_hit_attempt": state["first_hit_attempt"],
                            "future_numbers": list(state["future_numbers"]),
                            "evaluation": {
                                "status": state["status"],
                                "attempts_window": state["attempts_window"],
                                "available_attempts": state["attempts_seen"],
                                "remaining_attempts": max(0, state["attempts_window"] - state["attempts_seen"]),
                                "hit_count": state["hit_count"],
                                "hit_attempts": list(state["hit_attempts"]),
                                "hit_numbers": list(state["hit_numbers"]),
                                "first_hit_attempt": state["first_hit_attempt"],
                                "future_numbers": list(state["future_numbers"]),
                                "attempts": list(state["attempts"]),
                                "summary": state["summary"],
                            },
                            "resolved_at_utc": state["updated_at_utc"] if state["status"] == "resolved" else None,
                        },
                        "$push": {
                            "attempts": attempt_payload,
                        },
                    },
                )
        for event_id in resolved_event_ids:
            self.pending_events.pop(event_id, None)
        if resolved_event_ids or self.pending_events:
            self._flush_run_metrics()


def _build_parser() -> argparse.ArgumentParser:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Monitor ao vivo da estrategia de ocorrencias do tooltip usando /history e /ws."
    )
    parser.add_argument("--slug", required=True, help="Slug da roleta, ex.: pragmatic-brazilian-roulette")
    parser.add_argument(
        "--api-base-url",
        default=(os.getenv("BASE_URL_API") or "http://localhost:8081").rstrip("/"),
    )
    parser.add_argument("--history-limit", type=int, default=2000)
    parser.add_argument("--window-before", type=int, default=5)
    parser.add_argument("--window-after", type=int, default=3)
    parser.add_argument("--ranking-size", type=int, default=18)
    parser.add_argument("--attempts-window", type=int, default=10)
    parser.add_argument("--invert-check-window", type=int, default=0)
    parser.add_argument("--reconnect-delay", type=float, default=3.0)
    parser.add_argument("--http-timeout", type=float, default=20.0)
    parser.add_argument("--max-backlog", type=int, default=200)
    parser.add_argument("--mongo-url", default=os.getenv("MONGO_URL") or os.getenv("mongo_url") or "")
    parser.add_argument("--mongo-db", default=os.getenv("MONGO_DB") or "roleta_db")
    parser.add_argument("--persist", action=argparse.BooleanOptionalAction, default=True)
    return parser


async def _async_main(args: argparse.Namespace) -> None:
    monitor = OccurrenceLiveMonitor(args)
    loop = asyncio.get_running_loop()

    def _handle_stop(*_args: Any) -> None:
        logging.info("Occurrence live monitor stop requested.")
        monitor.stop()

    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, _handle_stop)
        except NotImplementedError:
            signal.signal(sig, lambda *_: _handle_stop())

    await monitor.start()


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    if args.persist and not str(args.mongo_url or "").strip():
        parser.error("`--mongo-url` (ou MONGO_URL) e obrigatorio quando `--persist` esta ativo.")
    asyncio.run(_async_main(args))


if __name__ == "__main__":
    main()
