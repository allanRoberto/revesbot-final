#!/usr/bin/env python3
"""
Worker PUXADAS — INVERSÃO (mede assertividade do analisador de puxadas).

Lógica:
  • A cada giro recalcula o ranking top-12 pelo método de puxadas
    (últimas 6 âncoras × 5 ocorrências anteriores × sementes de vizinhança).
  • TRIGGER = quando o número que acabou de sair estava no ranking top-12
    calculado no giro ANTERIOR (a "inversão pagou").
  • APOSTA   = top-12 do novo ranking (calculado com o giro atual como âncora).
  • Monitoramento: até MAX_ATTEMPTS (4) giros, apostando 12 fichas (1 por número).
  • P&L por tentativa: vitória = +24 fichas; derrota total = -48 fichas.
  • Após resolução (win/loss): acompanha POST_ROUNDS (10) giros extras para
    medir quanto do top-12 se confirma na prática.

Coleção MongoDB: puxadas_inversao_signals
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import redis as redis_lib
from pymongo import DESCENDING, MongoClient
from pymongo.collection import Collection

# ── Paths ────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[3]
APPS_ROOT = REPO_ROOT / "apps"
if str(APPS_ROOT) not in sys.path:
    sys.path.insert(0, str(APPS_ROOT))

# ── Configuração via env ──────────────────────────────────────────────────────
MONGO_URL = os.getenv(
    "MONGO_URL",
    "mongodb://revesbot:DlBnGmlimRZpIblr@127.0.0.1:27017/roleta_db?authSource=admin",
)
REDIS_URL        = os.getenv("REDIS_CONNECT", "redis://localhost:6379")
RESULT_CHANNEL   = os.getenv("RESULT_CHANNEL", "new_result")
SIGNAL_STREAM    = "streams:signals:new"

ROULETTE_IDS_RAW = os.getenv(
    "PUXADAS_INV_ROULETTE_IDS",
    "pragmatic-auto-roulette,pragmatic-brazilian-roulette",
)
ROULETTE_IDS = [r.strip() for r in ROULETTE_IDS_RAW.split(",") if r.strip()]

SPINS_TO_FETCH = int(os.getenv("PUXADAS_INV_SPINS", "500"))
MAX_ATTEMPTS   = int(os.getenv("PUXADAS_INV_MAX_ATTEMPTS", "4"))
POST_ROUNDS    = int(os.getenv("PUXADAS_INV_POST_ROUNDS", "10"))
N_ANCHORS      = int(os.getenv("PUXADAS_INV_N_ANCHORS", "6"))
N_OCC          = int(os.getenv("PUXADAS_INV_N_OCC", "5"))
TOP_K          = int(os.getenv("PUXADAS_INV_TOP_K", "12"))
BET_CHIPS      = int(os.getenv("PUXADAS_INV_BET_CHIPS", "12"))   # fichas por tentativa

# ── Relações (puxadas) ────────────────────────────────────────────────────────
WHEEL = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23,
         10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26]
POS = {n: i for i, n in enumerate(WHEEL)}
ESP = {1: 10, 10: 1, 2: 20, 20: 2, 3: 30, 30: 3, 6: 9, 9: 6,
       12: 21, 21: 12, 13: 31, 31: 13, 16: 19, 19: 16,
       23: 32, 32: 23, 26: 29, 29: 26}
TWINS = {11, 22, 33}
CAV = {**{d: 'A' for d in (0, 3, 6, 9)},
       **{d: 'B' for d in (1, 4, 7)},
       **{d: 'C' for d in (2, 5, 8)}}

DEPTH      = [1.0, 0.6, 0.4, 0.25, 0.15, 0.1]
SEED_W     = 3.0
STRONG_W   = 2.0
WEAK_W     = 1.0

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("puxadas-inversao-worker")

# ── MongoDB / Redis ───────────────────────────────────────────────────────────
_mongo         = MongoClient(MONGO_URL)
_db            = _mongo["roleta_db"]
history_coll:  Collection = _db["history"]
signals_coll:  Collection = _db["puxadas_inversao_signals"]

_redis = redis_lib.from_url(REDIS_URL, decode_responses=True)


# ── Matriz de relações ────────────────────────────────────────────────────────
def _droot(n: int) -> int:
    if n == 0:
        return 0
    r = n % 9
    return 9 if r == 0 else r


def _build_R() -> np.ndarray:
    R = np.zeros((37, 37), dtype=np.float32)
    for n in range(37):
        R[n, n] += SEED_W
        i = POS[n]
        for nb in (WHEEL[(i - 1) % 37], WHEEL[(i + 1) % 37]):
            R[n, nb] += STRONG_W
        if n in ESP:
            R[n, ESP[n]] += STRONG_W
        for seq in (n - 1, n + 1):
            if 0 <= seq <= 36:
                R[n, seq] += STRONG_W
        dr = _droot(n)
        if dr:
            for x in range(37):
                if x != n and _droot(x) == dr:
                    R[n, x] += WEAK_W
        t = n % 10
        for x in range(37):
            if x != n and x % 10 == t:
                R[n, x] += WEAK_W
        c = CAV[n % 10]
        for x in range(37):
            if x != n and CAV[x % 10] == c:
                R[n, x] += WEAK_W
    return R


R_MATRIX = _build_R()


def calc_ranking(history: List[int]) -> List[int]:
    """
    Calcula o ranking top-K pelo método de puxadas.
    history[0] = mais recente.
    """
    n = len(history)
    if n < 10:
        return []

    # Histórico cronológico (mais antigo → mais recente)
    v = list(reversed(history))

    # Índices de cada número no histórico cronológico
    idx_of: Dict[int, List[int]] = {x: [] for x in range(37)}
    for j, val in enumerate(v):
        idx_of[val].append(j)

    scores = np.zeros(37, dtype=np.float32)
    for d in range(1, N_ANCHORS + 1):
        if d > n:
            break
        A = history[d - 1]           # âncora d (mais recente = profundidade 1)
        dw = DEPTH[d - 1]
        positions = idx_of[A]         # posições no histórico cronológico
        T = n                         # todos os itens são < T (sem vazamento)

        svec = np.zeros(37, dtype=np.float32)
        for j in positions[max(0, len(positions) - N_OCC):]:
            # semente -1 (antes da ocorrência)
            if j > 0:
                svec += R_MATRIX[v[j - 1]]
            # semente +1 (logo após)
            if j + 1 < T:
                svec += R_MATRIX[v[j + 1]]
            # semente +2
            if j + 2 < T:
                svec += R_MATRIX[v[j + 2]]

        if svec.max() == 0:
            continue
        top10_idx = np.argpartition(svec, -10)[-10:]
        keep = np.zeros(37, dtype=np.float32)
        keep[top10_idx] = svec[top10_idx]
        scores += dw * keep

    ranked = np.argsort(scores)[::-1].tolist()
    return [int(x) for x in ranked[:TOP_K]]


# ── P&L ─────────────────────────────────────────────────────────────────────
def calc_pnl(won_at: Optional[int]) -> float:
    """
    12 fichas por tentativa (1 por número).
    Vitória: +36 - 12 = +24 fichas (líquido por tentativa onde ganhou)
             menos 12 × (won_at - 1) fichas das tentativas anteriores.
    Derrota: -12 × MAX_ATTEMPTS.
    """
    if won_at is None:
        return float(-BET_CHIPS * MAX_ATTEMPTS)
    win_net = (36 - BET_CHIPS)            # = +24
    loss    = -BET_CHIPS * (won_at - 1)   # tentativas anteriores
    return float(win_net + loss)


# ── Estado por roleta ─────────────────────────────────────────────────────────
class RouletteState:
    def __init__(self, roulette_id: str, initial_history: List[int]):
        self.rid = roulette_id
        # history[0] = mais recente
        self.history: List[int] = initial_history[:SPINS_TO_FETCH]

        self.prev_ranking: List[int] = []
        self.signal_id: Optional[Any] = None        # ObjectId ativo
        self.phase: str = "idle"                    # idle | monitoring | post_tracking
        self.attempts: int = 0
        self.post_count: int = 0
        self.bet: List[int] = []                    # ranking apostado

        # Calcula ranking inicial
        self.prev_ranking = calc_ranking(self.history)
        log.info("[%s] Inicializado: %d giros, ranking=%s", roulette_id, len(self.history), self.prev_ranking)

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def on_spin(self, value: int, ts: Optional[datetime] = None) -> None:
        now = ts or self._now()

        # Atualiza histórico (mais recente na frente)
        self.history.insert(0, value)
        if len(self.history) > SPINS_TO_FETCH:
            self.history.pop()

        if self.phase == "monitoring":
            self._handle_monitoring(value, now)

        elif self.phase == "post_tracking":
            self._handle_post_tracking(value, now)

        else:  # idle
            self._check_trigger(value, now)

    # ── Trigger ──────────────────────────────────────────────────────────────
    def _check_trigger(self, value: int, now: datetime) -> None:
        prev = self.prev_ranking
        new_ranking = calc_ranking(self.history)

        if prev and value in prev:
            # Inversão pagou → dispara sinal com o NOVO ranking
            if new_ranking:
                self._fire_signal(value, prev, new_ranking, now)
            else:
                log.debug("[%s] Inversão pagou mas ranking vazio, skip.", self.rid)

        self.prev_ranking = new_ranking

    def _fire_signal(self, trigger_value: int, prev_ranking: List[int],
                     new_ranking: List[int], now: datetime) -> None:
        doc = {
            "roulette_id":     self.rid,
            "status":          "monitoring",
            "trigger_value":   trigger_value,
            "trigger_ts":      now,
            "prev_ranking":    prev_ranking,         # ranking que pagou (inversão)
            "ranking":         new_ranking,          # ranking apostado
            "bet":             new_ranking,
            "bet_chips":       BET_CHIPS,
            "attempts":        [],
            "won_at_attempt":  None,
            "pnl":             None,
            "post_tracking": {
                "active":     False,
                "rounds":     [],
                "hits":       0,
                "completed":  False,
                "started_at": None,
            },
            "created_at":  now,
            "resolved_at": None,
            "config": {
                "max_attempts":  MAX_ATTEMPTS,
                "post_rounds":   POST_ROUNDS,
                "n_anchors":     N_ANCHORS,
                "n_occ":         N_OCC,
                "top_k":         TOP_K,
                "bet_chips":     BET_CHIPS,
            },
        }
        result = signals_coll.insert_one(doc)
        self.signal_id = result.inserted_id
        self.phase     = "monitoring"
        self.attempts  = 0
        self.bet       = new_ranking
        log.info("[%s] Sinal disparado: trigger=%d ranking=%s", self.rid, trigger_value, new_ranking)

        # Publica no stream de sinais (dashboard ao vivo)
        try:
            _redis.xadd(SIGNAL_STREAM, {
                "type":        "new_signal",
                "signal_type": "puxadas_inversao",
                "roulette_id": self.rid,
                "signal_id":   str(self.signal_id),
                "ranking":     json.dumps(new_ranking),
                "trigger":     trigger_value,
            }, maxlen=2000)
        except Exception as e:
            log.warning("[%s] Falha ao publicar no stream: %s", self.rid, e)

    # ── Monitoramento ─────────────────────────────────────────────────────────
    def _handle_monitoring(self, value: int, now: datetime) -> None:
        self.attempts += 1
        hit = value in self.bet
        attempt_doc = {
            "attempt":   self.attempts,
            "value":     value,
            "hit":       hit,
            "timestamp": now,
        }

        if hit or self.attempts >= MAX_ATTEMPTS:
            won_at = self.attempts if hit else None
            pnl    = calc_pnl(won_at)
            status = "won" if hit else "lost"
            signals_coll.update_one(
                {"_id": self.signal_id},
                {"$push": {"attempts": attempt_doc},
                 "$set":  {
                     "status":         status,
                     "won_at_attempt": won_at,
                     "pnl":            pnl,
                     "resolved_at":    now,
                     "post_tracking.active":     True,
                     "post_tracking.started_at": now,
                 }},
            )
            log.info("[%s] Sinal %s: %s | won_at=%s | pnl=%.0f",
                     self.rid, self.signal_id, status, won_at, pnl)
            self.phase     = "post_tracking"
            self.post_count = 0
        else:
            signals_coll.update_one(
                {"_id": self.signal_id},
                {"$push": {"attempts": attempt_doc}},
            )
            log.debug("[%s] Tentativa %d: %d (miss)", self.rid, self.attempts, value)

    # ── Pós-tracking ──────────────────────────────────────────────────────────
    def _handle_post_tracking(self, value: int, now: datetime) -> None:
        self.post_count += 1
        hit = value in self.bet
        round_doc = {
            "round":     self.post_count,
            "value":     value,
            "hit":       hit,
            "timestamp": now,
        }
        update: Dict[str, Any] = {
            "$push": {"post_tracking.rounds": round_doc},
        }
        if hit:
            update["$inc"] = {"post_tracking.hits": 1}

        if self.post_count >= POST_ROUNDS:
            update["$set"] = {
                "post_tracking.active":    False,
                "post_tracking.completed": True,
            }
            signals_coll.update_one({"_id": self.signal_id}, update)
            log.info("[%s] Post-tracking concluído: %d/%d do top-%d apareceram.",
                     self.rid, 0, POST_ROUNDS, TOP_K)
            self._reset()
        else:
            signals_coll.update_one({"_id": self.signal_id}, update)

    def _reset(self) -> None:
        self.signal_id  = None
        self.phase      = "idle"
        self.attempts   = 0
        self.post_count = 0
        self.bet        = []
        # Recalcula ranking para o próximo trigger
        self.prev_ranking = calc_ranking(self.history)


# ── Bootstrap: carrega histórico do MongoDB ───────────────────────────────────
def load_initial_history(rid: str) -> List[int]:
    docs = list(
        history_coll.find({"roulette_id": rid}, {"value": 1, "_id": 0})
        .sort("timestamp", DESCENDING)
        .limit(SPINS_TO_FETCH)
    )
    values = [int(d["value"]) for d in docs if 0 <= int(d.get("value", -1)) <= 36]
    log.info("[%s] Carregados %d giros do MongoDB.", rid, len(values))
    return values


# ── Loop principal ────────────────────────────────────────────────────────────
def _parse_message(raw: Any) -> Optional[Dict]:
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except Exception:
            return None
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    slug = data.get("slug") or data.get("roulette_id")
    if not isinstance(slug, str) or not slug.strip():
        return None
    raw_val = data.get("result") if data.get("result") is not None else data.get("value")
    try:
        val = int(raw_val)
    except (TypeError, ValueError):
        return None
    if not (0 <= val <= 36):
        return None
    return {"slug": slug.strip(), "value": val, "raw": data}


def main() -> None:
    log.info("Iniciando puxadas-inversao-worker | roletas=%s", ROULETTE_IDS)

    # Carrega histórico inicial
    states: Dict[str, RouletteState] = {}
    for rid in ROULETTE_IDS:
        hist = load_initial_history(rid)
        if hist:
            states[rid] = RouletteState(rid, hist)
        else:
            log.warning("[%s] Sem histórico inicial — aguardando primeiros giros.", rid)
            states[rid] = RouletteState(rid, [])

    # Redis pubsub
    pubsub = _redis.pubsub()
    pubsub.subscribe(RESULT_CHANNEL)
    log.info("Inscrito no canal Redis '%s'. Aguardando giros…", RESULT_CHANNEL)

    while True:
        try:
            msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg is None:
                time.sleep(0.05)
                continue

            parsed = _parse_message(msg.get("data"))
            if parsed is None:
                continue

            slug  = parsed["slug"]
            value = parsed["value"]

            if slug not in states:
                continue

            states[slug].on_spin(value)

        except KeyboardInterrupt:
            log.info("Encerrando worker.")
            break
        except Exception as e:
            log.exception("Erro no loop principal: %s", e)
            time.sleep(2)


if __name__ == "__main__":
    main()
