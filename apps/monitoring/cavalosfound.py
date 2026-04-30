from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import random
import re
import sys
import time
import traceback
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import aiohttp
from redis.exceptions import RedisError


REPO_ROOT = Path(__file__).resolve().parents[2]
APPS_ROOT = REPO_ROOT / "apps"
if str(APPS_ROOT) not in sys.path:
    sys.path.insert(0, str(APPS_ROOT))

from api.core.db import history_coll  # noqa: E402
from api.core.redis_client import create_pubsub_redis_client  # noqa: E402


LOGGER = logging.getLogger("cavalosfound")

DEFAULT_TELEGRAM_TOKEN = "8025852537:AAFj-j0rDK22RV5dZwdlHcxigLwwNwDo3ws"
DEFAULT_CHAT_ID = "-1002634558541"
TELEGRAM_TOKEN = (
    os.getenv("HORSE_FOUND_TELEGRAM_TOKEN")
    or os.getenv("TELEGRAM_TOKEN")
    or DEFAULT_TELEGRAM_TOKEN
)
CHAT_ID = (
    os.getenv("HORSE_FOUND_CHAT_ID")
    or os.getenv("TELEGRAM_CHAT_ID")
    or DEFAULT_CHAT_ID
)
BUTTON_TEXT = os.getenv("HORSE_FOUND_BUTTON_TEXT", "ACESSE A MESA")
BET_API_URL = (os.getenv("HORSE_FOUND_BET_API_URL") or "http://localhost:3000/api/bet").strip()
AUTO_BET_ENABLED = str(os.getenv("HORSE_FOUND_AUTO_BET_ENABLED", "1")).strip().lower() not in {"0", "false", "off", "no"}
BET_API_TIMEOUT = float(os.getenv("HORSE_FOUND_BET_API_TIMEOUT", "15"))

START_BANKROLL = float(os.getenv("HORSE_FOUND_START_BANKROLL", "723"))
CHIP_VALUE = float(os.getenv("HORSE_FOUND_CHIP_VALUE", "1"))
SESSION_PAUSE = int(os.getenv("HORSE_FOUND_SESSION_PAUSE", "0"))
BATCH_SIZE = int(os.getenv("HORSE_FOUND_BATCH_SIZE", "10"))
FETCH_SIZE = int(os.getenv("HORSE_FOUND_FETCH_SIZE", "150"))
RESULT_CHANNEL = (os.getenv("HORSE_FOUND_RESULT_CHANNEL") or "new_result").strip() or "new_result"
ROULETTE_FILTER_RAW = os.getenv("HORSE_FOUND_ROULETTES", "")

BASE_DIR = Path(__file__).resolve().parent
LOGS_DIR = BASE_DIR / "Logs"
STATE_PATH = Path(os.getenv("HORSE_FOUND_STATE_PATH") or (LOGS_DIR / "cavalosfound_state.json"))
WORKER_LOG_PATH = Path(os.getenv("HORSE_FOUND_LOG_PATH") or (LOGS_DIR / "cavalosfound_worker.log"))
AUTO_BET_STATUS_PLACEHOLDER = "__AUTO_BET_STATUS__"


TABLES_TO_MONITOR: List[Dict[str, str]] = [
    {"slug": "pragmatic-korean-roulette", "name": "Korean Roulette", "link": "https://lotogreen.bet.br/play/457"},
    {"slug": "pragmatic-auto-roulette", "name": "Auto Roulette", "link": "https://lotogreen.bet.br/play/373"},
    {"slug": "pragmatic-brazilian-roulette", "name": "Brazilian Roulette", "link": "https://lotogreen.bet.br/play/450"},
    {"slug": "pragmatic-roulette-macao", "name": "Roulette Macao", "link": "https://lotogreen.bet.br/play/552"},
    {"slug": "pragmatic-roulette-1", "name": "Roulette 1", "link": "https://lotogreen.bet.br/play/473"},
]


def _configure_logging() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    LOGGER.addHandler(stream_handler)

    file_handler = logging.FileHandler(WORKER_LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(formatter)
    LOGGER.addHandler(file_handler)
    LOGGER.propagate = False


def _parse_roulette_allowlist(raw_value: str) -> set[str]:
    if not raw_value:
        return set()
    return {
        str(item).strip()
        for item in raw_value.split(",")
        if str(item).strip()
    }


ROULETTE_ALLOWLIST = _parse_roulette_allowlist(ROULETTE_FILTER_RAW)


def _resolve_monitored_tables() -> List[Dict[str, str]]:
    if not ROULETTE_ALLOWLIST:
        return list(TABLES_TO_MONITOR)
    return [table for table in TABLES_TO_MONITOR if table["slug"] in ROULETTE_ALLOWLIST]


MONITORED_TABLES = _resolve_monitored_tables()
TABLE_BY_SLUG = {table["slug"]: table for table in MONITORED_TABLES}


def generate_key() -> str:
    return "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ", k=5))


def _serialize_iso(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return None


def _to_epoch(value: Any) -> float:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
    return time.time()


def _write_pattern_log(pattern_name: str, result_text: str, hidden_log: str = "") -> None:
    clean_name = re.sub(r"[^A-Za-z0-9_]", "", pattern_name.replace(" ", "_"))
    filename = LOGS_DIR / f"log_{clean_name}.txt"
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    clean_text = re.sub(r"<[^>]+>", "", result_text)
    log_entry = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}]\n{clean_text}\n"
    if hidden_log:
        log_entry += f"\n[CAIXA PRETA - CONTEXTO HISTORICO]\n{hidden_log}\n"
    log_entry += "=" * 60 + "\n"
    try:
        with filename.open("a", encoding="utf-8") as file_obj:
            file_obj.write(log_entry)
    except Exception:
        LOGGER.exception("Falha ao escrever log do padrao %s", pattern_name)


class TelegramClient:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _request(self, method: str, payload: Dict[str, Any]) -> Dict[str, Any] | None:
        if not self.token or not self.chat_id:
            LOGGER.warning("Telegram desabilitado: token/chat_id ausentes")
            return None
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        for attempt in range(6):
            try:
                session = await self._get_session()
                async with session.post(url, json=payload, timeout=8) as response:
                    if response.status == 200:
                        return await response.json()
                    if response.status == 429:
                        body = await response.json()
                        wait_time = int(body.get("parameters", {}).get("retry_after", 3))
                        await asyncio.sleep(wait_time + 1)
                        continue
                    LOGGER.warning("Telegram %s retornou HTTP %s", method, response.status)
                    return None
            except Exception:
                if attempt == 5:
                    LOGGER.exception("Falha no Telegram %s apos retries", method)
                    return None
                await asyncio.sleep(1)
        return None

    async def send_message(self, text: str, link: Optional[str] = None) -> Optional[int]:
        payload: Dict[str, Any] = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        if link:
            payload["reply_markup"] = {
                "inline_keyboard": [[{"text": BUTTON_TEXT, "url": link}]]
            }
        data = await self._request("sendMessage", payload)
        if not data:
            return None
        return data.get("result", {}).get("message_id")

    async def edit_message(self, msg_id: int, text: str, link: Optional[str] = None) -> None:
        payload: Dict[str, Any] = {
            "chat_id": self.chat_id,
            "message_id": msg_id,
            "text": text,
            "parse_mode": "HTML",
        }
        if link:
            payload["reply_markup"] = {
                "inline_keyboard": [[{"text": BUTTON_TEXT, "url": link}]]
            }
        await self._request("editMessageText", payload)


class AutomaticBetClient:
    def __init__(self, endpoint: str, enabled: bool = True, timeout_seconds: float = 15):
        self.endpoint = endpoint.strip()
        self.enabled = enabled and bool(self.endpoint)
        self.timeout_seconds = timeout_seconds
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def send_bet(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.enabled:
            return {"success": False, "disabled": True, "error": "aposta_automatica_desabilitada"}
        try:
            session = await self._get_session()
            async with session.post(self.endpoint, json=payload, timeout=self.timeout_seconds) as response:
                body_text = await response.text()
                try:
                    body = json.loads(body_text) if body_text else {}
                except json.JSONDecodeError:
                    body = {"raw": body_text}
                return {
                    "success": response.status < 400 and bool(body.get("success", True)),
                    "status_code": response.status,
                    "body": body,
                    "raw": body_text,
                }
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
            }


class BankrollManager:
    def __init__(self, name: str, max_steps: int):
        self.name = name
        self.max_steps = max_steps
        self.balance = START_BANKROLL
        self.start_balance = START_BANKROLL
        self.chip = CHIP_VALUE
        self.total_wins = 0
        self.total_losses = 0
        self.g_wins = {k: 0 for k in range(max_steps)}

        self.session_wins = 0
        self.session_losses = 0
        self.current_batch = 1
        self.entries_started_batch = 0
        self.entries_finished_batch = 0
        self.batch_wins = 0
        self.batch_losses = 0
        self.active_bets_now = 0
        self.is_paused = False
        self.pause_until = 0.0

    def update_chip(self) -> None:
        multiplier = max(1, int(self.balance // START_BANKROLL))
        self.chip = CHIP_VALUE * multiplier

    def can_start_new_entry(self) -> bool:
        if self.is_paused:
            return False
        return self.entries_started_batch < BATCH_SIZE

    def register_entry_start(self) -> None:
        self.entries_started_batch += 1
        self.active_bets_now += 1

    def register_entry_end(self, now_ts: float) -> None:
        self.entries_finished_batch += 1
        if self.active_bets_now > 0:
            self.active_bets_now -= 1
        self._check_batch_completion(now_ts)

    def _check_batch_completion(self, now_ts: float) -> None:
        if self.entries_finished_batch < self.entries_started_batch or self.entries_started_batch < BATCH_SIZE:
            return
        if self.current_batch == 1:
            if self.batch_losses == 0:
                self.is_paused = True
                self.pause_until = now_ts + SESSION_PAUSE
            else:
                self.current_batch = 2
                self.entries_started_batch = 0
                self.entries_finished_batch = 0
        elif self.current_batch == 2:
            self.is_paused = True
            self.pause_until = now_ts + SESSION_PAUSE

    def check_session_status(self, now_ts: float) -> tuple[bool, str]:
        if self.is_paused and int(self.pause_until - now_ts) <= 0:
            self.is_paused = False
            self.session_wins = 0
            self.session_losses = 0
            self.current_batch = 1
            self.entries_started_batch = 0
            self.entries_finished_batch = 0
            self.active_bets_now = 0
        return self.is_paused, ""

    def process_win(self, attempt_idx: int, bet_list: List[int], multipliers: List[float]) -> float:
        self.update_chip()
        safe_idx = min(attempt_idx, len(multipliers) - 1)
        total_cost = sum(len(bet_list) * multipliers[i] * self.chip for i in range(safe_idx + 1))
        payout = 36 * multipliers[safe_idx] * self.chip
        profit = payout - total_cost
        self.balance += profit
        self.total_wins += 1
        self.session_wins += 1
        self.batch_wins += 1
        if safe_idx in self.g_wins:
            self.g_wins[safe_idx] += 1
        self.update_chip()
        return profit

    def process_loss(self, bet_list: List[int], multipliers: List[float]) -> float:
        self.update_chip()
        total_cost = sum(len(bet_list) * m * self.chip for m in multipliers)
        self.balance -= total_cost
        self.total_losses += 1
        self.session_losses += 1
        self.batch_losses += 1
        self.update_chip()
        return total_cost

    def get_short_dashboard(self) -> str:
        total = self.total_wins + self.total_losses
        acc = (self.total_wins / total * 100) if total > 0 else 0.0
        profit_total = self.balance - self.start_balance
        symbol = "+" if profit_total >= 0 else ""
        gale_text = " | ".join([f"G{k}: {v}" for k, v in self.g_wins.items() if k < self.max_steps])
        return (
            f"R$ {self.balance:.2f} ({symbol}{profit_total:.2f}) [Ficha: R${self.chip:.2f}]\n"
            f"   └ ✅ {self.total_wins} ❌ {self.total_losses} ({acc:.1f}%)\n"
            f"   └ [{gale_text}]"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "balance": self.balance,
            "total_wins": self.total_wins,
            "total_losses": self.total_losses,
            "g_wins": self.g_wins,
        }

    def from_dict(self, data: Mapping[str, Any]) -> None:
        self.balance = float(data.get("balance", self.start_balance))
        self.total_wins = int(data.get("total_wins", 0))
        self.total_losses = int(data.get("total_losses", 0))
        self.g_wins = {int(k): int(v) for k, v in dict(data.get("g_wins", {})).items()}
        self.update_chip()


class Scoreboard:
    def __init__(self, name: str, title: str, max_steps: int, notifier: TelegramClient, proj_steps: int = 0):
        self.msg_id: Optional[int] = None
        self.name = name
        self.title = title
        self.notifier = notifier
        self.bank = BankrollManager(name, max_steps)
        self.proj_bank = BankrollManager(f"{name}_proj", proj_steps) if proj_steps > 0 else None

    def get_text(self) -> str:
        text = f"🏆 <b>{self.title}</b> 🏆\n\n"
        text += f"🎯 <b>Desempenho Real ({self.bank.max_steps} Tentativas):</b>\n{self.bank.get_short_dashboard()}\n\n"
        if self.proj_bank:
            text += f"📊 <b>Projeção Analítica ({self.proj_bank.max_steps} Tentativas):</b>\n{self.proj_bank.get_short_dashboard()}\n\n"
        text += "<i>Sincronizando Máquina...</i>"
        return text

    async def send_initial(self) -> None:
        self.msg_id = await self.notifier.send_message(self.get_text())

    async def update(self) -> None:
        if self.msg_id:
            await self.notifier.edit_message(self.msg_id, self.get_text())


class RouletteMath:
    @staticmethod
    def calculate_dynamic_mults(
        bet_count: int,
        steps: int,
        min_profit: float = 10.0,
        base_mults: Optional[List[float]] = None,
    ) -> List[float]:
        if base_mults is not None and len(base_mults) == steps:
            return base_mults
        mults: List[float] = []
        total_cost = 0.0
        for _ in range(steps):
            if 36 <= bet_count:
                return [1.0] * steps
            multiplier = (min_profit + total_cost) / (36 - bet_count)
            multiplier = math.ceil(multiplier * 2) / 2.0
            if multiplier < 1.0:
                multiplier = 1.0
            while 36 * multiplier - (total_cost + bet_count * multiplier) < min_profit:
                multiplier += 0.5
            mults.append(multiplier)
            total_cost += bet_count * multiplier
        return mults

    @staticmethod
    def get_horse_base_idx(number: int) -> Optional[int]:
        if number in [0, 10, 20, 30]:
            return None
        terminal = number % 10
        if terminal in [1, 4, 7]:
            return 1
        if terminal in [2, 5, 8]:
            return 2
        if terminal in [3, 6, 9]:
            return 3
        return None

    @staticmethod
    def get_full_horse_bet(horse_idx_list: List[int]) -> List[int]:
        nums: List[int] = []
        for horse_idx in horse_idx_list:
            if horse_idx == 1:
                nums.extend([1, 4, 7, 11, 14, 17, 21, 24, 27, 31, 34, 10])
            elif horse_idx == 2:
                nums.extend([2, 5, 8, 12, 15, 18, 22, 25, 28, 32, 35, 20])
            elif horse_idx == 3:
                nums.extend([3, 6, 9, 13, 16, 19, 23, 26, 29, 33, 36, 30])
        return sorted(set(nums))


class HorseFoundEngine:
    @staticmethod
    def analyze(history: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if len(history) < 20:
            return None
        raw = [item["val"] for item in history[:50]]
        current_hit = raw[0]
        if current_hit not in [10, 20, 30]:
            return None

        previous_number = raw[1]
        if previous_number in [0, 10, 20, 30]:
            return None

        if any(value in [0, 10, 20, 30] for value in raw[2:5]):
            return None

        subtract_value = 0
        if current_hit == 10:
            subtract_value = 9
        elif current_hit == 20:
            subtract_value = 25
        elif current_hit == 30:
            subtract_value = 36

        math_target = abs(previous_number - subtract_value)
        horse_idx = RouletteMath.get_horse_base_idx(math_target)
        redirect_message = ""

        if horse_idx == 3:
            horse_idx = RouletteMath.get_horse_base_idx(previous_number)
            redirect_message = f" (Desvio 369 -> Formacao {previous_number})"
            if horse_idx == 3 or horse_idx is None:
                back_number = raw[2]
                horse_idx = RouletteMath.get_horse_base_idx(back_number)
                redirect_message = f" (Desvio 369 Duplo -> Antecessor {back_number})"
                if horse_idx == 3 or horse_idx is None:
                    return None

        if horse_idx is None:
            return None

        bet_list = sorted(set(RouletteMath.get_full_horse_bet([horse_idx]) + [0]))
        multipliers = [1.0, 2.0, 2.0]
        last_10 = " - ".join(map(str, raw[:10]))
        info = (
            "🐎 <b>HORSE FOUND (CAVALOS)</b>\n\n"
            f"📚 <b>Ultimos 10 Numeros:</b>\n<code>{last_10}</code>\n\n"
            f"🔗 <b>Gatilho Fixado:</b> {current_hit}\n"
            f"🧮 <b>Matematica:</b> |{previous_number} - {subtract_value}| = {math_target}{redirect_message}\n"
            f"⚡ <b>Acao:</b> Cavalo {horse_idx} + 0!"
        )
        return {
            "pattern_type": "HorseFound",
            "trigger_val": f"HORSEF_CAV_{current_hit}_{previous_number}_{math_target}_{generate_key()}",
            "target_name": f"Cavalo {horse_idx} + 0",
            "bet_list": bet_list,
            "info": info,
            "multipliers": multipliers,
            "multipliers_proj": [],
            "gale_msg": "Gestao Tatica (3x: 1x-2x-2x)",
            "hidden_log": (
                f"HorseFound Cavalo: Gatilho {current_hit}. "
                f"Anterior {previous_number}. Alvo Math {math_target}. Cav Final {horse_idx}."
            ),
            "steps": ["bet1", "bet2", "bet3"],
        }


def _scoreboard_version() -> Dict[str, str]:
    return {"HorseFound": "v11-redis-3x-sequence"}


class TableBot:
    def __init__(
        self,
        cfg: Mapping[str, str],
        board: Scoreboard,
        notifier: TelegramClient,
        bet_client: AutomaticBetClient,
    ):
        self.cfg = dict(cfg)
        self.board = board
        self.notifier = notifier
        self.bet_client = bet_client
        self.history: List[Dict[str, Any]] = []
        self.active_bets: Dict[str, Dict[str, Any]] = {}
        self.cooldowns: Dict[str, int] = {}
        self._recent_event_ids: deque[str] = deque(maxlen=max(300, FETCH_SIZE * 3))
        self._recent_event_id_set: set[str] = set()

    def _set_auto_bet_status(self, bet: Dict[str, Any], status_text: str) -> None:
        base_text = str(bet.get("base_text") or "")
        if AUTO_BET_STATUS_PLACEHOLDER in base_text:
            bet["base_text"] = base_text.replace(AUTO_BET_STATUS_PLACEHOLDER, status_text)
            return
        if status_text not in base_text:
            bet["base_text"] = f"{base_text}\n{status_text}".strip()

    def _remember_event_id(self, event_id: str) -> None:
        normalized = str(event_id or "").strip()
        if not normalized:
            return
        if normalized in self._recent_event_id_set:
            return
        if len(self._recent_event_ids) >= self._recent_event_ids.maxlen:
            old = self._recent_event_ids.popleft()
            self._recent_event_id_set.discard(old)
        self._recent_event_ids.append(normalized)
        self._recent_event_id_set.add(normalized)

    def _has_seen_event_id(self, event_id: str) -> bool:
        normalized = str(event_id or "").strip()
        return bool(normalized) and normalized in self._recent_event_id_set

    async def initialize_from_db(self) -> None:
        docs = await (
            history_coll.find({"roulette_id": self.cfg["slug"]})
            .sort("timestamp", -1)
            .limit(FETCH_SIZE)
            .to_list(length=FETCH_SIZE)
        )
        self.history = []
        self.cooldowns = {}
        self._recent_event_ids.clear()
        self._recent_event_id_set.clear()
        for doc in docs:
            entry = {
                "val": int(doc.get("value")),
                "key": str(doc.get("_id")),
                "ts": _to_epoch(doc.get("timestamp")),
                "history_id": str(doc.get("_id")),
                "external_game_id": str(doc.get("external_game_id") or "").strip(),
            }
            self.history.append(entry)
            self._remember_event_id(entry["history_id"])
            if entry["external_game_id"]:
                self._remember_event_id(f"external:{entry['external_game_id']}")
        LOGGER.info("Historico inicial carregado | roulette=%s | items=%s", self.cfg["slug"], len(self.history))

    async def process_result_entry(self, entry: Mapping[str, Any]) -> None:
        history_id = str(entry.get("history_id") or "").strip()
        external_game_id = str(entry.get("external_game_id") or "").strip()
        if history_id and self._has_seen_event_id(history_id):
            return
        if external_game_id and self._has_seen_event_id(f"external:{external_game_id}"):
            return

        for cooldown_key in list(self.cooldowns.keys()):
            self.cooldowns[cooldown_key] -= 1
            if self.cooldowns[cooldown_key] <= 0:
                del self.cooldowns[cooldown_key]

        now_ts = float(entry.get("ts") or time.time())
        trigger_id = history_id or external_game_id or f"live_{generate_key()}"
        new_item = {
            "val": int(entry.get("val")),
            "key": trigger_id,
            "ts": now_ts,
            "history_id": history_id,
            "external_game_id": external_game_id,
        }
        self.history.insert(0, new_item)
        if len(self.history) > FETCH_SIZE:
            self.history.pop()

        if history_id:
            self._remember_event_id(history_id)
        if external_game_id:
            self._remember_event_id(f"external:{external_game_id}")

        await self.logic_cycle(int(entry.get("val")), now_ts, trigger_id)

    async def logic_cycle(self, current_num: int, current_ts: float, trigger_id: str) -> None:
        for bet_id in list(self.active_bets.keys()):
            await self.handle_active_bet(current_num, bet_id, current_ts)

        signal = HorseFoundEngine.analyze(self.history)
        if not signal:
            return

        pattern_type = signal["pattern_type"]
        bet_id = f"{self.cfg['slug']}_{signal['trigger_val']}_{trigger_id}"

        for active_data in self.active_bets.values():
            if (
                active_data["pattern_type"] == pattern_type
                and active_data["target_name"] == signal["target_name"]
            ):
                return

        if bet_id in self.active_bets or bet_id in self.cooldowns:
            return

        paused, _ = self.board.bank.check_session_status(current_ts)
        if paused or not self.board.bank.can_start_new_entry():
            return

        self.cooldowns[bet_id] = 10
        self.board.bank.register_entry_start()
        await self.start_bet(signal, bet_id)

    async def _send_initial_bet_msg(self, bet_id: str) -> None:
        bet = self.active_bets[bet_id]
        info_text = "🔁 <b>3 Tentativas Taticas</b>"
        current_last_10 = " - ".join([str(item["val"]) for item in self.history[:10]])
        header = f"🚀 <b>NOVO SINAL {bet['pattern_type'].upper()}</b>"

        info_base = bet["signal_info"]
        if "📚 <b>Ultimos 10 Numeros:</b>" not in info_base:
            lines = info_base.split("\n")
            lines.insert(2, f"📚 <b>Ultimos 10 Numeros:</b>\n<code>{current_last_10}</code>\n")
            updated_signal_info = "\n".join(lines)
        else:
            updated_signal_info = info_base

        base_message = (
            f"{header}\n"
            f"🎰 <b>{self.cfg['name']}</b>\n\n"
            f"{updated_signal_info}\n"
            f"🎯 <b>Alvo Final:</b> {bet['target_name']}\n"
            f"🔢 <b>Apostar:</b> {bet['bet_list']}\n"
            f"{AUTO_BET_STATUS_PLACEHOLDER}\n"
            f"{info_text}\n{bet['gale_msg']}"
        )
        bet["base_text"] = base_message
        self._set_auto_bet_status(bet, "🤖 <b>Aposta automática:</b> envio iniciado para o bot")
        text_to_fire = (
            f"{bet['base_text']}\n\n"
            "✅ <b>ATIRAR (REAL)!</b>\n"
            "Iniciando Ataque na Mesa!"
        )
        bet["msg_id"] = await self.notifier.send_message(text_to_fire, self.cfg["link"])

    def _build_auto_bet_payload(self, bet_id: str) -> Dict[str, Any]:
        bet = self.active_bets[bet_id]
        attempts = max(1, len(bet.get("multipliers") or []))
        chip_value = round(float(self.board.bank.chip), 2)
        bet_sequence = [
            round(chip_value * float(multiplier), 2)
            for multiplier in (bet.get("multipliers") or [1.0])
        ]
        return {
            "bets": list(bet["bet_list"]),
            "attempts": attempts,
            "roulette_url": self.cfg["link"],
            "gales": attempts,
            "valor": chip_value,
            "bet_sequence": bet_sequence,
            "source": "cavalosfound",
            "pattern": bet["pattern_type"],
            "bet_id": bet_id,
        }

    async def _dispatch_automatic_bet(self, bet_id: str) -> None:
        bet = self.active_bets.get(bet_id)
        if not bet:
            return
        payload = self._build_auto_bet_payload(bet_id)
        bet["auto_bet_payload"] = payload
        result = await self.bet_client.send_bet(payload)
        bet["auto_bet_result"] = result
        if result.get("success"):
            response_body = result.get("body") or {}
            result_label = str(response_body.get("result") or response_body.get("status") or "aceita")
            attempts_used = response_body.get("attempts")
            status_text = f"🤖 <b>Aposta automática:</b> enviada ao bot"
            if attempts_used is not None:
                status_text += f" | retorno: {result_label} | tentativas: {attempts_used}"
            else:
                status_text += f" | retorno: {result_label}"
            self._set_auto_bet_status(bet, status_text)
            if bet.get("msg_id"):
                await self.notifier.edit_message(bet["msg_id"], bet["base_text"], self.cfg["link"])
            LOGGER.info(
                "Aposta automatica enviada | roulette=%s | bet_id=%s | endpoint=%s | bets=%s | valor=%s",
                self.cfg["slug"],
                bet_id,
                self.bet_client.endpoint,
                payload["bets"],
                payload["valor"],
            )
            return

        error_message = str(result.get("error") or result.get("body") or result.get("raw") or "falha_desconhecida")
        LOGGER.error(
            "Falha na aposta automatica | roulette=%s | bet_id=%s | endpoint=%s | error=%s",
            self.cfg["slug"],
            bet_id,
            self.bet_client.endpoint,
            error_message,
        )
        self._set_auto_bet_status(bet, f"⚠️ <b>Aposta automática falhou:</b> {error_message}")
        if bet.get("msg_id"):
            await self.notifier.edit_message(bet["msg_id"], bet["base_text"], self.cfg["link"])

    async def start_bet(self, signal: Dict[str, Any], bet_id: str) -> None:
        self.active_bets[bet_id] = {
            "pattern_type": signal["pattern_type"],
            "msg_id": None,
            "base_text": "",
            "signal_info": signal["info"],
            "target_name": signal["target_name"],
            "bet_list": signal["bet_list"],
            "steps": signal["steps"],
            "step_idx": 0,
            "rolled_nums": [],
            "multipliers": signal.get("multipliers", [1.0, 2.0, 4.0]),
            "multipliers_proj": signal.get("multipliers_proj", []),
            "hidden_log": signal.get("hidden_log", ""),
            "gale_msg": signal.get("gale_msg", ""),
            "auto_bet_result": None,
            "auto_bet_payload": None,
        }
        await self._send_initial_bet_msg(bet_id)
        asyncio.create_task(self._dispatch_automatic_bet(bet_id))

    async def handle_active_bet(self, num: int, bet_id: str, current_ts: float) -> None:
        bet = self.active_bets.get(bet_id)
        if not bet:
            return

        try:
            current_step = bet["steps"][bet["step_idx"]]
            if current_step.startswith("wait"):
                bet["step_idx"] += 1
                return

            bet["rolled_nums"].append(num)
            rolled_str = " - ".join(map(str, bet["rolled_nums"]))
            bank_real = self.board.bank
            bank_proj = self.board.proj_bank

            if not current_step.startswith("bet"):
                return

            attempt_idx = int(current_step[-1]) - 1
            mults_real = bet["multipliers"]
            mults_proj = bet["multipliers_proj"]

            if num in bet["bet_list"]:
                profit_text = ""
                safe_proj_idx = min(attempt_idx, len(mults_proj) - 1) if mults_proj else 0
                if attempt_idx < len(mults_real):
                    profit = bank_real.process_win(attempt_idx, bet["bet_list"], mults_real)
                    profit_text = f"(+R$ {profit:.2f})"
                else:
                    tactical_loss = sum(m * bank_real.chip for m in mults_real for _ in bet["bet_list"])
                    profit_text = f"(-R$ {tactical_loss:.2f} Tatica / GREEN Analitica)"

                if bank_proj and attempt_idx < len(mults_proj):
                    chip_proj = bank_proj.chip
                    cost_proj = sum(len(bet["bet_list"]) * mults_proj[i] * chip_proj for i in range(safe_proj_idx + 1))
                    payout_proj = 36 * mults_proj[safe_proj_idx] * chip_proj
                    profit_proj = payout_proj - cost_proj
                    bank_proj.process_win(attempt_idx, bet["bet_list"], mults_proj)
                    if attempt_idx >= len(mults_real):
                        profit_text = f"(-R$ {tactical_loss:.2f} Tatica / +R$ {profit_proj:.2f} Analitica)"

                footer = (
                    f"\n\n✅ <b>GREEN NO G{attempt_idx}!</b> {profit_text}\n"
                    f"🎲 <b>Saidas no Ataque:</b> {rolled_str}\n"
                    f"{self.board.get_text()}"
                )
                del self.active_bets[bet_id]
                bank_real.register_entry_end(current_ts)
                _write_pattern_log(bet["pattern_type"], bet["base_text"] + footer, bet["hidden_log"])
                save_scoreboards([self.board])
                if bet["msg_id"]:
                    asyncio.create_task(self.notifier.edit_message(bet["msg_id"], bet["base_text"] + footer, self.cfg["link"]))
                await self.board.update()
                return

            if attempt_idx == len(mults_real) - 1:
                bank_real.process_loss(bet["bet_list"], mults_real)
            if bank_proj and attempt_idx == len(mults_proj) - 1:
                bank_proj.process_loss(bet["bet_list"], mults_proj)

            bet["step_idx"] += 1
            if bet["step_idx"] < len(bet["steps"]):
                return

            loss_value = sum(m * bank_real.chip for m in mults_real for _ in bet["bet_list"])
            footer = (
                f"\n\n❌ <b>RED PRINCIPAL</b> (-R$ {loss_value:.2f})\n"
                f"🎲 <b>Saidas no Ataque:</b> {rolled_str}\n"
                f"{self.board.get_text()}"
            )
            del self.active_bets[bet_id]
            bank_real.register_entry_end(current_ts)
            _write_pattern_log(bet["pattern_type"], bet["base_text"] + footer, bet["hidden_log"])
            save_scoreboards([self.board])
            if bet["msg_id"]:
                asyncio.create_task(self.notifier.edit_message(bet["msg_id"], bet["base_text"] + footer, self.cfg["link"]))
            await self.board.update()
        except Exception:
            LOGGER.error("Erro no handle_active_bet | roulette=%s | bet_id=%s", self.cfg["slug"], bet_id)
            LOGGER.error(traceback.format_exc())
            self.active_bets.pop(bet_id, None)


def load_scoreboards(boards: List[Scoreboard]) -> None:
    try:
        with STATE_PATH.open("r", encoding="utf-8") as file_obj:
            data = json.load(file_obj)
    except Exception:
        return

    version_map = _scoreboard_version()
    for board in boards:
        board_data = data.get(board.name)
        if not isinstance(board_data, Mapping):
            continue
        if board_data.get("version") != version_map.get(board.name, ""):
            continue
        if "real" in board_data:
            board.bank.from_dict(board_data["real"])
        if board.proj_bank and "proj" in board_data:
            board.proj_bank.from_dict(board_data["proj"])


def save_scoreboards(boards: List[Scoreboard]) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    version_map = _scoreboard_version()
    payload: Dict[str, Any] = {}
    for board in boards:
        row: Dict[str, Any] = {"real": board.bank.to_dict()}
        if board.proj_bank:
            row["proj"] = board.proj_bank.to_dict()
        row["version"] = version_map.get(board.name, "")
        payload[board.name] = row
    try:
        with STATE_PATH.open("w", encoding="utf-8") as file_obj:
            json.dump(payload, file_obj)
    except Exception:
        LOGGER.exception("Falha ao salvar estado dos placares")


def _coerce_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except Exception:
        return None


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    raw = str(value).strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _parse_result_message(raw_data: Any) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, Mapping):
        return None

    roulette_id = str(payload.get("slug") or payload.get("roulette_id") or "").strip()
    if not roulette_id:
        return None
    result_number = _coerce_int(payload.get("result"))
    if result_number is None or not (0 <= result_number <= 36):
        return None

    full_result = payload.get("full_result") if isinstance(payload.get("full_result"), Mapping) else {}
    history_id = str(full_result.get("_id") or payload.get("_id") or payload.get("history_id") or "").strip()
    external_game_id = str(full_result.get("external_game_id") or payload.get("external_game_id") or "").strip()
    ts_value = _parse_iso_datetime(full_result.get("timestamp")) or datetime.now(timezone.utc)
    return {
        "roulette_id": roulette_id,
        "val": result_number,
        "history_id": history_id,
        "external_game_id": external_game_id,
        "ts": ts_value.timestamp(),
        "timestamp_utc": ts_value,
    }


async def run_worker() -> None:
    _configure_logging()
    if not MONITORED_TABLES:
        LOGGER.warning("Nenhuma roleta configurada para o HorseFound")
        return

    notifier = TelegramClient(TELEGRAM_TOKEN, CHAT_ID)
    bet_client = AutomaticBetClient(BET_API_URL, enabled=AUTO_BET_ENABLED, timeout_seconds=BET_API_TIMEOUT)
    board_horse_found = Scoreboard("HorseFound", "🐎 HORSE FOUND", 3, notifier, proj_steps=0)
    all_boards = [board_horse_found]
    bots = [TableBot(table, board_horse_found, notifier, bet_client) for table in MONITORED_TABLES]
    bot_by_slug = {bot.cfg["slug"]: bot for bot in bots}

    LOGGER.info(
        "HorseFound worker iniciando | channel=%s | monitoradas=%s | auto_bet=%s | endpoint=%s | log=%s",
        RESULT_CHANNEL,
        ",".join(sorted(bot_by_slug.keys())),
        "on" if AUTO_BET_ENABLED else "off",
        BET_API_URL,
        str(WORKER_LOG_PATH),
    )

    await asyncio.gather(*(bot.initialize_from_db() for bot in bots))
    load_scoreboards(all_boards)
    for board in all_boards:
        await board.send_initial()
        await asyncio.sleep(1)

    client = create_pubsub_redis_client()
    pubsub = client.pubsub()
    await pubsub.subscribe(RESULT_CHANNEL)
    total_messages = 0
    total_processed = 0
    total_invalid = 0
    total_skipped = 0

    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            total_messages += 1
            parsed = _parse_result_message(message.get("data"))
            if not parsed:
                total_invalid += 1
                if total_invalid <= 5 or total_invalid % 25 == 0:
                    LOGGER.warning("Payload invalido ignorado | invalid=%s | total=%s", total_invalid, total_messages)
                continue

            roulette_id = str(parsed["roulette_id"])
            bot = bot_by_slug.get(roulette_id)
            if not bot:
                total_skipped += 1
                continue

            try:
                await bot.process_result_entry(parsed)
                total_processed += 1
                if total_processed <= 5 or total_processed % 25 == 0:
                    LOGGER.info(
                        "Resultado processado | roulette=%s | result=%s | history_id=%s | active_bets=%s | processed=%s | total=%s",
                        roulette_id,
                        parsed["val"],
                        parsed.get("history_id") or "-",
                        len(bot.active_bets),
                        total_processed,
                        total_messages,
                    )
            except Exception:
                LOGGER.error("Falha ao processar resultado | roulette=%s", roulette_id)
                LOGGER.error(traceback.format_exc())
    except RedisError as exc:
        LOGGER.error("HorseFound worker interrompido pelo Redis: %s", exc)
        raise
    finally:
        save_scoreboards(all_boards)
        try:
            await pubsub.close()
        except Exception:
            pass
        try:
            await client.close()
        except Exception:
            pass
        await bet_client.close()
        await notifier.close()


if __name__ == "__main__":
    asyncio.run(run_worker())
