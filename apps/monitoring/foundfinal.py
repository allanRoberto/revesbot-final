import os, asyncio, aiohttp, time, sys, random, json, math, re
from datetime import datetime, timezone
from pathlib import Path
from collections import deque, Counter, defaultdict
from typing import List, Optional, Dict, Tuple, Set, Any, Mapping
import traceback

from dotenv import load_dotenv
from redis.exceptions import RedisError

REPO_ROOT = Path(__file__).resolve().parents[2]
APPS_ROOT = REPO_ROOT / "apps"
for candidate in (REPO_ROOT, APPS_ROOT):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

load_dotenv(REPO_ROOT / ".env")

from api.core.db import history_coll  # noqa: E402
from api.core.redis_client import create_pubsub_redis_client  # noqa: E402

# ==============================================================================
# CORREÇÃO CRÍTICA PARA WINDOWS
# ==============================================================================
if sys.platform == 'win32': 
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# ==============================================================================
# 1) CONFIGURAÇÕES GERAIS E TELEGRAM
# ==============================================================================
DEFAULT_TELEGRAM_TOKEN = "8025852537:AAFj-j0rDK22RV5dZwdlHcxigLwwNwDo3ws"
DEFAULT_CHAT_ID = "-1002634558541"
TELEGRAM_TOKEN = (
    os.getenv("FOUND_FINAL_TELEGRAM_TOKEN")
    or os.getenv("HORSE_FOUND_TELEGRAM_TOKEN")
    or os.getenv("TELEGRAM_TOKEN")
    or DEFAULT_TELEGRAM_TOKEN
)
CHAT_ID = (
    os.getenv("FOUND_FINAL_CHAT_ID")
    or os.getenv("HORSE_FOUND_CHAT_ID")
    or os.getenv("TELEGRAM_CHAT_ID")
    or DEFAULT_CHAT_ID
)
BUTTON_TEXT = (
    os.getenv("FOUND_FINAL_BUTTON_TEXT")
    or os.getenv("HORSE_FOUND_BUTTON_TEXT")
    or "ACESSE A MESA"
)
RESULT_CHANNEL = (
    os.getenv("FOUND_FINAL_RESULT_CHANNEL")
    or os.getenv("HORSE_FOUND_RESULT_CHANNEL")
    or "new_result"
).strip() or "new_result"

MAX_CONCURRENT_REQUESTS = 1
SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
START_BANKROLL = 1000.00
CHIP_VALUE = 1.00
SESSION_PAUSE = 0        
BATCH_SIZE = 10          
FETCH_SIZE = 500         

BASE_DIR = Path(__file__).resolve().parent
CAMINHO_LOGS = str(BASE_DIR / "Logs" / "foundfinal")
STATE_PATH = os.path.join(CAMINHO_LOGS, "placares_state.json")

def write_log(pattern_name: str, result_text: str, hidden_log: str = ""):
    clean_name = re.sub(r'[^A-Za-z0-9_]', '', pattern_name.replace(' ', '_'))
    os.makedirs(CAMINHO_LOGS, exist_ok=True)
    clean_text = re.sub(r'<[^>]+>', '', result_text)
    log_entry = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}]\n{clean_text}\n"
    if hidden_log: log_entry += f"\n[CAIXA PRETA - CONTEXTO HISTÓRICO]\n{hidden_log}\n"
    try:
        with open(os.path.join(CAMINHO_LOGS, f"log_{clean_name}.txt"), "a", encoding="utf-8") as f: 
            f.write(log_entry + "="*60 + "\n")
    except: pass

# ==============================================================================
# 2) GESTÃO FINANCEIRA E PLACARES DINÂMICOS
# ==============================================================================
class BankrollManager:
    def __init__(self, name, max_steps):
        self.name, self.max_steps = name, max_steps
        self.balance = self.start_balance = START_BANKROLL
        self.chip = CHIP_VALUE
        self.total_wins = self.total_losses = self.session_wins = self.session_losses = 0
        self.g_wins = {k: 0 for k in range(max_steps)}
        self.current_batch, self.entries_started_batch, self.entries_finished_batch = 1, 0, 0
        self.batch_wins, self.batch_losses, self.active_bets_now = 0, 0, 0
        self.is_paused, self.pause_until = False, 0

    def update_chip(self): self.chip = CHIP_VALUE * max(1, int(self.balance // START_BANKROLL))
    
    def can_start_new_entry(self) -> bool:
        self.check_session_status(time.time())
        if self.is_paused: return False
        if SESSION_PAUSE > 0 and self.entries_started_batch >= BATCH_SIZE: return False
        return True
        
    def register_entry_start(self): 
        self.entries_started_batch += 1
        self.active_bets_now += 1
        
    def register_entry_end(self, now: float):
        self.entries_finished_batch += 1
        if self.active_bets_now > 0: self.active_bets_now -= 1
        if SESSION_PAUSE <= 0: return 
        
        if self.entries_finished_batch >= self.entries_started_batch and self.entries_started_batch >= BATCH_SIZE:
            if self.current_batch == 1:
                if self.batch_losses == 0: self.is_paused, self.pause_until = True, now + SESSION_PAUSE
                else: self.current_batch, self.entries_started_batch, self.entries_finished_batch = 2, 0, 0
            else: self.is_paused, self.pause_until = True, now + SESSION_PAUSE

    def check_session_status(self, now: float) -> Tuple[bool, str]:
        if self.is_paused and int(self.pause_until - now) <= 0:
            self.is_paused, self.session_wins, self.session_losses = False, 0, 0
            self.current_batch, self.entries_started_batch, self.entries_finished_batch, self.active_bets_now = 1, 0, 0, 0
        return self.is_paused, ""

    def process_win(self, attempt_idx: int, bet_list: List[int], multipliers: List[float], bet_sizes: List[int] = None) -> float:
        self.update_chip()
        safe_idx = min(attempt_idx, len(multipliers) - 1)
        if bet_sizes is None: bet_sizes = [len(bet_list)] * len(multipliers)
        cost = sum(bet_sizes[i] * multipliers[i] * self.chip for i in range(safe_idx + 1))
        profit = (36 * multipliers[safe_idx] * self.chip) - cost
        self.balance += profit; self.total_wins += 1; self.session_wins += 1; self.batch_wins += 1
        if safe_idx in self.g_wins: self.g_wins[safe_idx] += 1
        self.update_chip(); return profit

    def process_loss(self, bet_list: List[int], multipliers: List[float], bet_sizes: List[int] = None) -> float:
        self.update_chip()
        if bet_sizes is None: bet_sizes = [len(bet_list)] * len(multipliers)
        cost = sum(bet_sizes[i] * m * self.chip for i, m in enumerate(multipliers))
        self.balance -= cost; self.total_losses += 1; self.session_losses += 1; self.batch_losses += 1
        self.update_chip(); return cost

    def get_short_dashboard(self) -> str:
        t = self.total_wins + self.total_losses
        acc = (self.total_wins / t * 100) if t > 0 else 0.0
        g_str = " | ".join([f"G{k}: {v}" for k, v in self.g_wins.items() if k < self.max_steps])
        return f"R$ {self.balance:.2f} ({'+' if self.balance>=self.start_balance else ''}{self.balance-self.start_balance:.2f}) [Ficha: R${self.chip:.2f}]\n   └ ✅ {self.total_wins} ❌ {self.total_losses} ({acc:.1f}%)\n   └ [{g_str}]"

    def to_dict(self): return {"balance": self.balance, "total_wins": self.total_wins, "total_losses": self.total_losses, "g_wins": self.g_wins}
    def from_dict(self, d):
        self.balance = d.get("balance", self.start_balance); self.total_wins = d.get("total_wins", 0); self.total_losses = d.get("total_losses", 0)
        self.g_wins = {int(k): v for k, v in d.get("g_wins", {}).items()}; self.update_chip()

class Scoreboard:
    def __init__(self, name: str, title: str, max_steps: int, proj_steps: int = 0):
        self.msg_id, self.name, self.title = None, name, title
        self.bank = BankrollManager(name, max_steps)
        self.proj_bank = BankrollManager(name + "_proj", proj_steps) if proj_steps > 0 else None

    def get_text(self):
        t = f"🏆 <b>{self.title}</b> 🏆\n\n🎯 <b>Desempenho Real ({self.bank.max_steps} Tentativas):</b>\n{self.bank.get_short_dashboard()}\n\n"
        if self.proj_bank: t += f"📊 <b>Projeção Analítica ({self.proj_bank.max_steps} Tentativas):</b>\n{self.proj_bank.get_short_dashboard()}\n\n"
        return t + "<i>Sincronizando Máquina...</i>"

    async def send_initial(self):
        try: self.msg_id = await send_telegram_message(self.get_text())
        except: pass
    async def update(self):
        if self.msg_id: await edit_telegram_message(self.msg_id, self.get_text())

# ==============================================================================
# 3) DECLARAÇÃO GLOBAL DOS PLACARES
# ==============================================================================
BOARD_HORSE_FOUND = Scoreboard("HorseFound", "🐎 HORSE FOUND CLASSIC", 3, 4)

ALL_BOARDS = [BOARD_HORSE_FOUND]
SCOREBOARD_VERSIONS = {
    "HorseFound": "v14"
}

def load_scoreboards():
    try:
        with open(STATE_PATH, "r") as f:
            data = json.load(f)
            for board in ALL_BOARDS:
                if board.name in data and data[board.name].get("version") == SCOREBOARD_VERSIONS.get(board.name, ""):
                    if "real" in data[board.name]: board.bank.from_dict(data[board.name]["real"])
                    if getattr(board, 'proj_bank', None) and "proj" in data[board.name]: board.proj_bank.from_dict(data[board.name]["proj"])
    except: pass

def save_scoreboards():
    os.makedirs(CAMINHO_LOGS, exist_ok=True)
    data = {}
    for board in ALL_BOARDS:
        b_data = {"real": board.bank.to_dict(), "version": SCOREBOARD_VERSIONS.get(board.name, "")}
        if getattr(board, 'proj_bank', None): b_data["proj"] = board.proj_bank.to_dict()
        data[board.name] = b_data
    try:
        with open(STATE_PATH, "w") as f: json.dump(data, f)
    except: pass

# ==============================================================================
# 4) CONEXÃO TELEGRAM E MATEMÁTICA
# ==============================================================================
async def send_telegram_message(text: str, link: Optional[str] = None) -> Optional[int]:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    if link: payload["reply_markup"] = {"inline_keyboard": [[{"text": BUTTON_TEXT, "url": link}]]}
    for _ in range(5):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(url, json=payload, timeout=8) as r:
                    if r.status == 200: return (await r.json())["result"]["message_id"]
                    elif r.status == 429: await asyncio.sleep((await r.json()).get("parameters", {}).get("retry_after", 3) + 1); continue
        except: await asyncio.sleep(1)
    return None

async def edit_telegram_message(msg_id: int, text: str, link: Optional[str] = None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
    payload = {"chat_id": CHAT_ID, "message_id": msg_id, "text": text, "parse_mode": "HTML"}
    if link: payload["reply_markup"] = {"inline_keyboard": [[{"text": BUTTON_TEXT, "url": link}]]}
    for _ in range(5):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(url, json=payload, timeout=8) as r:
                    if r.status == 200: return
                    elif r.status == 429: await asyncio.sleep((await r.json()).get("parameters", {}).get("retry_after", 3) + 1); continue
        except: await asyncio.sleep(1)

async def delete_telegram_message(msg_id: int):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteMessage"
    payload = {"chat_id": CHAT_ID, "message_id": msg_id}
    for _ in range(3):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(url, json=payload, timeout=8) as r:
                    if r.status == 200: return
        except: await asyncio.sleep(1)

def generate_key(): return ''.join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ", k=5))

WHEEL_ORDER = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26]

class RouletteMath:
    @staticmethod
    def get_wheel_neighbors(num: int, count: int = 1) -> Set[int]:
        if num not in WHEEL_ORDER: return set()
        idx = WHEEL_ORDER.index(num); neighbors = set()
        for i in range(1, count + 1):
            neighbors.add(WHEEL_ORDER[(idx - i) % len(WHEEL_ORDER)])
            neighbors.add(WHEEL_ORDER[(idx + i) % len(WHEEL_ORDER)])
        if count == 1:
            if num == 32: neighbors.discard(0); neighbors.add(19)
            if num == 26: neighbors.discard(0); neighbors.add(35)
        return neighbors

    @staticmethod
    def calculate_dynamic_mults(bet_count: int, steps: int, min_profit: float = 10.0, current_cost: float = 0.0) -> List[float]:
        mults = []
        total_cost = current_cost
        for i in range(steps):
            if 36 <= bet_count: return [1.0] * steps
            m = math.ceil(((min_profit + total_cost) / (36 - bet_count)) * 2) / 2.0
            if m < 1.0: m = 1.0
            while 36 * m - (total_cost + bet_count * m) < min_profit: m += 0.5
            mults.append(m)
            total_cost += bet_count * m
        return mults

    @staticmethod
    def get_horse_base_idx(n: int) -> Optional[int]:
        if n in [0, 10, 20, 30]: return None
        t = n % 10
        if t in [1, 4, 7]: return 1
        if t in [2, 5, 8]: return 2
        if t in [3, 6, 9]: return 3
        return None

    @staticmethod
    def get_full_horse_bet(h_list: List[int]) -> List[int]:
        n = []
        for h in h_list:
            if h == 1: n.extend([1, 4, 7, 11, 14, 17, 21, 24, 27, 31, 34, 10])
            elif h == 2: n.extend([2, 5, 8, 12, 15, 18, 22, 25, 28, 32, 35, 20])
            elif h == 3: n.extend([3, 6, 9, 13, 16, 19, 23, 26, 29, 33, 36, 30])
        return sorted(list(set(n)))

TABLES_TO_MONITOR = [
    {"slug": "pragmatic-korean-roulette", "name": "Korean Roulette", "link": "https://lotogreen.bet.br/play/457"},
    {"slug": "pragmatic-speed-roulette-1", "name": "Speed Roulette 1", "link": "https://lotogreen.bet.br/play/556"},
    {"slug": "pragmatic-auto-roulette", "name": "Auto Roulette", "link": "https://lotogreen.bet.br/play/373"},
    {"slug": "pragmatic-mega-roulette-brazilian", "name": "Mega Roulette Brazilian", "link": "https://lotogreen.bet.br/play/6478"},
    {"slug": "pragmatic-mega-roulette", "name": "Mega Roulette", "link": "https://lotogreen.bet.br/play/550"},
    {"slug": "pragmatic-brazilian-roulette", "name": "Brazilian Roulette", "link": "https://lotogreen.bet.br/play/450"},
    {"slug": "pragmatic-auto-mega-roulette", "name": "Auto Mega Roulette", "link": "https://lotogreen.bet.br/play/543"},
    {"slug": "pragmatic-immersive-roulette-deluxe", "name": "Immersive Roulette Deluxe", "link": "https://lotogreen.bet.br/play/8261"},
    {"slug": "pragmatic-roulette-macao", "name": "Roulette Macao", "link": "https://lotogreen.bet.br/play/552"},
    {"slug": "pragmatic-speed-auto-roulette", "name": "Speed Auto Roulette", "link": "https://lotogreen.bet.br/play/481"},
    {"slug": "pragmatic-roulette-1", "name": "Roulette 1", "link": "https://lotogreen.bet.br/play/473"}
]

# ==============================================================================
# MOTOR 1: HORSE FOUND CLÁSSICO 🐎
# ==============================================================================
class HorseFoundEngine:
    @staticmethod
    def analyze(history: List[Dict]) -> Optional[Dict]:
        if len(history) < 20: return None
        raw = [h['val'] for h in history[:50]]
        curr, prev = raw[0], raw[1]
        
        if curr not in [10, 20, 30] or prev in [0, 10, 20, 30]: return None
        
        # O Novo ENO: só opera se o anterior pertencer ao grupo 258.
        if curr == 20 and prev % 10 not in [2, 5, 8]: return None
        
        if any(val in [0, 10, 20, 30] for val in raw[1:4]): return None
        if any(x in [1, 2, 3, 11, 22, 33] for x in raw[1:4]): return None 
        
        sub_value = {10: 9, 20: 18, 30: 36}[curr]
        math_target = abs(prev - sub_value)
        if math_target in [1, 35]: return None 
        
        h_idx = RouletteMath.get_horse_base_idx(math_target)
        redirect_msg = ""
        
        if curr == 10:
            window = raw[1:5]
            t_369_count = sum(1 for x in window if x % 10 in [3, 6, 9])
            has_term_rep = any(window[i]%10 == window[j]%10 for i in range(len(window)) for j in range(i+1, len(window)) if window[i]%10 in [3,6,9])
            
            is_saturated = False
            if t_369_count >= 4: is_saturated = True 
            elif t_369_count == 3 and not has_term_rep: is_saturated = True 
            elif t_369_count == 3 and (window[0]%10 in [3,6,9] and window[1]%10 in [3,6,9] and window[2]%10 in [3,6,9]): is_saturated = True 
            
            if has_term_rep and not is_saturated:
                h_idx = 3 
                redirect_msg = f"\n🔄 <b>Superposição ONE:</b>\nRepetição do Terminal {next(x%10 for x in window if x%10 in [3,6,9])} identificada em {window}.\nAlvo forçado: Cavalo 3!"
            
            elif h_idx == 3: 
                h_prev = RouletteMath.get_horse_base_idx(prev)
                if h_prev is not None and h_prev != 3:
                    h_idx = ({1, 2, 3} - {3, h_prev}).pop()
                    redirect_msg = f"\n🔄 <b>Desvio Triplo (ONE):</b>\nAlvo (369) ➔ Anulado.\nNº Base {prev} (Cavalo {h_prev}) ➔ Anulado.\nRestou Cavalo {h_idx} como alvo!"
                else:
                    return None
                    
        elif curr == 30: # Somente o NEO faz o recalculo do 369. O ENO (20) passa direto sem desvios.
            sub_val = 36
            if h_idx == 3:
                found_new = False
                for i in range(1, 20):
                    temp_math = abs(raw[i] - sub_val)
                    if temp_math in [1, 35]: continue
                    temp_h = RouletteMath.get_horse_base_idx(temp_math)
                    if temp_h is not None and temp_h != 3:
                        h_idx = temp_h
                        redirect_msg = f"\n🔄 <b>Recálculo {curr} (-{sub_val}):</b>\nAlvo 369 evitado.\nUsando histórico ({raw[i]}): |{raw[i]} - {sub_val}| = {temp_math} ➔ Cavalo {h_idx}!"
                        found_new = True
                        break
                if not found_new: return None
        
        if h_idx is None: return None
        protector = {1: 10, 2: 20, 3: 30}[h_idx]
        bet_list = sorted(list(set(RouletteMath.get_full_horse_bet([h_idx]) + [0, protector])))
        catalizador_name = {10: "ONE", 20: "ENO", 30: "NEO"}[curr]
        
        return {
            "pattern_type": "HorseFound",
            "trigger_val": f"HORSEF_{curr}_{generate_key()}",
            "target_name": f"Cavalo {h_idx} + {protector},0",
            "bet_list": bet_list,
            "info": f"🐎 <b>HORSE FOUND CLASSIC [{catalizador_name}]</b>\n\n📚 <b>Últimos 10:</b>\n<code>{' - '.join(map(str, raw[:10]))}</code>\n\n🔗 <b>Catalizador:</b> {curr} ({catalizador_name})\n🧮 <b>Matemática:</b> |{prev} - {sub_value}| = {math_target}{redirect_msg}\n⚡ <b>Ação:</b> Cavalo {h_idx} + Proteção {protector} e 0!",
            "multipliers": RouletteMath.calculate_dynamic_mults(len(bet_list), 3, 10.0),
            "multipliers_proj": RouletteMath.calculate_dynamic_mults(len(bet_list), 4, 10.0),
            "board": BOARD_HORSE_FOUND,
            "steps": ['bet1', 'bet2', 'bet3', 'bet4']
        }

# ==============================================================================
# 6. CONTROLADOR GERAL MULTI-THREAD E STATE MACHINE
# ==============================================================================
class TableBot:
    def __init__(self, cfg):
        self.cfg = cfg
        self.history = []
        self.active_bets = {}
        self.cooldowns = {}
        self._recent_event_ids = deque(maxlen=max(300, FETCH_SIZE * 3))
        self._recent_event_id_set = set()

    def _remember_event_id(self, event_id: str):
        normalized = str(event_id or "").strip()
        if not normalized or normalized in self._recent_event_id_set:
            return
        if len(self._recent_event_ids) >= self._recent_event_ids.maxlen:
            old = self._recent_event_ids.popleft()
            self._recent_event_id_set.discard(old)
        self._recent_event_ids.append(normalized)
        self._recent_event_id_set.add(normalized)

    def _has_seen_event_id(self, event_id: str) -> bool:
        normalized = str(event_id or "").strip()
        return bool(normalized) and normalized in self._recent_event_id_set

    async def initialize_from_db(self):
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

    async def process_result_entry(self, entry: Mapping[str, Any]):
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

        await self.logic_cycle(int(entry.get("val")))

    async def logic_cycle(self, num):
        for bid in list(self.active_bets.keys()):
            await self.handle_active_bet(num, bid)

        signals = []
        res = HorseFoundEngine.analyze(self.history)
        if res: signals.append(res)

        for sig in signals:
            bid = f"{self.cfg['slug']}_{sig['trigger_val']}"
            if bid in self.active_bets or bid in self.cooldowns: continue
            
            actual_bank = sig['board'].bank
            if actual_bank.can_start_new_entry():
                self.cooldowns[bid] = 10
                actual_bank.register_entry_start()
                
                m_real = sig.get('multipliers', [])
                m_proj = sig.get('multipliers_proj', [])
                sig["bet_sizes"] = [len(sig["bet_list"])] * max(len(m_real), len(m_proj))
                if 'steps' not in sig:
                    sig['steps'] = ['bet1', 'bet2', 'bet3', 'bet4']
                
                self.active_bets[bid] = {**sig, "step_idx": 0, "rolled_nums": [], "msg_id": None, "base_text": ""}
                
                await self._send_initial_msg(bid)

    async def _send_initial_msg(self, bid):
        try:
            bet = self.active_bets[bid]
            base_msg = f"🚀 <b>NOVO SINAL {bet['pattern_type'].upper()}</b>\n🎰 <b>{self.cfg['name']}</b>\n\n{bet['info']}\n🎯 <b>Alvo Final:</b> {bet['target_name']}\n🔢 <b>Apostar:</b> {bet['bet_list']}\n✅ <b>ATIRAR (REAL)!</b>"
            bet['base_text'] = base_msg
            bet['msg_id'] = await send_telegram_message(base_msg, self.cfg['link'])
        except: pass

    async def handle_active_bet(self, num, bid):
        try:
            bet = self.active_bets[bid]
            p_type = bet['pattern_type']
            step = bet['step_idx']
            bet['rolled_nums'].append(num)
            rolled_str = " - ".join(map(str, bet['rolled_nums']))
            board = bet['board']

            if step < len(bet['steps']):
                m_real, m_proj = bet['multipliers'], bet.get('multipliers_proj', [])
                b_sizes = bet.get('bet_sizes', [len(bet['bet_list'])] * max(len(m_real), len(m_proj)))
                
                if num in bet['bet_list']:
                    if step < len(m_real):
                        profit = board.bank.process_win(step, bet['bet_list'], m_real, b_sizes)
                        header_status = f"✅ <b>GREEN NO G{step}!</b>"
                        profit_str = f"(+R$ {profit:.2f})"
                    else:
                        loss_real = sum(b_sizes[i] * m * board.bank.chip for i, m in enumerate(m_real))
                        header_status = f"⚠️ <b>RED TÁTICO / GREEN ANALÍTICO (G{step})</b>"
                        profit_str = f"(-R$ {loss_real:.2f})"
                        
                    if board.proj_bank and step < len(m_proj): 
                        board.proj_bank.process_win(step, bet['bet_list'], m_proj, b_sizes)
                        
                    footer = f"\n\n{header_status} {profit_str}\n🎲 <b>Saídas:</b> {rolled_str}\n{board.get_text()}"
                    full_msg = bet['base_text'] + footer
                    
                    if bet['msg_id']: await edit_telegram_message(bet['msg_id'], full_msg, self.cfg['link'])
                    write_log(p_type, full_msg.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", ""))
                    
                    del self.active_bets[bid]; board.bank.register_entry_end(time.time()); save_scoreboards(); await board.update(); return
                
                else:
                    if step == len(m_real) - 1: 
                        board.bank.process_loss(bet['bet_list'], m_real, b_sizes) 
                    
                    if board.proj_bank and step == len(m_proj) - 1: 
                        board.proj_bank.process_loss(bet['bet_list'], m_proj, b_sizes)
                    
                    if step == len(bet['steps']) - 1:
                        loss = sum(b_sizes[i] * m * board.bank.chip for i, m in enumerate(m_real))
                        footer = f"\n\n❌ <b>RED PRINCIPAL</b> (-R$ {loss:.2f})\n🎲 <b>Saídas:</b> {rolled_str}\n{board.get_text()}"
                        full_msg = bet['base_text'] + footer
                        
                        if bet['msg_id']: await edit_telegram_message(bet['msg_id'], full_msg, self.cfg['link'])
                        write_log(p_type, full_msg.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", ""))
                        
                        del self.active_bets[bid]; board.bank.register_entry_end(time.time()); save_scoreboards(); await board.update(); return
                
                bet['step_idx'] += 1
                
        except Exception as e:
            traceback.print_exc()
            if bid in self.active_bets: 
                board = self.active_bets[bid].get('board')
                if board: board.bank.register_entry_end(time.time())
                del self.active_bets[bid]

def _to_epoch(value: Any) -> float:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
    return time.time()


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
    }


async def run_worker():
    bots = [TableBot(table) for table in TABLES_TO_MONITOR]
    bot_by_slug = {bot.cfg["slug"]: bot for bot in bots}

    print("⏳ CONECTANDO AO HISTÓRICO E BAIXANDO RESULTADOS RECENTES...")
    await asyncio.gather(*(bot.initialize_from_db() for bot in bots))

    print("✅ CARREGANDO MEMÓRIA E ENVIANDO PLACARES AO TELEGRAM...")
    load_scoreboards()
    for board in ALL_BOARDS:
        await board.send_initial()
        await asyncio.sleep(1)

    print(f"🚀 FOUND FINAL INICIANDO MONITORAMENTO EM TEMPO REAL VIA REDIS ({RESULT_CHANNEL})...")
    client = create_pubsub_redis_client()
    pubsub = client.pubsub()
    await pubsub.subscribe(RESULT_CHANNEL)

    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            parsed = _parse_result_message(message.get("data"))
            if not parsed:
                continue
            bot = bot_by_slug.get(str(parsed["roulette_id"]))
            if not bot:
                continue
            await bot.process_result_entry(parsed)
    except RedisError:
        traceback.print_exc()
        raise
    finally:
        save_scoreboards()
        try:
            await pubsub.close()
        except Exception:
            pass
        try:
            await client.close()
        except Exception:
            pass


async def main():
    await run_worker()


if __name__ == "__main__":
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass
