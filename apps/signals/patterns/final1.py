# -*- coding: utf-8 -*-
"""
Analizer_VIP_adapted.py
--------------------------------
Versão adaptada para a estrutura do Allan:
- Remove qualquer lógica de busca de histórico, polling, Telegram e loop assíncrono.
- Exponde UMA ÚNICA função pública: process_roulette(roulette, numbers)
  * numbers: list[int] já no formato [mais_recente, ..., mais_antigo]
  * roulette: objeto opcional com metadados (ex.: .name, .slug)

Mantém um motor compactado de sugestão (vizinho / espelho / família) + proteções.
A implementação abaixo é autocontida (sem dependências externas) e foca em
comportamento consistente, previsível e integrável ao seu pipeline.

Se quiser ajustar o "peso" de cada relação, use variáveis de ambiente (ENV) listadas abaixo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple, Iterable, Any
from collections import defaultdict, Counter
from helpers.classificador import ClassificadorProximidade



import pytz
import json
import logging
import certifi
import threading
import asyncio
import math
import random
import statistics
import functools
import itertools



from datetime import datetime, timedelta

from typing import List
from dotenv import load_dotenv

# ------------------------------
# Redis cache (opcional, usado como read-through)
# ------------------------------
try:
    import redis.asyncio as aioredis  # pip install redis>=4.2
except Exception:  # fallback, caso a lib não esteja instalada
    aioredis = None

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
_PATTERN_NS = os.getenv("PATTERN_NAMESPACE", "pattern")
_redis_conn = None
_redis_lock = asyncio.Lock()

async def _get_redis():
    global _redis_conn
    if aioredis is None:
        return None
    if _redis_conn is None:
        async with _redis_lock:
            if _redis_conn is None:
                _redis_conn = aioredis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
    return _redis_conn

def _make_pattern_key(slug: str, hhmm: str) -> str:
    return f"{_PATTERN_NS}:{slug}:{hhmm}"

async def get_top_numbers_cached_redis(
    slug: str,
    interval_key: str,
    *,
    interval_minutes: int = 5,
    number: int | None = None,
    days_back: int = 30,
    current_time: str | None = None,
    ttl_seconds: int = 600,
    top_k: int = 15,
):
    """
    Tenta obter top_numbers do Redis. Se não existir, roda get_pattern_analysis uma vez,
    guarda no Redis com TTL e retorna apenas os inteiros (até top_k).
    """
    r = await _get_redis()
    key = _make_pattern_key(slug, interval_key)

    # 1) tenta cache
    if r is not None:
        try:
            raw = await r.get(key)
            if raw:
                data = json.loads(raw)
                arr = data.get("top_numbers") or []
                out = []
                for item in arr:
                    if isinstance(item, dict):
                        n = item.get("number")
                        if isinstance(n, int):
                            out.append(n)
                    elif isinstance(item, int):
                        out.append(item)
                    if len(out) >= top_k:
                        break
                if out:
                    return out
        except Exception:
            pass  # se der problema, cai para DB

    # 2) miss: calcula via Mongo e preenche
    analysis = await get_pattern_analysis(
        slug, interval_minutes, number, days_back, current_time
    )
    try:
        arr = (analysis.get("interval_patterns", {})
                        .get(interval_key, {})
                        .get("top_numbers", []))
    except Exception:
        arr = []

    # normaliza e persiste
    payload = {"top_numbers": arr}
    if r is not None:
        try:
            await r.set(key, json.dumps(payload, ensure_ascii=False), ex=ttl_seconds)
        except Exception:
            pass

    # retorna inteiros
    out = []
    for item in arr:
        if isinstance(item, dict):
            n = item.get("number")
            if isinstance(n, int):
                out.append(n)
        elif isinstance(item, int):
            out.append(item)
        if len(out) >= top_k:
            break
    return out

load_dotenv()

logging.basicConfig(
    level=logging.ERROR,  # Você pode mudar para DEBUG ou ERROR se quiser
    format="%(asctime)s - %(levelname)s - %(message)s"
)

from motor.motor_asyncio import AsyncIOMotorClient

# --- util assíncrono seguro p/ contexto síncrono ---
import asyncio
import threading
from concurrent.futures import TimeoutError as FuturesTimeoutError

class _AsyncLoopRunner:
    def __init__(self):
        self._loop = None
        self._thread = None
        self._ready = threading.Event()

    def start(self):
        if self._loop is not None:
            return self
        def _target():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._ready.set()
            self._loop.run_forever()
        self._thread = threading.Thread(target=_target, name="async-runner-loop", daemon=True)
        self._thread.start()
        self._ready.wait()
        return self

    def run(self, coro, timeout=None):
        """
        Executa `coro` (async) de forma síncrona, em um loop dedicado.
        Bloqueia até obter o resultado ou lançar a exceção da corotina.
        """
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return fut.result(timeout=timeout)
        except FuturesTimeoutError:
            # se quiser, cancele:
            fut.cancel()
            raise

# instancia global (loop dedicado em thread separada)
_ASYNC_RUNNER = _AsyncLoopRunner().start()

def run_async(coro, timeout=None):
    return _ASYNC_RUNNER.run(coro, timeout=timeout)


from datetime import datetime
import pytz

def _format_hhmm(ts):
    """
    Aceita datetime, str ISO, int/float epoch ou já 'HH:MM'.
    Retorna 'HH:MM' em America/Sao_Paulo.
    """
    tz = pytz.timezone("America/Sao_Paulo")
    if isinstance(ts, str):
        # se já vier 'HH:MM'
        if len(ts) == 5 and ts[2] == ':':
            return ts
        # tenta parse ISO
        try:
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        except Exception:
            raise ValueError(f"timestamp string inválido: {ts!r}")
    elif isinstance(ts, (int, float)):
        dt = datetime.utcfromtimestamp(ts).replace(tzinfo=pytz.utc)
    elif isinstance(ts, datetime):
        dt = ts if ts.tzinfo else pytz.utc.localize(ts)
    else:
        raise TypeError(f"tipo de timestamp não suportado: {type(ts)}")

    br = dt.astimezone(tz)
    return f"{br.hour:02d}:{(br.minute // 1):02d}"


# ============================================================
# Parte assíncrona de análise temporal (já existente)
# ============================================================

# Abaixo está a função assíncrona que analisa padrões por intervalos.
# Precisamos chamá-la de dentro de process_roulette (síncrona).

from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "roleta_db")

mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client[MONGO_DB]
history_coll = db["history"]

async def get_pattern_analysis(
        roulette_id: str,
        interval_minutes: int = 10,  # Intervalo em minutos (10, 15, 20, 30, 60)
        number: int = None,  # Número específico ou todos
        days_back: int = 30,  # Quantos dias analisar
        current_time: str = None  # Hora atual para previsão (HH:MM)
    ):
        """
        Análise de padrões temporais e previsão baseada em histórico
        """
        try:
            # Buscar dados históricos
            start_date = datetime.now() - timedelta(days=days_back)
            filter_query = {
                "roulette_id": roulette_id,
                "timestamp": {"$gte": start_date}
            }
            
            if number is not None:
                filter_query["value"] = number
            
            cursor = history_coll.find(filter_query).sort("timestamp", 1)
            results = await cursor.to_list(length=None)
            
            tz_br = pytz.timezone("America/Sao_Paulo")
            
            # Criar matriz de intervalos (24 horas divididas pelo intervalo)
            intervals_per_hour = 60 // interval_minutes
            total_intervals = 24 * intervals_per_hour
            
            # Estrutura para armazenar padrões
            interval_patterns = {}
            for i in range(total_intervals):
                hour = i // intervals_per_hour
                minute = (i % intervals_per_hour) * interval_minutes
                interval_key = f"{hour:02d}:{minute:02d}"
                interval_patterns[interval_key] = {
                    "start_time": f"{hour:02d}:{minute:02d}",
                    "end_time": f"{hour:02d}:{minute + interval_minutes - 1:02d}",
                    "numbers": {},  # {numero: contagem}
                    "total_occurrences": 0,
                    "days_with_occurrence": set(),
                    "probability": 0
                }
            
            # Processar resultados
            for doc in results:
                timestamp = doc["timestamp"]
                if timestamp.tzinfo is None:
                    timestamp = pytz.utc.localize(timestamp)
                br_time = timestamp.astimezone(tz_br)
                
                # Calcular intervalo
                hour = br_time.hour
                minute = br_time.minute
                interval_index = (hour * intervals_per_hour) + (minute // interval_minutes)
                
                hour_key = hour
                minute_key = (minute // interval_minutes) * interval_minutes
                interval_key = f"{hour_key:02d}:{minute_key:02d}"
                
                if interval_key in interval_patterns:
                    num = doc["value"]
                    if num not in interval_patterns[interval_key]["numbers"]:
                        interval_patterns[interval_key]["numbers"][num] = 0
                    interval_patterns[interval_key]["numbers"][num] += 1
                    interval_patterns[interval_key]["total_occurrences"] += 1
                    interval_patterns[interval_key]["days_with_occurrence"].add(br_time.date())
            
            # Calcular probabilidades e estatísticas
            for interval_key, pattern in interval_patterns.items():
                if pattern["total_occurrences"] > 0:
                    pattern["probability"] = (len(pattern["days_with_occurrence"]) / days_back) * 100
                    pattern["average_per_day"] = pattern["total_occurrences"] / days_back
                 
                    # Top 5 números mais frequentes no intervalo
                    sorted_numbers = sorted(
                        pattern["numbers"].items(), 
                        key=lambda x: x[1], 
                        reverse=True
                    )[:30]
                    pattern["top_numbers"] = [
                        {"number": num, "count": count, "percentage": (count/pattern["total_occurrences"])*100}
                        for num, count in sorted_numbers
                    ]
                else:
                    pattern["probability"] = 0
                    pattern["average_per_day"] = 0
                    pattern["top_numbers"] = []
                
            # Previsão para horários específicos (próximos intervalos)
            prediction = None
            if current_time:
                try:
                    hour, minute = map(int, current_time.split(":"))
                    
                    # Encontrar próximos intervalos
                    next_intervals = []
                    for i in range(3):  # Próximos 3 intervalos
                        next_minute = minute + (i * interval_minutes)
                        next_hour = hour + (next_minute // 60)
                        next_minute = next_minute % 60
                        next_hour = next_hour % 24
                        
                        interval_key = f"{next_hour:02d}:{(next_minute // interval_minutes) * interval_minutes:02d}"
                        if interval_key in interval_patterns:
                            pattern = interval_patterns[interval_key]
                            next_intervals.append({
                                "interval": interval_key,
                                "probability": pattern["probability"],
                                "historical_occurrences": pattern["total_occurrences"],
                                "top_numbers": pattern["top_numbers"],
                                "average_per_day": pattern["average_per_day"]
                            })
                    
                    prediction = {
                        "current_time": current_time,
                        "interval_minutes": interval_minutes,
                        "next_intervals": next_intervals
                    }
                except:
                    pass
            
            # Detectar zonas quentes e frias
            hot_zones = []
            cold_zones = []
            for interval_key, pattern in interval_patterns.items():
                if pattern["probability"] > 50:  # Mais de 50% dos dias tivemos ocorrência
                    hot_zones.append({
                        "interval": interval_key,
                        "probability": pattern["probability"],
                        "total_occurrences": pattern["total_occurrences"],
                        "top_numbers": pattern["top_numbers"][:5]
                    })
                elif pattern["probability"] < 10:  # Menos de 10% dos dias
                    cold_zones.append({
                        "interval": interval_key,
                        "probability": pattern["probability"],
                        "total_occurrences": pattern["total_occurrences"]
                    })
            
            # Ordenar zonas
            hot_zones.sort(key=lambda x: x["probability"], reverse=True)
            cold_zones.sort(key=lambda x: x["probability"])
            
            return {
                "analysis_parameters": {
                    "roulette_id": roulette_id,
                    "interval_minutes": interval_minutes,
                    "days_analyzed": days_back,
                    "total_records": len(results),
                    "number_filter": number
                },
                "interval_patterns": interval_patterns,
                "hot_zones": hot_zones[:10],  # Top 10 zonas quentes
                "cold_zones": cold_zones[:10],  # Top 10 zonas frias
                "prediction": prediction
            }
            
        except Exception as e:
            logging.error(f"Erro na análise de padrões: {e}")



# ------------------------------------------------------------
# Config via ENV (valores padrão seguros)
# ------------------------------------------------------------

TOPK_DEFAULT = int(os.getenv("CONFLUENCE_TOPK", "6"))
MIN_HISTORY_REQUIRED = int(os.getenv("MIN_HISTORY_REQUIRED", "12"))

WEIGHT_NEIGHBOR = float(os.getenv("WEIGHT_NEIGHBOR", "1.20"))
WEIGHT_MIRROR = float(os.getenv("WEIGHT_MIRROR", "0.95"))
WEIGHT_TERMINAL = float(os.getenv("WEIGHT_TERMINAL", "0.65"))
WEIGHT_DUZIA = float(os.getenv("WEIGHT_DUZIA", "0.55"))
WEIGHT_COLUNA = float(os.getenv("WEIGHT_COLUNA", "0.55"))
WEIGHT_COLOR = float(os.getenv("WEIGHT_COLOR", "0.35"))
WEIGHT_PARITY = float(os.getenv("WEIGHT_PARITY", "0.25"))
WEIGHT_GAP = float(os.getenv("WEIGHT_GAP", "0.50"))

MAX_SAME_TERMINAL = int(os.getenv("MAX_SAME_TERMINAL", "3"))
MAX_SAME_DUZIA = int(os.getenv("MAX_SAME_DUZIA", "4"))
MAX_SAME_COLUNA = int(os.getenv("MAX_SAME_COLUNA", "4"))

ZERO_NEIGHBOR_PENALTY = float(os.getenv("ZERO_NEIGHBOR_PENALTY", "0.85"))

# ------------------------------------------------------------
# Layout de roda europeia e utilitários
# ------------------------------------------------------------

# Ordem da roda europeia (número -> posição circular)
WHEEL: List[int] = [
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5,
    24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26
]
INDEX: Dict[int, int] = {n: i for i, n in enumerate(WHEEL)}

# Cor (0 = None)
RED: Set[int] = {
    1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36
}


# ─── Conexão MongoDB / Motor ───────────────────────────────────────────────────
MONGO_URL = os.getenv(
    "MONGO_URL",
)
mongo_client = AsyncIOMotorClient(
    MONGO_URL,
    tls=True,
    tlsCAFile=certifi.where()
    )
mongo_db     = mongo_client["roleta_db"]
history_coll = mongo_db["history"]

# Função para formatar timestamps para horário de Brasília
def format_timestamp_br(timestamp: int) -> str:
    tz = pytz.timezone("America/Sao_Paulo")
    dt = datetime.fromtimestamp(timestamp, tz)
    return dt.strftime("%d/%m/%Y %H:%M:%S")


def color(n: int) -> Optional[str]:
    if n == 0:
        return None
    return "R" if n in RED else "B"

def paridade(n: int) -> Optional[int]:
    if n == 0:
        return None
    return n % 2

def duzia(n: int) -> Optional[int]:
    if n == 0:
        return None
    if 1 <= n <= 12:
        return 1
    if 13 <= n <= 24:
        return 2
    if 25 <= n <= 36:
        return 3
    return None

def coluna(n: int) -> Optional[int]:
    """
    Colunas do layout 3-colunas clássico:
    1ª coluna: 1,4,7,...,34
    2ª coluna: 2,5,8,...,35
    3ª coluna: 3,6,9,...,36
    """
    if n == 0:
        return None
    c = n % 3
    return 3 if c == 0 else c  # 0->3, 1->1, 2->2

def vizinhos(n: int) -> Tuple[int, int]:
    """Vizinhos na roda (circular)."""
    i = INDEX[n]
    left = WHEEL[(i - 1) % len(WHEEL)]
    right = WHEEL[(i + 1) % len(WHEEL)]
    return left, right

def wheel_dist(a: int, b: int) -> int:
    """Distância mínima na roda circular."""
    ia = INDEX[a]; ib = INDEX[b]
    L = len(WHEEL)
    d = abs(ia - ib)
    return min(d, L - d)

# Ruas (streets) 1..36
STREETS: List[Tuple[int, int, int]] = [(s, s+1, s+2) for s in range(1, 37, 3)]
def street_of(n: int) -> Optional[Tuple[int, int, int]]:
    if n == 0:
        return None
    s = n - ((n-1) % 3)
    return (s, s+1, s+2)

# Espelhos (mapeamento consolidado a partir dos pares fornecidos pelo Allan em conversas anteriores)
ESPELHOS_FIXOS: Dict[int, int] = {
    1:10, 10:1,
    2:20, 20:2,
    3:30, 30:3,
    6:9,  9:6,
    11:22, 22:33, 33:11,
    12:21, 21:12,
    13:31, 31:13,
    16:19, 19:16,
    23:32, 32:23,
    26:29, 29:26,
}

def espelho(n: int) -> Optional[int]:
    return ESPELHOS_FIXOS.get(n)

def terminal(n: int) -> Optional[int]:
    if n == 0:
        return None
    return n % 10

# ------------------------------------------------------------
# Proteções
# ------------------------------------------------------------

def calcular_protecoes(sugestao: Iterable[int]) -> List[int]:
    """
    Proteções automáticas:
      1) Espelhos dos sugeridos.
      2) "Buracos da roda": se ambos os vizinhos de X estão nos sugeridos, protege X.
      3) Street faltante: se 2 da mesma rua estão nos sugeridos, protege o 3º.
      4) Saltos ±2: se (n, n±2) estão, protege (n±1) quando válido.
    """
    base: Set[int] = set(int(x) for x in sugestao if 0 <= int(x) <= 36)
    prot: Set[int] = set()

    # 1) Espelhos
    for x in base:
        e = espelho(x)
        if e is not None and e not in base:
            prot.add(e)

    # 2) Buracos da roda
    # Se ambos vizinhos de X já estão em base, protege X
    for x in range(37):
        if x in base:
            continue
        vl, vr = vizinhos(x)
        if vl in base and vr in base:
            prot.add(x)

    # 3) Street faltante
    for st in STREETS:
        sset = set(st)
        inter = sset & base
        if len(inter) == 2:
            missing = list(sset - inter)[0]
            if missing not in base:
                prot.add(missing)

    # 4) Saltos ±2
    # Considera apenas 1..36 (ignora 0 nesta proteção)
    b = {x for x in base if x != 0}
    for x in list(b):
        for delta in (-2, 2):
            y = x + delta
            if 1 <= y <= 36 and y in b:
                mid = x + (delta // 2)
                if 1 <= mid <= 36 and mid not in base:
                    prot.add(mid)

    # Remove números já na base
    prot.difference_update(base)
    return sorted(prot, key=lambda n: (n == 0, n))

# ------------------------------------------------------------
# Estruturas de retorno do motor
# ------------------------------------------------------------

@dataclass
class Suggestion:
    candidatos: List[int]
    anchor: Optional[int] = None
    support_master: float = 0.0
    support_estelar: float = 0.0
    support_gap: float = 0.0
    sn_multiplier: float = 1.0

# ------------------------------------------------------------
# Motor compacto: MasterEstelarSuggestor (versão enxuta)
# ------------------------------------------------------------

class MasterEstelarSuggestor:
    """
    Versão compacta e autocontida do motor:
    - Pesa: vizinhos, espelho, terminal, dúzia, coluna, cor, paridade
    - "Gap" simplificado: frequência de saídas após "âncoras" equivalentes recentes
    - Diversificação: limites por terminal, dúzia e coluna
    """

    def __init__(self):
        pass

    # ---------- Helpers de família ----------

    def _family_terminal(self, n: int) -> Set[int]:
        t = terminal(n)
        if t is None:
            return set()
        return {k for k in range(1, 37) if k % 10 == t}

    def _family_duzia(self, n: int) -> Set[int]:
        d = duzia(n)
        if d is None:
            return set()
        if d == 1:
            return set(range(1, 13))
        elif d == 2:
            return set(range(13, 25))
        return set(range(25, 37))

    def _family_coluna(self, n: int) -> Set[int]:
        c = coluna(n)
        if c is None:
            return set()
        return {k for k in range(1, 37) if coluna(k) == c}

    def _family_color(self, n: int) -> Set[int]:
        c = color(n)
        if c is None:
            return set()
        if c == "R":
            return set(RED)
        else:
            return {k for k in range(1, 37) if k not in RED}

    def _family_parity(self, n: int) -> Set[int]:
        p = paridade(n)
        if p is None:
            return set()
        return {k for k in range(1, 37) if k % 2 == p}

    # ---------- Gap simplificado ----------

    def _gap_scores(self, hist: List[int], anchor: int, lookback: int = 80) -> Counter:
        """
        Gap simplificado: para cada posição i onde hist[i] == anchor,
        soma a frequência de hist[i-1] (o número que saiu "logo depois" no passado,
        considerando hist[0] como o MAIS RECENTE).
        """
        cnt = Counter()
        L = min(len(hist), lookback)
        # hist[0] é o mais recente -> 'depois' no passado é i-1 (se existir)
        for i in range(L):
            if hist[i] == anchor and (i + 1) < L:
                # no histórico reverso, o "próximo" que saiu antes desta âncora
                prev_after_anchor = hist[i + 1]
                if 0 <= prev_after_anchor <= 36:
                    cnt[prev_after_anchor] += 1
        return cnt

    # ---------- Diversificação ----------

    def _diversify(self, ordered: List[int]) -> List[int]:
        """
        Aplica limites por terminal, dúzia e coluna.
        """
        out: List[int] = []
        term_cnt: Dict[int, int] = defaultdict(int)
        doz_cnt: Dict[int, int] = defaultdict(int)
        col_cnt: Dict[int, int] = defaultdict(int)

        for n in ordered:
            if n < 0 or n > 36:
                continue

            t = terminal(n)
            d = duzia(n)
            c = coluna(n)

            if t is not None and term_cnt[t] >= MAX_SAME_TERMINAL:
                continue
            if d is not None and doz_cnt[d] >= MAX_SAME_DUZIA:
                continue
            if c is not None and col_cnt[c] >= MAX_SAME_COLUNA:
                continue

            out.append(n)
            if t is not None: term_cnt[t] += 1
            if d is not None: doz_cnt[d] += 1
            if c is not None: col_cnt[c] += 1

        return out

    # ---------- Núcleo: sugerir ----------

    def sugerir(self, hist: List[int], topk: int = TOPK_DEFAULT) -> Optional[Suggestion]:
        """
        hist[0] = MAIS RECENTE
        Retorna Suggestion com lista de candidatos e metadados de suporte.
        """
        if not hist or len(hist) < MIN_HISTORY_REQUIRED:
            return None

        anchor = hist[0]
        weights: Dict[int, float] = defaultdict(float)

        # 1) Relações principais em torno da âncora
        # 1.1 Vizinhos
        vl, vr = vizinhos(anchor)
        if anchor == 0:
            # âncora zero: pequeno rebaixamento dos vizinhos
            weights[vl] += WEIGHT_NEIGHBOR * ZERO_NEIGHBOR_PENALTY
            weights[vr] += WEIGHT_NEIGHBOR * ZERO_NEIGHBOR_PENALTY
        else:
            weights[vl] += WEIGHT_NEIGHBOR
            weights[vr] += WEIGHT_NEIGHBOR

        # 1.2 Espelho
        m = espelho(anchor)
        if m is not None:
            weights[m] += WEIGHT_MIRROR
            # bônus suave aos vizinhos do espelho
            mvl, mvr = vizinhos(m)
            weights[mvl] += WEIGHT_MIRROR * 0.25
            weights[mvr] += WEIGHT_MIRROR * 0.25

        # 1.3 Terminal/duzia/coluna
        for fam, w in [
            (self._family_terminal(anchor), WEIGHT_TERMINAL),
            (self._family_duzia(anchor), WEIGHT_DUZIA),
            (self._family_coluna(anchor), WEIGHT_COLUNA),
        ]:
            # ordenar por proximidade na roda à âncora
            ordered = sorted(fam, key=lambda x: wheel_dist(x, anchor))
            for i, n in enumerate(ordered):
                # decaimento leve conforme se afasta
                weights[n] += w * (0.9 ** i)

        # 1.4 Cor e paridade (peso mais leve, também por proximidade)
        for fam, w in [
            (self._family_color(anchor), WEIGHT_COLOR),
            (self._family_parity(anchor), WEIGHT_PARITY),
        ]:
            ordered = sorted(fam, key=lambda x: wheel_dist(x, anchor))
            for i, n in enumerate(ordered[:12]):  # não exagerar no espalhamento
                weights[n] += w * (0.9 ** i)

        # 2) Gap simplificado
        gap = self._gap_scores(hist, anchor, lookback=80)
        if gap:
            # normaliza por máximo para virar um boost 0..1
            max_gap = max(gap.values())
            for n, c in gap.items():
                if n == anchor:
                    continue
                weights[n] += WEIGHT_GAP * (c / max_gap)

        # Não sugerimos o próprio anchor
        if anchor in weights:
            del weights[anchor]

        # Remove 0 de pesos negativos acidentais
        weights = {k: max(0.0, float(v)) for k, v in weights.items() if 0 <= k <= 36 and v > 0}

        if not weights:
            return None

        # 3) Ordenação por peso (desc), depois por proximidade ao anchor
        ordered_all = sorted(
            weights.keys(),
            key=lambda n: (-weights[n], wheel_dist(n, anchor), n)
        )

        # 4) Diversificação por limites de família
        diversified = self._diversify(ordered_all)

        # 5) Corta em topk
        candidatos = diversified[:max(1, int(topk))]

        # Suportes (estimativas coerentes para monitoramento)
        support_master = float(WEIGHT_NEIGHBOR + WEIGHT_MIRROR + WEIGHT_TERMINAL + WEIGHT_DUZIA + WEIGHT_COLUNA)
        support_estelar = 0.0  # não modelado explicitamente nesta versão compacta
        support_gap = float(WEIGHT_GAP) if gap else 0.0
        sn_multiplier = 1.0    # não modelado explicitamente nesta versão compacta

        return Suggestion(
            candidatos=candidatos,
            anchor=anchor,
            support_master=support_master,
            support_estelar=support_estelar,
            support_gap=support_gap,
            sn_multiplier=sn_multiplier,
        )

# ------------------------------------------------------------
# Instância única do motor
# ------------------------------------------------------------

_SUGGESTOR = MasterEstelarSuggestor()

# ------------------------------------------------------------
# Função pública para integrar no pipeline do Allan
# ------------------------------------------------------------

def process_roulette(roulette, numbers: List[int], full_results):
    """
    Parametrização mínima p/ acoplar ao seu orquestrador.

    Parâmetros
    ----------
    roulette : objeto opcional com metadados (ex.: .name, .slug). Pode ser qualquer coisa.
    numbers  : list[int] com 0..36, em ordem [mais_recente, ..., mais_antigo]
    """
    # pré-condição
    if not numbers or len(numbers) < MIN_HISTORY_REQUIRED:
        return None


    hist = numbers
    topk = TOPK_DEFAULT

    sugestao_raw = _SUGGESTOR.sugerir(hist, topk=topk)
    if not sugestao_raw or not sugestao_raw.candidatos:
        return None

    protecoes = calcular_protecoes(sugestao_raw.candidatos)

    name = getattr(roulette, "name", None) or getattr(roulette, "nome", None) or None
    slug = getattr(roulette, "slug", None) or getattr(roulette, "id", None) or None

    final_bet = sorted(set(sugestao_raw.candidatos))

    spins_required = 0
    classificador = ClassificadorProximidade(peso_principal = 2.3,
    peso_vizinhos = 1.4,
    peso_vizinhos1 = 0.8,
    peso_duzia = 0,
    peso_cor = 0,
    peso_puxada = 0,
    qtd_puxada = 10,
    decaimento = 0.8)

    for number in numbers[:80]:
        classificador.adicionar_numero(number)

    ranking = classificador.get_ranking()[:13]

    nums = [num for num, _ in ranking]


    matches = [n for n in nums if n in final_bet]

            
    hour_key = full_results[0]["hour"]
    minute_key = (full_results[0]["minute"] // 5) * 5
    interval_key = f"{hour_key:02d}:{minute_key:02d}"

    ranking_temporal = run_async(get_top_numbers_cached_redis(
        roulette["slug"],
        interval_key,
        interval_minutes=5,
        number=None,
        days_back=30,
        current_time=_format_hhmm(full_results[0]["timestamp"]),
        ttl_seconds=600,
        top_k=15,
    ))


    matches_temporal = [n for n in ranking_temporal if n in final_bet]


    if len(matches_temporal) <= 2:
        spins_required += 8
        

    if len(matches) <= 3 :
        return None


    return {
                "roulette_id": roulette['slug'],
                "roulette_name" : roulette["name"],
                "roulette_url" : roulette["url"],
                "pattern" : "7NUMEROS IMEDIATO",
                "triggers":[numbers[0]],
                "targets":[*final_bet],
                "bets": final_bet,
                "passed_spins" : 0,
                "spins_required" : spins_required,
                "spins_count": 0,
                "gales" : 20,
                "score" :len(matches_temporal),
                "snapshot":numbers[:10],
                "status":"processing",
                "message" : f"Gatilho encontrado! necessário aguardar {spins_required} jogadas",
                "tags" : [f"ranking_{len(matches)}", f'temporal_{len(matches_temporal)}'],
            }
    return None


