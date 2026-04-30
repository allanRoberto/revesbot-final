import os
import asyncio
import aiohttp
import time
import sys
import random
import json
import math
import re
from datetime import datetime
from collections import deque, Counter, defaultdict
from typing import List, Optional, Dict, Tuple, Set, Any
import traceback

# ==============================================================================
# CORREÇÃO CRÍTICA PARA WINDOWS
# ==============================================================================
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# ==============================================================================
# 1) CONFIGURAÇÕES GERAIS E TELEGRAM
# ==============================================================================
TELEGRAM_TOKEN = "8163117177:AAEkKSKUiprvUhcsHYZsjS-USWfElF5jNIs"
CHAT_ID = "-1002903738591"
BUTTON_TEXT = "ACESSE A MESA"

MAX_CONCURRENT_REQUESTS = 1
SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

START_BANKROLL = 1000.00
CHIP_VALUE = 1.00
SESSION_PAUSE = 0        
BATCH_SIZE = 10          
FETCH_SIZE = 150         

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CAMINHO_LOGS = os.path.join(BASE_DIR, "Logs")

def write_log(pattern_name: str, result_text: str, hidden_log: str = ""):
    clean_name = re.sub(r'[^A-Za-z0-9_]', '', pattern_name.replace(' ', '_'))
    filename = os.path.join(CAMINHO_LOGS, f"log_{clean_name}.txt")
    os.makedirs(CAMINHO_LOGS, exist_ok=True)
    clean_text = re.sub(r'<[^>]+>', '', result_text)
    log_entry = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}]\n{clean_text}\n"
    if hidden_log: log_entry += f"\n[CAIXA PRETA - CONTEXTO HISTÓRICO]\n{hidden_log}\n"
    log_entry += "="*60 + "\n"
    try:
        with open(filename, "a", encoding="utf-8") as f: f.write(log_entry)
    except Exception: pass

# ==============================================================================
# 2) GESTÃO FINANCEIRA E PLACARES
# ==============================================================================
class BankrollManager:
    def __init__(self, name, max_steps):
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
        self.pause_until = 0

    def update_chip(self):
        multiplier = max(1, int(self.balance // START_BANKROLL))
        self.chip = CHIP_VALUE * multiplier

    def can_start_new_entry(self) -> bool:
        if self.is_paused: return False
        if self.entries_started_batch >= BATCH_SIZE: return False
        return True

    def register_entry_start(self):
        self.entries_started_batch += 1
        self.active_bets_now += 1

    def register_entry_end(self, now: float):
        self.entries_finished_batch += 1
        if self.active_bets_now > 0: self.active_bets_now -= 1
        self._check_batch_completion(now)

    def _check_batch_completion(self, now: float):
        if self.entries_finished_batch >= self.entries_started_batch and self.entries_started_batch >= BATCH_SIZE:
            if self.current_batch == 1:
                if self.batch_losses == 0:
                    self.is_paused = True
                    self.pause_until = now + SESSION_PAUSE
                else:
                    self.current_batch = 2
                    self.entries_started_batch = 0
                    self.entries_finished_batch = 0
            elif self.current_batch == 2:
                self.is_paused = True
                self.pause_until = now + SESSION_PAUSE

    def check_session_status(self, now: float) -> Tuple[bool, str]:
        if self.is_paused:
            if int(self.pause_until - now) <= 0:
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
        if safe_idx in self.g_wins: self.g_wins[safe_idx] += 1
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
        g_str = " | ".join([f"G{k}: {v}" for k, v in self.g_wins.items() if k < self.max_steps])
        return f"R$ {self.balance:.2f} ({symbol}{profit_total:.2f}) [Ficha: R${self.chip:.2f}]\n   └ ✅ {self.total_wins} ❌ {self.total_losses} ({acc:.1f}%)\n   └ [{g_str}]"

    def to_dict(self):
        return {"balance": self.balance, "total_wins": self.total_wins, "total_losses": self.total_losses, "g_wins": self.g_wins}

    def from_dict(self, data):
        self.balance = data.get("balance", self.start_balance)
        self.total_wins = data.get("total_wins", 0)
        self.total_losses = data.get("total_losses", 0)
        self.g_wins = {int(k): v for k, v in data.get("g_wins", {}).items()}
        self.update_chip()

class Scoreboard:
    def __init__(self, name: str, title: str, max_steps: int, proj_steps: int = 0):
        self.msg_id = None
        self.name = name
        self.title = title
        self.bank = BankrollManager(name, max_steps)
        self.proj_bank = BankrollManager(name + "_proj", proj_steps) if proj_steps > 0 else None

    def get_text(self):
        t = f"🏆 <b>{self.title}</b> 🏆\n\n"
        t += f"🎯 <b>Desempenho Real ({self.bank.max_steps} Tentativas):</b>\n{self.bank.get_short_dashboard()}\n\n"
        if self.proj_bank:
            t += f"📊 <b>Projeção Analítica ({self.proj_bank.max_steps} Tentativas):</b>\n{self.proj_bank.get_short_dashboard()}\n\n"
        t += f"<i>Sincronizando Máquina...</i>"
        return t

    async def send_initial(self):
        self.msg_id = await send_telegram_message(self.get_text())

    async def update(self):
        if self.msg_id: await edit_telegram_message(self.msg_id, self.get_text())

# ==============================================================================
# PLACARES OFICIAIS
# ==============================================================================
BOARD_HORSE_FOUND = Scoreboard("HorseFound", "🐎 HORSE FOUND", 3, 4)

ALL_BOARDS = [BOARD_HORSE_FOUND]

SCOREBOARD_VERSIONS = {
    "HorseFound": "v8"        
}

def load_scoreboards():
    try:
        with open(os.path.join(CAMINHO_LOGS, "placares_state.json"), "r") as f:
            data = json.load(f)
            for board in ALL_BOARDS:
                if board.name in data and hasattr(board, 'bank'):
                    b_data = data[board.name]
                    if b_data.get("version") == SCOREBOARD_VERSIONS.get(board.name, ""):
                        if "real" in b_data: board.bank.from_dict(b_data["real"])
                        if getattr(board, 'proj_bank', None) and "proj" in b_data: 
                            board.proj_bank.from_dict(b_data["proj"])
    except: pass

def save_scoreboards():
    os.makedirs(CAMINHO_LOGS, exist_ok=True)
    data = {}
    for board in ALL_BOARDS:
        if hasattr(board, 'bank'):
            b_data = {"real": board.bank.to_dict()}
            if getattr(board, 'proj_bank', None): b_data["proj"] = board.proj_bank.to_dict()
            b_data["version"] = SCOREBOARD_VERSIONS.get(board.name, "")
            data[board.name] = b_data
    try:
        with open(os.path.join(CAMINHO_LOGS, "placares_state.json"), "w") as f:
            json.dump(data, f)
    except: pass

# ==============================================================================
# 3) CONEXÃO TELEGRAM
# ==============================================================================
async def send_telegram_message(text: str, link: Optional[str] = None) -> Optional[int]:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    if link: payload["reply_markup"] = {"inline_keyboard": [[{"text": BUTTON_TEXT, "url": link}]]}
    for attempt in range(5):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=8) as r:
                    if r.status == 200: return (await r.json())["result"]["message_id"]
                    elif r.status == 429: 
                        wait_time = (await r.json()).get("parameters", {}).get("retry_after", 3)
                        await asyncio.sleep(wait_time + 1)
                        continue
        except Exception: await asyncio.sleep(1)
    return None

async def edit_telegram_message(msg_id: int, text: str, link: Optional[str] = None):
    async def _do_edit():
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
        payload = {"chat_id": CHAT_ID, "message_id": msg_id, "text": text, "parse_mode": "HTML"}
        if link: payload["reply_markup"] = {"inline_keyboard": [[{"text": BUTTON_TEXT, "url": link}]]}
        for attempt in range(6):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=payload, timeout=8) as r:
                        if r.status == 200: return
                        elif r.status == 429: 
                            wait_time = (await r.json()).get("parameters", {}).get("retry_after", 3)
                            await asyncio.sleep(wait_time + 1)
                            continue
            except Exception: await asyncio.sleep(1)
    asyncio.create_task(_do_edit())

# ==============================================================================
# 4) UTILITÁRIOS MATEMÁTICOS E TEMPO
# ==============================================================================
def generate_key(): return ''.join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ", k=5))

class RouletteMath:
    @staticmethod
    def calculate_dynamic_mults(bet_count: int, steps: int, min_profit: float = 10.0, base_mults: List[float] = None) -> List[float]:
        if base_mults is not None and len(base_mults) == steps: return base_mults
        mults = []
        total_cost = 0.0
        for i in range(steps):
            if 36 <= bet_count: return [1.0] * steps
            m = (min_profit + total_cost) / (36 - bet_count)
            m = math.ceil(m * 2) / 2.0
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
    def get_full_horse_bet(horse_idx_list: List[int]) -> List[int]:
        nums = []
        for h in horse_idx_list:
            if h == 1: nums.extend([1, 4, 7, 11, 14, 17, 21, 24, 27, 31, 34, 10])
            elif h == 2: nums.extend([2, 5, 8, 12, 15, 18, 22, 25, 28, 32, 35, 20])
            elif h == 3: nums.extend([3, 6, 9, 13, 16, 19, 23, 26, 29, 33, 36, 30])
        return sorted(list(set(nums)))

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
# MOTOR 1: HORSE FOUND 🐎 (GESTÃO 1x 2x 2x)
# ==============================================================================
class HorseFoundEngine:
    @staticmethod
    def analyze(history: List[Dict]) -> Optional[Dict]:
        if len(history) < 20: return None
        raw = [h['val'] for h in history[:50]]
        
        curr_hit = raw[0] 
        if curr_hit not in [10, 20, 30]: return None
        
        prev_num = raw[1]
        if prev_num in [0, 10, 20, 30]: return None
        
        # Filtro de cancelamento se houver T0 nas 3 rodadas antes da formação
        if any(val in [0, 10, 20, 30] for val in raw[2:5]):
            return None
        
        sub_value = 0
        if curr_hit == 10:
            sub_value = 9
        elif curr_hit == 20:
            sub_value = 25
        elif curr_hit == 30:
            sub_value = 36
            
        math_target = abs(prev_num - sub_value)
        h_idx = RouletteMath.get_horse_base_idx(math_target)
        
        redirect_msg = ""
        
        # Desvio 369
        if h_idx == 3:
            h_idx = RouletteMath.get_horse_base_idx(prev_num)
            redirect_msg = f" (Desvio 369 -> Formação {prev_num})"
            if h_idx == 3 or h_idx is None:
                back_num = raw[2]
                h_idx = RouletteMath.get_horse_base_idx(back_num)
                redirect_msg = f" (Desvio 369 Duplo -> Antecessor {back_num})"
                if h_idx == 3 or h_idx is None:
                    return None
                    
        if h_idx is None: return None
            
        bet_list = sorted(list(set(RouletteMath.get_full_horse_bet([h_idx]) + [0])))
        
        # GESTÃO TÁTICA RIGOROSA: 1x 2x 2x
        mults = [1.0, 2.0, 2.0]
        m_proj = RouletteMath.calculate_dynamic_mults(len(bet_list), 4, 10.0)
        
        last_10_str = " - ".join(map(str, raw[:10]))
        
        info = (f"🐎 <b>HORSE FOUND (CAVALOS)</b>\n\n"
                f"📚 <b>Últimos 10 Números:</b>\n<code>{last_10_str}</code>\n\n"
                f"🔗 <b>Gatilho Fixado:</b> {curr_hit}\n"
                f"🧮 <b>Matemática:</b> |{prev_num} - {sub_value}| = {math_target}{redirect_msg}\n"
                f"⚡ <b>Ação:</b> Cavalo {h_idx} + 0!")
                
        return {
            "pattern_type": "HorseFound",
            "trigger_val": f"HORSEF_CAV_{curr_hit}_{prev_num}_{math_target}_{generate_key()}",
            "target_name": f"Cavalo {h_idx} + 0",
            "bet_list": bet_list,
            "info": info,
            "multipliers": mults,
            "multipliers_proj": m_proj,
            "gale_msg": "Gestão Tática (3x: 1x-2x-2x) / Projeção Analítica (4x)",
            "board": BOARD_HORSE_FOUND,
            "hidden_log": f"HorseFound Cavalo: Gatilho {curr_hit}. Anterior {prev_num}. Alvo Math {math_target}. Cav Final {h_idx}.",
            "steps": ['bet1', 'bet2', 'bet3', 'bet4']
        }

# ==============================================================================
# 6. CONTROLADOR GERAL MULTI-THREAD E STATE MACHINE
# ==============================================================================
class TableBot:
    def __init__(self, cfg):
        self.cfg = cfg
        self.history: List[Dict] = [] 
        self.active_bets: Dict[str, Dict] = {} 
        self.cooldowns: Dict[str, int] = {} 

    async def initialize(self, api):
        self.history = []
        self.cooldowns = {}
        for attempt in range(10):
            try:
                async with SEMAPHORE:
                    await asyncio.sleep(random.uniform(0.5, 2.0))
                    res = await api.api(self.cfg['slug'], num_results=FETCH_SIZE)
                if res and "results" in res:
                    raw_nums = [int(x) for x in res["results"] if str(x).isdigit()]
                    now = time.time()
                    for i, n in enumerate(reversed(raw_nums)):
                        ts = now - (len(raw_nums) - i) * 45
                        self.history.insert(0, {'val': n, 'key': generate_key(), 'ts': ts})
                    break
            except Exception as e: 
                print(f"⚠️ Aguardando API para {self.cfg['name']} (Tentativa {attempt+1}/10)...")
                await asyncio.sleep(3)

    async def process_batch(self, new_numbers: List[int]):
        incoming = list(reversed(new_numbers))
        now = time.time()
        for num in incoming:
            for c_key in list(self.cooldowns.keys()):
                self.cooldowns[c_key] -= 1
                if self.cooldowns[c_key] <= 0: del self.cooldowns[c_key]
                    
            trigger_id = f"live_{generate_key()}"
            self.history.insert(0, {'val': num, 'key': trigger_id, 'ts': now})
            if len(self.history) > FETCH_SIZE: self.history.pop()
            await self.logic_cycle(num, now, trigger_id)

    async def logic_cycle(self, current_num: int, current_ts: float, trigger_id: str):
        for bet_id in list(self.active_bets.keys()):
            await self.handle_active_bet(current_num, bet_id, current_ts)

        signals = []
        
        sig_horse = HorseFoundEngine.analyze(self.history)
        if sig_horse: signals.append(sig_horse)
            
        for sig in signals:
            p_type = sig['pattern_type']
            bet_id = f"{self.cfg['slug']}_{sig['trigger_val']}_{trigger_id}"
            
            is_duplicate = False
            for act_id, act_data in self.active_bets.items():
                if act_data['pattern_type'] == p_type and act_data['target_name'] == sig['target_name']:
                    is_duplicate = True
                    break
            if is_duplicate: continue
            
            if bet_id in self.active_bets: continue
            
            if sig['board']:
                actual_bank = sig['board'].bank
                paused, _ = actual_bank.check_session_status(current_ts)
                if not paused and actual_bank.can_start_new_entry():
                    if bet_id not in self.cooldowns:
                        self.cooldowns[bet_id] = 10
                        actual_bank.register_entry_start()
                        await self.start_bet(sig, bet_id)
            else: 
                if bet_id not in self.cooldowns:
                    self.cooldowns[bet_id] = 10
                    await self.start_bet(sig, bet_id)

    async def _send_initial_bet_msg(self, bet_id: str):
        try:
            bet = self.active_bets[bet_id]
            
            info_txt = f"🔁 <b>3 Tentativas Táticas / 4 Analíticas</b>"
            current_last_10 = " - ".join([str(h['val']) for h in self.history[:10]])
            header = f"🚀 <b>NOVO SINAL {bet['pattern_type'].upper()}</b>"
            
            info_base = bet['signal_info']
            if "📚 <b>Últimos 10 Números:</b>" not in info_base:
                lines = info_base.split("\n")
                lines.insert(2, f"📚 <b>Últimos 10 Números:</b>\n<code>{current_last_10}</code>\n")
                updated_signal_info = "\n".join(lines)
            else:
                lines = info_base.split("\n")
                for i, line in enumerate(lines):
                    if "Últimos 10 Números" in line:
                        if i + 1 < len(lines): lines[i+1] = f"<code>{current_last_10}</code>"
                updated_signal_info = "\n".join(lines)
            
            base_msg = (f"{header}\n"
                        f"🎰 <b>{self.cfg['name']}</b>\n\n"
                        f"{updated_signal_info}\n"
                        f"🎯 <b>Alvo Final:</b> {bet['target_name']}\n"
                        f"🔢 <b>Apostar:</b> {bet['bet_list']}\n"
                        f"{info_txt}\n{bet['gale_msg']}")
            
            bet['base_text'] = base_msg
            
            if "wait" in bet['steps'][0]:
                txt_atir = f"{base_msg}\n\n⏳ <b>Cenário Raro!</b>\nAguardando delay de mesa."
            else:
                txt_atir = f"{base_msg}\n\n✅ <b>ATIRAR (REAL)!</b>\nIniciando Ataque na Mesa!"
            
            mid = await send_telegram_message(txt_atir, self.cfg['link'])
            bet['msg_id'] = mid
        except Exception as e: pass

    async def start_bet(self, signal: Dict, bet_id: str):
        try:
            bet_list = signal['bet_list']
            mults = signal.get("multipliers", [1.0, 2.0, 4.0])
            mults_proj = signal.get("multipliers_proj", [])
            board_to_use = signal['board'] 
            steps = signal['steps']
            
            self.active_bets[bet_id] = {
                "pattern_type": signal['pattern_type'],
                "msg_id": None, 
                "base_text": "",
                "signal_info": signal['info'],
                "target_name": signal['target_name'],
                "bet_list": bet_list, 
                "steps": steps, 
                "step_idx": 0, 
                "rolled_nums": [],
                "multipliers": mults, 
                "multipliers_proj": mults_proj, 
                "hidden_log": signal.get("hidden_log", ""), 
                "board": board_to_use,
                "gale_msg": signal.get("gale_msg", "")
            }
            
            await self._send_initial_bet_msg(bet_id)
        except Exception as e: pass

    async def handle_active_bet(self, num, bet_id, current_ts):
        try:
            bet = self.active_bets.get(bet_id)
            if not bet: return

            p_type = bet['pattern_type']
            current_step = bet['steps'][bet['step_idx']]
            
            if current_step.startswith('wait'):
                bet['step_idx'] += 1
                return
            
            bet['rolled_nums'].append(num)
            rolled_str = " - ".join(map(str, bet['rolled_nums']))

            active_board = bet['board'] 
            bank_real = active_board.bank
            bank_proj = active_board.proj_bank

            if current_step.startswith('bet'):
                attempt_idx = int(current_step[-1]) - 1 
                mults_real = bet['multipliers']
                mults_proj = bet['multipliers_proj']

                if num in bet['bet_list']:
                    profit_str = ""
                    safe_real_idx = min(attempt_idx, len(mults_real) - 1)
                    safe_proj_idx = min(attempt_idx, len(mults_proj) - 1) if mults_proj else 0
                    
                    if attempt_idx < len(mults_real):
                        profit = bank_real.process_win(attempt_idx, bet['bet_list'], mults_real)
                        profit_str = f"(+R$ {profit:.2f})"
                    else:
                        loss_tatic = sum(m * bank_real.chip for m in mults_real for n in bet['bet_list'])
                        profit_str = f"(-R$ {loss_tatic:.2f} Tática / GREEN Analítica)"
                        
                    if bank_proj and attempt_idx < len(mults_proj):
                        c_proj = bank_proj.chip
                        c_cost = sum(len(bet['bet_list']) * mults_proj[i] * c_proj for i in range(safe_proj_idx + 1))
                        payout = 36 * mults_proj[safe_proj_idx] * c_proj
                        profit_proj = payout - c_cost
                        bank_proj.process_win(attempt_idx, bet['bet_list'], mults_proj)
                        
                        if attempt_idx >= len(mults_real): profit_str = f"(-R$ {loss_tatic:.2f} Tática / +R$ {profit_proj:.2f} Analítica)"
                            
                    footer = f"\n\n✅ <b>GREEN NO G{attempt_idx}!</b> {profit_str}\n🎲 <b>Saídas no Ataque:</b> {rolled_str}\n{active_board.get_text()}"
                    
                    del self.active_bets[bet_id]
                    bank_real.register_entry_end(current_ts)
                    write_log(p_type, bet['base_text'] + footer, bet['hidden_log'])
                    save_scoreboards()
                    
                    if bet['msg_id']: 
                        asyncio.create_task(edit_telegram_message(bet['msg_id'], bet['base_text'] + footer, self.cfg['link']))
                        await active_board.update()
                    return

                else:
                    if attempt_idx == len(mults_real) - 1: bank_real.process_loss(bet['bet_list'], mults_real)
                    if bank_proj and attempt_idx == len(mults_proj) - 1: bank_proj.process_loss(bet['bet_list'], mults_proj)
                            
                    bet['step_idx'] += 1
                    
                    if bet['step_idx'] >= len(bet['steps']):
                        loss_val_tatic = sum(m * bank_real.chip for m in mults_real for n in bet['bet_list'])
                        footer = f"\n\n❌ <b>RED PRINCIPAL</b> (-R$ {loss_val_tatic:.2f})\n🎲 <b>Saídas no Ataque:</b> {rolled_str}\n{active_board.get_text()}"
                        
                        del self.active_bets[bet_id]
                        bank_real.register_entry_end(current_ts)
                        write_log(p_type, bet['base_text'] + footer, bet['hidden_log'])
                        save_scoreboards()
                        
                        if bet['msg_id']: 
                            asyncio.create_task(edit_telegram_message(bet['msg_id'], bet['base_text'] + footer, self.cfg['link']))
                            await active_board.update()
                        return
                    else:
                        return 
        except Exception as e:
            print(f"Error in handle_active_bet for {bet_id}: {e}")
            traceback.print_exc()
            if bet_id in self.active_bets: del self.active_bets[bet_id]

async def monitor_realtime(bot, api):
    while True:
        try:
            try:
                async with SEMAPHORE:
                    res = await asyncio.wait_for(api.api(bot.cfg['slug'], num_results=FETCH_SIZE), timeout=15)
            except asyncio.TimeoutError:
                await asyncio.sleep(3); continue
            except Exception:
                await asyncio.sleep(3); continue
            
            if res and "results" in res:
                raw_list = [int(x) for x in res["results"] if str(x).isdigit()]
                new_items = []
                
                if not bot.history: new_items = raw_list
                else:
                    history_vals = [h['val'] for h in bot.history[:20]]
                    cut_idx = len(raw_list)
                    for i in range(len(raw_list)):
                        match, check_length = True, min(len(history_vals), len(raw_list) - i)
                        if check_length == 0: match = False
                        for j in range(check_length):
                            if raw_list[i+j] != history_vals[j]: match = False; break
                        if match and check_length > 0: cut_idx = i; break
                    new_items = raw_list[:cut_idx]

                if new_items: await bot.process_batch(new_items)
            await asyncio.sleep(2)
        except Exception as e: 
            print(f"Monitor Loop Error: {e}")
            await asyncio.sleep(5)

async def main():
    if not os.path.exists("core/api.py"): return
    try: from core.api import RouletteAPI
    except ImportError:
        print("\n❌ ERRO: A pasta 'core' ou o arquivo 'api.py' não foi encontrado neste diretório.")
        return
    
    api = RouletteAPI()
    bots = [TableBot(t) for t in TABLES_TO_MONITOR]
    
    print("⏳ CONECTANDO ÀS MESAS E BAIXANDO HISTÓRICO RECENTE...")
    await asyncio.gather(*(bot.initialize(api) for bot in bots))
    
    print("✅ CARREGANDO MEMÓRIA E ENVIANDO PLACARES AO TELEGRAM...")
    load_scoreboards()
    
    for board in ALL_BOARDS:
        await board.send_initial()
        await asyncio.sleep(1)
    
    print("🚀 SYSTEM HORSE FOUND PURE INICIANDO MONITORAMENTO EM TEMPO REAL...")
    tasks = [monitor_realtime(bot, api) for bot in bots]
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: pass