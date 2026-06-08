#!/usr/bin/env python3
"""
Worker MULTI-PIVÔ — SINAL (assertividade da análise multi-pivô).

Lógica:
  • TRIGGER = qualquer giro quando o worker está idle.
  • RANKING = método multi-pivô (mesmo da página /multi-pivo):
        - 5 pivôs  = os 5 últimos números sorteados;
        - 5 ocorrências anteriores de cada pivô;
        - 2 números ATRÁS (-1,-2) + 2 à FRENTE (+1,+2) de cada ocorrência;
        - cada número-base é expandido em vizinho(1)/espelho/sequência;
        - cruza as 5 listas → agregado, ordenado por (em quantas listas aparece,
          depois total de aparições). Top-12 = aposta.
  • APOSTA = top-12 do ranking (12 fichas, 1 por número).
  • Monitoramento: até MAX_ATTEMPTS (4) giros.
  • P&L por tentativa de vitória:
        T1 = +24 | T2 = +12 | T3 = 0 | T4 = -12 | Derrota = -48 fichas.
  • Pós-resolução: POST_ROUNDS (10) giros de acompanhamento para medir
    quantas vezes o top-12 aparece na prática. Roda EM PARALELO: assim que um
    sinal resolve (won/lost), o worker já fica livre para disparar o próximo no
    giro seguinte — vários sinais podem estar em pós-tracking ao mesmo tempo.

Coleção MongoDB: multi_pivo_signals
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import redis as redis_lib
from pymongo import DESCENDING, MongoClient
from pymongo.collection import Collection

# ── Paths ─────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[3]
APPS_ROOT = REPO_ROOT / "apps"
if str(APPS_ROOT) not in sys.path:
    sys.path.insert(0, str(APPS_ROOT))

# ── Config via env ─────────────────────────────────────────────────────────────
MONGO_URL = os.getenv(
    "MONGO_URL",
    "mongodb://revesbot:DlBnGmlimRZpIblr@127.0.0.1:27017/roleta_db?authSource=admin",
)
REDIS_URL      = os.getenv("REDIS_CONNECT", "redis://localhost:6379")
RESULT_CHANNEL = os.getenv("RESULT_CHANNEL", "new_result")
SIGNAL_STREAM  = "streams:signals:new"

ROULETTE_IDS_RAW = os.getenv(
    "MULTI_PIVO_ROULETTE_IDS",
    "pragmatic-auto-roulette,pragmatic-brazilian-roulette",
)
ROULETTE_IDS = [r.strip() for r in ROULETTE_IDS_RAW.split(",") if r.strip()]

SPINS_TO_FETCH = int(os.getenv("MULTI_PIVO_SPINS",        "500"))
MAX_ATTEMPTS   = int(os.getenv("MULTI_PIVO_MAX_ATTEMPTS",  "4"))
POST_ROUNDS    = int(os.getenv("MULTI_PIVO_POST_ROUNDS",   "10"))
N_PIVOS        = int(os.getenv("MULTI_PIVO_N_PIVOS",        "5"))
N_OCC          = int(os.getenv("MULTI_PIVO_N_OCC",         "5"))
N_ANTES        = int(os.getenv("MULTI_PIVO_N_ANTES",        "2"))
N_FRENTE       = int(os.getenv("MULTI_PIVO_N_FRENTE",       "2"))
TOP_K          = int(os.getenv("MULTI_PIVO_TOP_K",         "12"))
BET_CHIPS      = int(os.getenv("MULTI_PIVO_BET_CHIPS",     "12"))

# ── Constantes de relação (iguais à ferramenta multi-pivô) ─────────────────────
WHEEL = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23,
         10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26]
POS   = {n: i for i, n in enumerate(WHEEL)}
ESP   = {1: 10, 10: 1, 2: 20, 20: 2, 3: 30, 30: 3, 6: 9, 9: 6,
         12: 21, 21: 12, 13: 31, 31: 13, 14: 34, 34: 14, 16: 19, 19: 16,
         23: 32, 32: 23, 26: 29, 29: 26}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("multi-pivo-worker")

# ── Conexões ───────────────────────────────────────────────────────────────────
_mongo       = MongoClient(MONGO_URL)
_db          = _mongo["roleta_db"]
history_coll: Collection = _db["history"]
signals_coll: Collection = _db["multi_pivo_signals"]

_redis = redis_lib.from_url(REDIS_URL, decode_responses=True)


# ── Ranking multi-pivô (em memória) ────────────────────────────────────────────
def expand_base(n: int) -> List[Tuple[int, str]]:
    """vizinho(1 de cada lado) + espelho + sequência (n-1, n+1)."""
    out: List[Tuple[int, str]] = []
    seen = set()

    def add(x: int, rel: str):
        if 0 <= x <= 36 and x != n and (x, rel) not in seen:
            seen.add((x, rel))
            out.append((x, rel))

    i = POS[n]
    add(WHEEL[(i - 1) % 37], 'vizinho')
    add(WHEEL[(i + 1) % 37], 'vizinho')
    if n in ESP:
        add(ESP[n], 'espelho')
    if n > 0:
        add(n - 1, 'sequencia')
    if n < 36:
        add(n + 1, 'sequencia')
    return out


def calc_ranking(history: List[int]) -> List[int]:
    """
    history[0] = giro mais recente. Reproduz /multi-pivo/api/analise com
    pivos=N_PIVOS, ocorrencias=N_OCC, 2 atrás + 2 à frente, top-K.
    """
    n = len(history)
    if n < 10:
        return []

    listas_count = [0] * 37
    total_count = [0] * 37

    for p_idx in range(min(N_PIVOS, n)):
        pivo = history[p_idx]

        # Ocorrências anteriores do pivô = índices > p_idx (mais velhos no tempo)
        occ_indices = [j for j in range(p_idx + 1, n) if history[j] == pivo][:N_OCC]
        if not occ_indices:
            continue

        peso: Dict[int, int] = {}

        def push(v: int):
            peso[v] = peso.get(v, 0) + 1

        for o in occ_indices:
            # 2 ATRÁS (pos -1, -2) = índices o+1, o+2 (mais velhos)
            for k in range(1, N_ANTES + 1):
                bi = o + k
                if bi < n:
                    v = history[bi]
                    push(v)
                    for x, _ in expand_base(v):
                        push(x)
            # 2 À FRENTE (pos +1, +2) = índices o-1, o-2 (mais novos)
            for k in range(1, N_FRENTE + 1):
                fi = o - k
                if fi >= 0:
                    v = history[fi]
                    push(v)
                    for x, _ in expand_base(v):
                        push(x)

        for v, w in peso.items():
            listas_count[v] += 1
            total_count[v] += w

    if max(listas_count) == 0:
        return []

    ranked = sorted(
        (x for x in range(37) if listas_count[x] > 0),
        key=lambda x: (-listas_count[x], -total_count[x], x),
    )
    return [int(x) for x in ranked[:TOP_K]]


# ── P&L ───────────────────────────────────────────────────────────────────────
def calc_pnl(won_at: Optional[int]) -> float:
    """12 fichas por tentativa. Vitória: +36 recebido − 12 apostado = +24 net."""
    if won_at is None:
        return float(-BET_CHIPS * MAX_ATTEMPTS)   # −48
    win_net = 36 - BET_CHIPS                       # +24
    loss    = -BET_CHIPS * (won_at - 1)            # tentativas perdidas antes
    return float(win_net + loss)


# ── Estado por roleta ──────────────────────────────────────────────────────────
class RouletteState:
    def __init__(self, roulette_id: str, initial_history: List[int]):
        self.rid     = roulette_id
        self.history: List[int] = list(initial_history[:SPINS_TO_FETCH])

        self.signal_id:  Optional[Any] = None
        self.phase:      str           = "idle"   # idle | monitoring
        self.attempts:   int           = 0
        self.bet:        List[int]     = []
        # Sinais já resolvidos em pós-tracking (rodam em paralelo, NÃO travam
        # novos sinais): [{"id": ObjectId, "bet": [...], "count": int}]
        self.post_list:  List[Dict[str, Any]] = []

        log.info("[%s] Inicializado: %d giros", roulette_id, len(self.history))

    def on_spin(self, value: int, ts: Optional[datetime] = None) -> None:
        now = ts or datetime.now(timezone.utc)

        self.history.insert(0, value)
        if len(self.history) > SPINS_TO_FETCH:
            self.history.pop()

        # Pós-tracking corre em paralelo e não bloqueia a emissão de novos sinais
        self._advance_post_tracking(value, now)

        if self.phase == "monitoring":
            self._handle_monitoring(value, now)
        else:
            self._fire_signal(value, now)

    def _fire_signal(self, trigger_value: int, now: datetime) -> None:
        ranking = calc_ranking(self.history)
        if not ranking:
            log.debug("[%s] Histórico insuficiente para calcular ranking.", self.rid)
            return

        doc = {
            "roulette_id":   self.rid,
            "status":        "monitoring",
            "trigger_value": trigger_value,
            "trigger_ts":    now,
            "pivots":        self.history[:N_PIVOS],
            "ranking":       ranking,
            "bet":           ranking,
            "bet_chips":     BET_CHIPS,
            "attempts":       [],
            "won_at_attempt": None,
            "pnl":            None,
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
                "max_attempts": MAX_ATTEMPTS,
                "post_rounds":  POST_ROUNDS,
                "n_pivos":      N_PIVOS,
                "n_occ":        N_OCC,
                "n_antes":      N_ANTES,
                "n_frente":     N_FRENTE,
                "top_k":        TOP_K,
                "bet_chips":    BET_CHIPS,
            },
        }

        result          = signals_coll.insert_one(doc)
        self.signal_id  = result.inserted_id
        self.phase      = "monitoring"
        self.attempts   = 0
        self.bet        = ranking

        log.info(
            "[%s] Sinal disparado | trigger=%d | pivots=%s | ranking=%s",
            self.rid, trigger_value, self.history[:N_PIVOS], ranking,
        )

        try:
            _redis.xadd(SIGNAL_STREAM, {
                "type":        "new_signal",
                "signal_type": "multi_pivo",
                "roulette_id": self.rid,
                "signal_id":   str(self.signal_id),
                "ranking":     json.dumps(ranking),
                "trigger":     trigger_value,
            }, maxlen=2000)
        except Exception as e:
            log.warning("[%s] Falha ao publicar no stream: %s", self.rid, e)

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
            log.info(
                "[%s] Sinal %s | %s | won_at=%s | pnl=%.0f",
                self.rid, self.signal_id, status, won_at, pnl,
            )
            # Pós-tracking em paralelo: registra e libera o worker para o
            # próximo sinal já no giro seguinte.
            self.post_list.append({"id": self.signal_id, "bet": list(self.bet), "count": 0})
            self._reset()
        else:
            signals_coll.update_one(
                {"_id": self.signal_id},
                {"$push": {"attempts": attempt_doc}},
            )
            log.debug("[%s] Tentativa %d: %d (miss)", self.rid, self.attempts, value)

    def _advance_post_tracking(self, value: int, now: datetime) -> None:
        """Avança o pós-tracking de TODOS os sinais resolvidos (em paralelo)."""
        if not self.post_list:
            return
        still_active: List[Dict[str, Any]] = []
        for pt in self.post_list:
            pt["count"] += 1
            hit = value in pt["bet"]
            round_doc = {
                "round":     pt["count"],
                "value":     value,
                "hit":       hit,
                "timestamp": now,
            }
            update: Dict[str, Any] = {"$push": {"post_tracking.rounds": round_doc}}
            if hit:
                update["$inc"] = {"post_tracking.hits": 1}

            if pt["count"] >= POST_ROUNDS:
                update.setdefault("$set", {})
                update["$set"].update({
                    "post_tracking.active":    False,
                    "post_tracking.completed": True,
                })
                signals_coll.update_one({"_id": pt["id"]}, update)
                log.info(
                    "[%s] Post-tracking concluído: sinal %s | %d/%d giros.",
                    self.rid, pt["id"], pt["count"], POST_ROUNDS,
                )
            else:
                signals_coll.update_one({"_id": pt["id"]}, update)
                still_active.append(pt)
        self.post_list = still_active

    def _reset(self) -> None:
        self.signal_id  = None
        self.phase      = "idle"
        self.attempts   = 0
        self.bet        = []


# ── Bootstrap ─────────────────────────────────────────────────────────────────
def load_initial_history(rid: str) -> List[int]:
    docs = list(
        history_coll.find({"roulette_id": rid}, {"value": 1, "_id": 0})
        .sort("timestamp", DESCENDING)
        .limit(SPINS_TO_FETCH)
    )
    return [int(d["value"]) for d in docs if 0 <= int(d.get("value", -1)) <= 36]


# ── Loop principal ─────────────────────────────────────────────────────────────
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
    slug = (data.get("slug") or data.get("roulette_id") or "").strip()
    if not slug:
        return None
    raw_val = data.get("result") if data.get("result") is not None else data.get("value")
    try:
        val = int(raw_val)
    except (TypeError, ValueError):
        return None
    return {"slug": slug, "value": val} if 0 <= val <= 36 else None


def main() -> None:
    log.info("Iniciando multi-pivo-worker | roletas=%s", ROULETTE_IDS)

    states: Dict[str, RouletteState] = {}
    for rid in ROULETTE_IDS:
        hist = load_initial_history(rid)
        log.info("[%s] %d giros carregados.", rid, len(hist))
        states[rid] = RouletteState(rid, hist)

    pubsub = _redis.pubsub()
    pubsub.subscribe(RESULT_CHANNEL)
    log.info("Inscrito em '%s'. Aguardando giros…", RESULT_CHANNEL)

    while True:
        try:
            msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg is None:
                time.sleep(0.05)
                continue

            parsed = _parse_message(msg.get("data"))
            if parsed is None:
                continue

            slug = parsed["slug"]
            if slug not in states:
                continue

            states[slug].on_spin(parsed["value"])

        except KeyboardInterrupt:
            log.info("Encerrando worker.")
            break
        except Exception as e:
            log.exception("Erro no loop principal: %s", e)
            time.sleep(2)


if __name__ == "__main__":
    main()
