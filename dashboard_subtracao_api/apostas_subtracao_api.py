import sys
import os
import json
import time
import signal
import threading
import collections
from datetime import datetime, timezone
from typing import List, Dict, Optional
import asyncio
import random

try:
    from core.api import RouletteAPI
except ImportError:
    pass

sys.stdout.reconfigure(encoding="utf-8")
os.system("")

# ========================= MAPAS E LISTAS ====================================
MAPA_CAVALOS_147 = [1, 4, 7, 14, 17, 21, 24, 27, 31, 34]
MAPA_CAVALOS_258 = [2, 5, 8, 12, 15, 18, 25, 28, 32, 35]
LISTA_VALIDA = set(MAPA_CAVALOS_147 + MAPA_CAVALOS_258)
GATILHOS = {10, 20, 30}
INVALIDOS_DIRETOS = {11, 22, 33}

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
    {"slug": "pragmatic-roulette-1", "name": "Roulette 1", "link": "https://lotogreen.bet.br/play/473"},
    {"slug": "pragmatic-roulette-2", "name": "Roulette 2", "link": "https://lotogreen.bet.br/play/457"},
    {"slug": "pragmatic-roulete-3", "name": "Roulette 3", "link": "https://lotogreen.bet.br/play/476"},
    {"slug": "pragmatic-vip-auto-roulette", "name": "VIP Auto Roulette", "link": "https://lotogreen.bet.br/play/457"},
    {"slug": "pragmatic-vip-roulette", "name": "VIP Roulette", "link": "https://lotogreen.bet.br/play/457"},
    {"slug": "pragmatic-turkish-mega-roulette", "name": "Turkish Mega Roulette", "link": "https://lotogreen.bet.br/play/457"},
    {"slug": "pragmatic-italian-mega-roulette", "name": "Italian Mega Roulette", "link": "https://lotogreen.bet.br/play/457"},
    {"slug": "pragmatic-turkish-roulette", "name": "Turkish Roulette", "link": "https://lotogreen.bet.br/play/457"},
    {"slug": "pragmatic-speed-roulette-2", "name": "Speed Roulette 2", "link": "https://lotogreen.bet.br/play/457"},
    {"slug": "pragmatic-romanian-roulette", "name": "Romanian Roulette", "link": "https://lotogreen.bet.br/play/457"},
    {"slug": "pragmatic-roulette-italian", "name": "Roulette Italian", "link": "https://lotogreen.bet.br/play/457"},
    {"slug": "pragmatic-german-roulette", "name": "German Roulette", "link": "https://lotogreen.bet.br/play/457"},
    {"slug": "pragmatic-russian-roulette", "name": "Russian Roulette", "link": "https://lotogreen.bet.br/play/457"},
    {"slug": "pragmatic-roulette-italia-tricolore", "name": "Roulette Italia Tricolore", "link": "https://lotogreen.bet.br/play/457"},
    {"slug": "pragmatic-vietnamese-roulette", "name": "Vietnamese Roulette", "link": "https://lotogreen.bet.br/play/457"}
]

TABLES_DICT = {t["slug"]: t for t in TABLES_TO_MONITOR}

# ========================= CONFIGURAÇÕES =====================================
BASE_DIR             = os.path.dirname(os.path.abspath(__file__))
CAMINHO_APOSTAS      = os.path.join(BASE_DIR, "APOSTAS")
CAMINHO_LOGS         = os.path.join(BASE_DIR, "Logs")
CAMINHO_PROCESSADOS  = os.path.join(CAMINHO_LOGS, "Processados_Sub_Api")
STATE_FILE           = os.path.join(CAMINHO_LOGS, "subtracao_api_estado.json")
RESULTS_DIR          = os.path.join(CAMINHO_LOGS, "Resultados_Sub_Api")
CONFIG_FILE          = os.path.join(CAMINHO_LOGS, "subtracao_api_config.json")

_CFG_DEFAULTS = {
    "banca_inicial": 2500.0,
    "ficha_e1": 1.0,
    "ficha_e2": 1.0,
    "ficha_e3": 1.5,
    "ficha_e4": 2.5,
    "payout_bruto": 36.0, #Payout do Pleno
    "poll_interval": 3,
    "stop_loss_pct": 20.0,
    "take_profit_pct": 20.0,
    "max_simultaneas": 4,
}

CFG = dict(_CFG_DEFAULTS)

def carregar_config():
    global CFG
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            CFG.update(data)
    except Exception:
        pass

carregar_config()

# ========================= ESTADO GLOBAL =====================================
_rlock = threading.RLock()
START_TIME = time.time() - 30 # margem

_placar = {"green": 0, "red": 0, "anulado": 0}
_banca_atual = CFG["banca_inicial"]

# ID da roleta -> dit de estado
_operacoes_ativas = {} 

_historicos = {}
_hist_lock = threading.RLock()
MAX_HISTORICO = 300
_stop_event = threading.Event()
_log_eventos = collections.deque(maxlen=30)
_roletas_ativas = 0
_resultados_recentes = collections.deque(maxlen=20)

def _add_evento(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    with _rlock:
        _log_eventos.appendleft(f"[{ts}] {msg}")
        print(f"[{ts}] {msg}")

def signal_handler(sig, frame):
    _stop_event.set()
    _add_evento("Encerramento solicitado")

# ========================= MOTOR API ASSÍNCRONO ==============================
MAX_CONCURRENT_REQUESTS = 3
SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
FETCH_SIZE = 150

def generate_key():
    chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return ''.join(random.choices(chars, k=5))

def _inserir_spin_ordenado(buf: List[dict], entry: dict) -> bool:
    if not isinstance(entry, dict) or not entry.get("chave"):
        return False
    chave_nova = entry.get("chave")
    for item in buf:
        if isinstance(item, dict) and item.get("chave") == chave_nova:
            return False
    ts_novo = entry.get("timestamp_epoch")
    if isinstance(ts_novo, (int, float)):
        pos = 0
        while pos<len(buf):
            atual = buf[pos]
            ts_atual = atual.get("timestamp_epoch") if isinstance(atual, dict) else None
            if not isinstance(ts_atual, (int, float)) or ts_novo >= ts_atual:
                break
            pos += 1
        buf.insert(pos, entry)
    else:
        buf.insert(0, entry)
    if len(buf) > MAX_HISTORICO:
        del buf[MAX_HISTORICO:]
    return True

async def monitor(roleta_slug: str, api):
    while not _stop_event.is_set():
        try:
            try:
                async with SEMAPHORE:
                    res = await asyncio.wait_for(api.api(roleta_slug, num_results=FETCH_SIZE), timeout=8)
            except Exception:
                await asyncio.sleep(2)
                continue
                
            if res and "results" in res:
                raw_list = [int(x) for x in res["results"] if str(x).isdigit()]
                
                with _hist_lock:
                    if roleta_slug not in _historicos:
                        _historicos[roleta_slug] = []
                        for n in reversed(raw_list):
                            entry = {
                                "numero": n,
                                "chave": generate_key(),
                                "timestamp_epoch": time.time()
                            }
                            _inserir_spin_ordenado(_historicos[roleta_slug], entry)
                    else:
                        buf = _historicos[roleta_slug]
                        history_vals = [h.get("numero") for h in buf[:20]]
                        cut_idx = len(raw_list)
                        for i in range(len(raw_list)):
                            match = True
                            check_length = min(len(history_vals), len(raw_list) - i)
                            if check_length == 0: match = False
                            for j in range(check_length):
                                if raw_list[i+j] != history_vals[j]: 
                                    match = False; break
                            if match and check_length > 0:
                                cut_idx = i; break
                                
                        new_items = raw_list[:cut_idx]
                        if new_items:
                            for num in reversed(new_items):
                                entry = {
                                    "numero": num,
                                    "chave": generate_key(),
                                    "timestamp_epoch": time.time()
                                }
                                if _inserir_spin_ordenado(buf, entry):
                                    processar_novo_spin(roleta_slug, entry, buf)
            await asyncio.sleep(CFG.get("poll_interval", 3))
        except Exception:
            await asyncio.sleep(5)

async def main_api_loop():
    try:
        api = RouletteAPI()
    except Exception as e:
        _add_evento(f"Erro ao instanciar API: {e}")
        return
        
    _add_evento("[API] Inicializando Monitores assíncronos...")
    tasks = []
    for roleta in TABLES_TO_MONITOR:
        roleta_slug = roleta["slug"]
        tasks.append(monitor(roleta_slug, api))
    
    with _hist_lock:
        global _roletas_ativas
        _roletas_ativas = len(tasks)
        
    await asyncio.gather(*tasks)

def thread_api():
    asyncio.run(main_api_loop())

# ========================= PERSISTÊNCIA ======================================
def salvar_estado(limite_atingido=""):
    os.makedirs(CAMINHO_LOGS, exist_ok=True)
    with _rlock:
        estado = {
            "placar": _placar,
            "banca_atual": _banca_atual,
            "operacoes_ativas": {k: v for k, v in _operacoes_ativas.items()},
            "resultados_recentes": list(_resultados_recentes),
            "atualizado_em": datetime.now().isoformat(),
            "limite_atingido": limite_atingido
        }
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(estado, f, ensure_ascii=False, indent=2)
    except:
        pass

def criar_json_aposta(op):
    roleta = op["roleta"]
    fid = op["formacao_id"]
    filename = f"{roleta}_subtr_api_{op['gatilho']}_{fid}.json"
    filepath = os.path.join(CAMINHO_APOSTAS, filename)
    
    if op["pausa_restante"] > 0:
        if os.path.exists(filepath):
            try: os.remove(filepath)
            except: pass
        return

    ent_idx = op["entradas_feitas"] + 1
    if ent_idx == 1: ficha = CFG["ficha_e1"]
    elif ent_idx == 2: ficha = CFG["ficha_e2"]
    elif ent_idx == 3: ficha = CFG["ficha_e3"]
    else: ficha = CFG["ficha_e4"]
    
    data = {
        "estado": "APOSTAR",
        "controlador": "PRODUTOR_API",
        "id_mesa": roleta,
        "url": TABLES_DICT.get(roleta, {}).get("link", ""),
        "formacao_id": fid,
        "valor_ficha": ficha,
        "banca_atual": _banca_atual,
        "numeros": op["alvos"],
        "entrada_atual": ent_idx,
        "gatilho": op["gatilho"],
        "alvo_subtracao": op["alvo_sub"],
        "timestamp": datetime.now().isoformat()
    }
    
    os.makedirs(CAMINHO_APOSTAS, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def apagar_json_aposta(op):
    roleta = op["roleta"]
    fid = op["formacao_id"]
    filename = f"{roleta}_subtr_api_{op['gatilho']}_{fid}.json"
    filepath = os.path.join(CAMINHO_APOSTAS, filename)
    if os.path.exists(filepath):
        try: os.remove(filepath)
        except: pass

def registrar_resultado(op, resultado, stop_ent=False):
    global _banca_atual
    apagar_json_aposta(op)
    
    variacao = 0
    if resultado == "GREEN":
        _placar["green"] += 1
        custo = 0
        feitas = op["entradas_feitas"]
        if feitas >= 1: custo += CFG["ficha_e1"] * len(op["alvos"])
        if feitas >= 2: custo += CFG["ficha_e2"] * len(op["alvos"])
        if feitas >= 3: custo += CFG["ficha_e3"] * len(op["alvos"])
        if feitas >= 4: custo += CFG["ficha_e4"] * len(op["alvos"])
        
        if feitas == 1: premio = CFG["ficha_e1"] * CFG["payout_bruto"]
        elif feitas == 2: premio = CFG["ficha_e2"] * CFG["payout_bruto"]
        elif feitas == 3: premio = CFG["ficha_e3"] * CFG["payout_bruto"]
        else: premio = CFG["ficha_e4"] * CFG["payout_bruto"]
        
        variacao = premio - custo
        
    elif resultado == "RED":
        _placar["red"] += 1
        custo = 0
        feitas = op["entradas_feitas"]
        if feitas >= 1: custo += CFG["ficha_e1"] * len(op["alvos"])
        if feitas >= 2: custo += CFG["ficha_e2"] * len(op["alvos"])
        if feitas >= 3: custo += CFG["ficha_e3"] * len(op["alvos"])
        if feitas >= 4: custo += CFG["ficha_e4"] * len(op["alvos"])
        variacao = -custo
        
    elif resultado == "ANULAR":
        _placar["anulado"] += 1
        variacao = 0
        
    _banca_atual += variacao
    
    res_dict = {
        "roleta": op["roleta"],
        "formacao_id": op["formacao_id"],
        "datahora": datetime.now().isoformat(),
        "resultado": resultado,
        "entrada_green": op["entradas_feitas"] if resultado == "GREEN" else None,
        "variacao": variacao,
        "banca_atual": _banca_atual,
        "gatilho": op["gatilho"],
        "n_anterior": op["n_prev"],
        "alvo_sub": op["alvo_sub"],
        "grupo": op["grupo"],
        "alvos": op["alvos"],
        "historico_resultados": op["resultados_girados"],
        "historico_pausas": op["historico_pausas"],
    }
    
    _resultados_recentes.append(res_dict)
    
    os.makedirs(RESULTS_DIR, exist_ok=True)
    res_file = os.path.join(RESULTS_DIR, f"{op['roleta']}_{op['formacao_id']}.json")
    try:
        with open(res_file, "w", encoding="utf-8") as f:
            json.dump(res_dict, f, indent=2)
    except: pass
    
    _add_evento(f"[{resultado}] Roleta: {op['roleta']} | Var: {variacao:.2f} | Gat: {op['gatilho']} -> Alvo: {op['alvo_sub']}")
    
    limite = ""
    var_total = _banca_atual - CFG["banca_inicial"]
    if var_total <= - (CFG["banca_inicial"] * CFG["stop_loss_pct"] / 100):
        limite = "STOP LOSS ATINGIDO"
    elif var_total >= (CFG["banca_inicial"] * CFG["take_profit_pct"] / 100):
        limite = "TAKE PROFIT ATINGIDO"
        
    if limite:
        salvar_estado(limite)
        _add_evento(f"❗️ {limite}")
        _stop_event.set()

# ========================= LÓGICA DE NEGÓCIO ==================================
def obter_alvos(n_prev):
    if n_prev is None or not isinstance(n_prev, int): return None
    
    val = n_prev
    target_group = 0
    math_steps = []
    
    while True:
        prev_val = val
        val = val - 36
        abs_val = abs(val)
        math_steps.append(f"{prev_val} - 36 = {val}")
        
        if abs_val in [11, 22, 33, 10, 20, 30]:
            return None
            
        term = abs_val % 10
        if term in [1, 4, 7]: 
            target_group = 1
            break
        elif term in [2, 5, 8]: 
            target_group = 2
            break
        elif term in [3, 6, 9]: 
            continue
        else: 
            return None
            
    if target_group == 1:
        alvos_final = MAPA_CAVALOS_147 + [10, 0]
        return {"grupo": "Absolu 1-4-7", "alvos": alvos_final, "alvo_sub": "Proteção 10"}
    elif target_group == 2:
        alvos_final = MAPA_CAVALOS_258 + [20, 0]
        return {"grupo": "Absolu 2-5-8", "alvos": alvos_final, "alvo_sub": "Proteção 20"}

def verificar_turbulencia(atual, ref):
    if not isinstance(atual, int) or not isinstance(ref, int): return False
    
    if atual != 0 and ref != 0:
        if abs(atual - ref) <= 3 or (atual % 10 == ref % 10):
            return True
            
    return False

def processar_novo_spin(roleta: str, spin: dict, buf_roleta: List[dict]):
    with _rlock:
        ts = spin.get("timestamp_epoch", 0)
        num = spin.get("numero")
        chave = spin.get("chave")
        
        if ts < START_TIME:
            return 
            
        op = _operacoes_ativas.get(roleta)
        
        if not op:
            if num in GATILHOS:
                if len(buf_roleta) >= 2:
                    n_prev = buf_roleta[1].get("numero")
                    
                    if n_prev == 0 or n_prev == num:
                        return
                        
                    alvos_dict = obter_alvos(n_prev)
                    if alvos_dict:
                        fid = f"api_{chave}"
                        _operacoes_ativas[roleta] = {
                            "roleta": roleta,
                            "formacao_id": fid,
                            "gatilho": num,
                            "n_prev": n_prev,
                            "alvo_sub": alvos_dict["alvo_sub"],
                            "grupo": alvos_dict["grupo"],
                            "alvos": alvos_dict["alvos"],
                            "entradas_feitas": 0,
                            "pausa_restante": 0,
                            "ref_escada": num,
                            "resultados": [],
                            "resultados_girados": [],
                            "historico_pausas": [],
                        }
                        criar_json_aposta(_operacoes_ativas[roleta])
                        _add_evento(f"Gatilho {num} detectado em {roleta}. Alvo {alvos_dict['alvo_sub']} ({alvos_dict['grupo']})")
                        salvar_estado()
        
        else:
            if chave in op["resultados"]: return
            op["resultados"].append(chave)
            op["resultados_girados"].append(num)
            
            if op["pausa_restante"] > 0:
                if verificar_turbulencia(num, op["ref_escada"]):
                    op["pausa_restante"] = 2
                    op["historico_pausas"].append(f"Renovou pausa no {num} (Turbulência contínua)")
                else:
                    op["pausa_restante"] -= 1
                
                op["ref_escada"] = num
                
                if op["pausa_restante"] == 0:
                    op["historico_pausas"].append(f"Pausa acabou no {num}. Voltando a apostar.")
                    criar_json_aposta(op)
                    
            else:
                op["entradas_feitas"] += 1
                
                if num in op["alvos"]:
                    registrar_resultado(op, "GREEN")
                    del _operacoes_ativas[roleta]
                else:
                    if op["entradas_feitas"] == 4:
                        registrar_resultado(op, "RED")
                        del _operacoes_ativas[roleta]
                    else:
                        if verificar_turbulencia(num, op["ref_escada"]):
                            op["pausa_restante"] = 2
                            op["historico_pausas"].append(f"Iniciou pausa no {num} (Entrada {op['entradas_feitas']})")
                        
                        op["ref_escada"] = num
                        criar_json_aposta(op)
                        
            salvar_estado()

def core_loop():
    while not _stop_event.is_set():
        carregar_config()
        salvar_estado()
        time.sleep(CFG["poll_interval"])

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    t_api = threading.Thread(target=thread_api, daemon=True)
    t_api.start()
    
    core_loop()
    _add_evento("Tchau!")
