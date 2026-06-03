from __future__ import annotations

# ============================================================
#  PUXADOS WORKER  —  "número seguinte às ocorrências anteriores"
# ------------------------------------------------------------
#  Lógica:
#    - A cada novo giro, o número que saiu vira GATILHO.
#    - Buscamos as ocorrências anteriores desse número nos
#      últimos LOOKBACK giros.
#    - O número imediatamente após cada ocorrência é coletado.
#    - Todos os números distintos coletados formam a APOSTA
#      (pode ser 3, 10, 12 … o que o histórico indicar).
#    - Monitoramos até MAX_ATTEMPTS giros à frente.
#    - Inversão: um número da aposta apareceu nos últimos
#      INVERSION_WINDOW giros ANTES do gatilho disparar.
#    - Sem encavalamento: sinal ativo bloqueia novos sinais.
#    - Sequências: rastreamos o top-1 de cada gatilho em sinais
#      consecutivos para detectar derivação por vizinhos físicos.
# ============================================================

import json
import logging
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import redis as redis_lib
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection

REPO_ROOT = Path(__file__).resolve().parents[3]
APPS_ROOT = REPO_ROOT / "apps"
if str(APPS_ROOT) not in sys.path:
    sys.path.insert(0, str(APPS_ROOT))

MONGO_URL = os.getenv(
    "MONGO_URL",
    "mongodb://revesbot:DlBnGmlimRZpIblr@127.0.0.1:27017/roleta_db?authSource=admin",
)
REDIS_URL     = os.getenv("REDIS_CONNECT", "redis://localhost:6379")
SIGNAL_STREAM = "streams:signals:new"

ROULETTE_IDS_RAW  = os.getenv("PUXADOS_ROULETTE_IDS") or "pragmatic-auto-roulette,pragmatic-brazilian-roulette"
LOOKBACK          = int(os.getenv("PUXADOS_LOOKBACK",          "500"))
MAX_ATTEMPTS      = int(os.getenv("PUXADOS_MAX_ATTEMPTS",      "4"))
INVERSION_WINDOW  = int(os.getenv("PUXADOS_INVERSION_WINDOW",  "4"))
MIN_OCCURRENCES   = int(os.getenv("PUXADOS_MIN_OCCUR",         "1"))
POLL_SECONDS      = float(os.getenv("PUXADOS_POLL_SECONDS",    "2"))
SEQUENCE_HISTORY  = int(os.getenv("PUXADOS_SEQ_HISTORY",       "10"))  # entradas por gatilho

# Multiplicadores de aposta por tentativa (G1-G4)
ATTEMPT_MULTIPLIERS = [1, 1, 2, 4]

# Roda física europeia (para detecção de vizinhos em sequências)
WHEEL = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30,
         8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28,
         12, 35, 3, 26]
WHEEL_IDX = {n: i for i, n in enumerate(WHEEL)}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("puxados-worker")

_mongo = MongoClient(MONGO_URL)
_db    = _mongo["roleta_db"]
history_coll:  Collection = _db["history"]
signals_coll:  Collection = _db["puxados_signals"]
sequence_coll: Collection = _db["puxados_sequence"]

_redis = redis_lib.from_url(REDIS_URL, decode_responses=True)


# ── Utilitários da roda física ───────────────────────────────

def are_wheel_neighbors(a: int, b: int, span: int = 2) -> bool:
    if a not in WHEEL_IDX or b not in WHEEL_IDX:
        return False
    ia, ib = WHEEL_IDX[a], WHEEL_IDX[b]
    dist = min(abs(ia - ib), len(WHEEL) - abs(ia - ib))
    return 0 < dist <= span


# ── Construção da aposta ─────────────────────────────────────

def build_bet(trigger: int, spins: List[int]) -> Tuple[List[int], Dict[int, int], int, Optional[int]]:
    """
    Percorre os LOOKBACK spins anteriores ao gatilho (não incluindo o próprio),
    coleta todos os números que vieram imediatamente após cada ocorrência do
    gatilho, retorna:
        bet           – lista ordenada de números únicos (a aposta)
        frequency     – {numero: quantas_vezes_seguiu_o_gatilho}
        occurrences   – total de ocorrências do gatilho na janela
        top1          – número mais frequente (tiebreak: ocorrência mais recente)
    """
    freq: Dict[int, int] = {}
    last_seen: Dict[int, int] = {}
    occ_count = 0

    n = len(spins)
    for i in range(n - 1):  # até penúltimo (o último não tem "seguinte" na janela)
        if spins[i] == trigger:
            suivant = spins[i + 1]
            freq[suivant] = freq.get(suivant, 0) + 1
            last_seen[suivant] = i
            occ_count += 1

    if not freq:
        return [], {}, occ_count, None

    bet = sorted(freq.keys())
    max_cnt = max(freq.values())
    cands = [n for n, c in freq.items() if c == max_cnt]
    top1 = max(cands, key=lambda x: last_seen.get(x, -1))

    return bet, freq, occ_count, top1


# ── Sequência: rastreamento por gatilho ──────────────────────

def get_sequence_info(rid: str, trigger: int, curr_top1: Optional[int]) -> Dict[str, Any]:
    """Retorna info de sequência e atualiza puxados_sequence (chamado só ao criar sinal)."""
    key = {"roulette_id": rid, "trigger": trigger}
    doc = sequence_coll.find_one(key)

    history: List[Dict] = doc.get("history", []) if doc else []
    prev_top1: Optional[int] = history[-1]["top1"] if history else None

    if curr_top1 is None:
        seq_type = "sem_top1"
    elif prev_top1 is None:
        seq_type = "primeiro"
    elif prev_top1 == curr_top1:
        seq_type = "mesmo"
    elif are_wheel_neighbors(prev_top1, curr_top1):
        seq_type = "vizinho"
    else:
        seq_type = "outro"

    return {
        "trigger":          trigger,
        "curr_top1":        curr_top1,
        "prev_top1":        prev_top1,
        "type":             seq_type,
        "is_neighbor":      seq_type == "vizinho",
        "history_len":      len(history),
    }


def update_sequence(rid: str, trigger: int, signal_id: Any, top1: Optional[int], ts: Any) -> None:
    key = {"roulette_id": rid, "trigger": trigger}
    entry = {"signal_id": str(signal_id), "top1": top1, "ts": ts}
    sequence_coll.update_one(
        key,
        {
            "$push": {"history": {"$each": [entry], "$slice": -SEQUENCE_HISTORY}},
            "$set":  {"roulette_id": rid, "trigger": trigger, "updated_at": datetime.now(tz=timezone.utc)},
        },
        upsert=True,
    )


# ── Infra ────────────────────────────────────────────────────

def resolve_target_roulettes() -> List[str]:
    raw = (ROULETTE_IDS_RAW or "").strip()
    if not raw or raw.lower() in ("all", "*"):
        return sorted(
            s for s in history_coll.distinct("roulette_id")
            if isinstance(s, str) and s.startswith("pragmatic-")
        )
    return [s.strip() for s in raw.split(",") if s.strip()]


def ensure_indexes() -> None:
    signals_coll.create_index([("roulette_id", ASCENDING), ("status", ASCENDING)])
    signals_coll.create_index([("created_at", DESCENDING)])
    signals_coll.create_index([("trigger", ASCENDING)])
    signals_coll.create_index([("status", ASCENDING)])
    sequence_coll.create_index([("roulette_id", ASCENDING), ("trigger", ASCENDING)], unique=True)


def get_recent_spins(rid: str, n: int) -> Tuple[List[int], Optional[Any]]:
    """Retorna (valores_cronológicos, timestamp_do_mais_recente)."""
    docs = list(
        history_coll.find({"roulette_id": rid}, {"value": 1, "timestamp": 1})
        .sort("timestamp", DESCENDING).limit(n)
    )
    if not docs:
        return [], None
    docs.reverse()
    return [int(d["value"]) for d in docs], docs[-1]["timestamp"]


# ── Criação do sinal ─────────────────────────────────────────

def create_signal(
    rid: str,
    trigger: int,
    trigger_ts: Any,
    bet: List[int],
    frequency: Dict[int, int],
    occurrences: int,
    top1: Optional[int],
    recent_spins: List[int],
) -> Dict[str, Any]:
    now = datetime.now(tz=timezone.utc)

    # Inversão: algum número da aposta apareceu nos últimos INVERSION_WINDOW
    # giros ANTES do gatilho (recent_spins[-1] = trigger; olhamos antes dele)
    inv_window = recent_spins[-(INVERSION_WINDOW + 1):-1] if len(recent_spins) > INVERSION_WINDOW else recent_spins[:-1]
    bet_set    = set(bet)
    inv_hits   = [v for v in inv_window if v in bet_set]
    inversion  = {
        "window":      inv_window,
        "window_size": INVERSION_WINDOW,
        "hits":        inv_hits,
        "hit_count":   len(inv_hits),
        "paid":        len(inv_hits) > 0,
    }

    # Sequência
    seq_info = get_sequence_info(rid, trigger, top1)

    doc = {
        "roulette_id":    rid,
        "status":         "monitoring",
        "trigger":        trigger,
        "trigger_ts":     trigger_ts,
        "occurrences":    occurrences,
        "bet":            bet,
        "bet_size":       len(bet),
        "frequency":      {str(k): v for k, v in frequency.items()},
        "top1":           top1,
        "inversion":      inversion,
        "sequence_info":  seq_info,
        "attempts":       [],
        "won_at_attempt": None,
        "pnl":            None,
        "created_at":     now,
        "resolved_at":    None,
        "config": {
            "lookback":          LOOKBACK,
            "max_attempts":      MAX_ATTEMPTS,
            "inversion_window":  INVERSION_WINDOW,
            "min_occurrences":   MIN_OCCURRENCES,
            "multipliers":       ATTEMPT_MULTIPLIERS,
        },
    }
    result = signals_coll.insert_one(doc)
    doc["_id"] = result.inserted_id

    update_sequence(rid, trigger, result.inserted_id, top1, trigger_ts)

    log.info(
        "[%s] SINAL trigger=%d occ=%d bet_size=%d top1=%s seq=%s inv=%s",
        rid, trigger, occurrences, len(bet), top1,
        seq_info["type"], inversion["paid"],
    )
    try:
        _redis.xadd(SIGNAL_STREAM, {
            "signal_id": str(result.inserted_id),
            "data": json.dumps({
                "id":          str(result.inserted_id),
                "roulette_id": rid,
                "trigger":     trigger,
                "top1":        top1,
                "bet_size":    len(bet),
                "seq_type":    seq_info["type"],
                "type":        "new_signal",
                "source":      "puxados",
            }),
        }, maxlen=200)
    except Exception as exc:
        log.warning("[%s] falha ao publicar no Redis stream: %s", rid, exc)

    return doc


# ── Loop principal ───────────────────────────────────────────

def process_roulette(rid: str, st: Dict[str, Any]) -> None:
    spins, latest_ts = get_recent_spins(rid, LOOKBACK + INVERSION_WINDOW + 10)
    if not spins:
        return
    if st.get("last_ts") is not None and latest_ts <= st["last_ts"]:
        return
    st["last_ts"] = latest_ts

    latest_val = spins[-1]
    active     = st.get("active")

    # 1. Tentativa do sinal ativo
    if active is not None:
        attempt_num = len(active.get("attempts", [])) + 1
        mult = ATTEMPT_MULTIPLIERS[attempt_num - 1] if attempt_num <= len(ATTEMPT_MULTIPLIERS) else ATTEMPT_MULTIPLIERS[-1]
        hit  = latest_val in active["bet"]
        entry = {
            "attempt":    attempt_num,
            "value":      latest_val,
            "hit":        hit,
            "timestamp":  latest_ts,
            "multiplier": mult,
        }

        if hit:
            bet_size    = active["bet_size"]
            all_att     = active.get("attempts", []) + [entry]
            total_cost  = sum(
                bet_size * (ATTEMPT_MULTIPLIERS[a["attempt"] - 1] if a["attempt"] <= len(ATTEMPT_MULTIPLIERS) else ATTEMPT_MULTIPLIERS[-1])
                for a in all_att
            )
            pnl = 36 * mult - total_cost
            signals_coll.update_one(
                {"_id": active["_id"]},
                {"$set": {"status": "won", "won_at_attempt": attempt_num,
                          "resolved_at": datetime.now(tz=timezone.utc), "pnl": pnl},
                 "$push": {"attempts": entry}},
            )
            log.info("[%s] WON attempt=%d value=%d pnl=%+d", rid, attempt_num, latest_val, pnl)
            active = None

        elif attempt_num >= MAX_ATTEMPTS:
            bet_size   = active["bet_size"]
            total_cost = bet_size * sum(ATTEMPT_MULTIPLIERS[:MAX_ATTEMPTS])
            pnl        = -total_cost
            signals_coll.update_one(
                {"_id": active["_id"]},
                {"$set": {"status": "lost", "resolved_at": datetime.now(tz=timezone.utc), "pnl": pnl},
                 "$push": {"attempts": entry}},
            )
            log.info("[%s] LOST após %d tentativas pnl=%+d", rid, MAX_ATTEMPTS, pnl)
            active = None

        else:
            signals_coll.update_one({"_id": active["_id"]}, {"$push": {"attempts": entry}})
            active.setdefault("attempts", []).append(entry)
            log.info("[%s] attempt %d/%d: %d (%s) mult=×%d",
                     rid, attempt_num, MAX_ATTEMPTS, latest_val, "HIT" if hit else "miss", mult)

    # 2. Novo sinal (sem encavalamento)
    if active is None:
        # janela de análise: todos os spins menos o último (que é o gatilho)
        window = spins[:-1][-LOOKBACK:]
        bet, frequency, occurrences, top1 = build_bet(latest_val, window)

        if occurrences >= MIN_OCCURRENCES and bet:
            active = create_signal(
                rid, latest_val, latest_ts,
                bet, frequency, occurrences, top1, spins,
            )
        else:
            log.debug("[%s] gatilho=%d sem ocorrências suficientes (%d)", rid, latest_val, occurrences)

    st["active"] = active


def main() -> None:
    ensure_indexes()

    targets = resolve_target_roulettes()
    if not targets:
        log.error("Nenhuma roleta para monitorar. PUXADOS_ROULETTE_IDS=%s", ROULETTE_IDS_RAW)
        return

    log.info(
        "Worker PUXADOS iniciado. roletas=%d lookback=%d max_attempts=%d inv_window=%d min_occur=%d poll=%ss",
        len(targets), LOOKBACK, MAX_ATTEMPTS, INVERSION_WINDOW, MIN_OCCURRENCES, POLL_SECONDS,
    )
    log.info("Roletas monitoradas: %s", ", ".join(targets))

    state: Dict[str, Dict[str, Any]] = {}
    for rid in targets:
        active = signals_coll.find_one(
            {"roulette_id": rid, "status": "monitoring"},
            sort=[("created_at", DESCENDING)],
        )
        last_ts: Optional[Any] = None
        if active and active.get("attempts"):
            last_ts = max(a["timestamp"] for a in active["attempts"])
        elif active:
            last_ts = active.get("trigger_ts")
        state[rid] = {"active": active, "last_ts": last_ts}
        if active:
            log.info("[%s] sinal ativo retomado id=%s trigger=%d bet_size=%d attempts=%d",
                     rid, active["_id"], active.get("trigger"), active.get("bet_size"),
                     len(active.get("attempts", [])))

    while True:
        for rid in targets:
            try:
                process_roulette(rid, state[rid])
            except Exception as exc:
                log.exception("[%s] erro: %s", rid, exc)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
