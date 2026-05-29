#!/usr/bin/env python3
"""
Worker NÚMEROS FORTES — framework determinístico de "números que se puxam".

A cada novo giro recalcula o ranking ponderado (recência dominante + repetição
de ciclo + terminais + cavalos + espelhos + proteção do zero), produzindo
`numeros_fortes` (grupo conectado) e `gatilhos` (subconjunto que dispara a
aposta). Quando o número que acabou de sair é um gatilho, abre um sinal
(paper-trading) apostando nos números fortes e acompanha o resultado por até
MAX_ATTEMPTS giros (imediata + gales 1,1,2,4).

Espelha a arquitetura de triplet_terminal_worker.py: poll → Mongo + Redis stream.
NÃO executa apostas reais.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections import defaultdict
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
REDIS_URL = os.getenv("REDIS_CONNECT", "redis://localhost:6379")
SIGNAL_STREAM = "streams:signals:new"

ROULETTE_IDS_RAW = (
    os.getenv("NUMEROS_FORTES_ROULETTE_IDS")
    or "pragmatic-auto-roulette,pragmatic-brazilian-roulette,pragmatic-mega-roulette"
)
SPINS_TO_FETCH = int(os.getenv("NUMEROS_FORTES_SPINS", "500"))
FORTES_COUNT   = int(os.getenv("NUMEROS_FORTES_COUNT", "13"))
GATILHOS_MAX   = int(os.getenv("NUMEROS_FORTES_GATILHOS_MAX", "8"))
RECENT_WINDOW  = int(os.getenv("NUMEROS_FORTES_RECENT_WINDOW", "50"))
MAX_ATTEMPTS   = int(os.getenv("NUMEROS_FORTES_MAX_ATTEMPTS", "4"))
POLL_SECONDS   = float(os.getenv("NUMEROS_FORTES_POLL_SECONDS", "2"))
MIN_HISTORY    = int(os.getenv("NUMEROS_FORTES_MIN_HISTORY", "20"))

# Multiplicador de aposta por tentativa: G1-G2 flat, G3 dobra, G4 quadruplica
ATTEMPT_MULTIPLIERS = [1, 1, 2, 4]

# ── Constantes do framework ─────────────────────────────────────────────────
CAVALOS: Dict[str, set] = {
    "147": {1, 4, 7, 11, 14, 17, 21, 24, 27, 31, 34},
    "258": {2, 5, 8, 12, 15, 18, 22, 25, 28, 32, 35},
    "369": {3, 6, 9, 13, 16, 19, 23, 26, 29, 33, 36},
    "047": {0, 10, 20, 30, 4, 14, 24, 34, 7, 17, 27},
}
_ESPELHOS = [(1, 10), (2, 20), (3, 30), (12, 21), (13, 31), (23, 32), (11, 22), (22, 33), (11, 33)]
MIRROR_MAP: Dict[int, set] = defaultdict(set)
for _a, _b in _ESPELHOS:
    MIRROR_MAP[_a].add(_b)
    MIRROR_MAP[_b].add(_a)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("numeros-fortes-worker")

_mongo = MongoClient(MONGO_URL)
_db = _mongo["roleta_db"]
history_coll: Collection = _db["history"]
signals_coll: Collection = _db["numeros_fortes_signals"]
live_coll: Collection = _db["numeros_fortes_live"]

_redis = redis_lib.from_url(REDIS_URL, decode_responses=True)


# ── Scoring determinístico ──────────────────────────────────────────────────

def recency_weight(i: int) -> float:
    """Peso por posição. i=0 é o mais recente. Recência é o peso dominante."""
    if i < 20:
        return 3.0
    if i < 50:
        return 2.0
    if i < 100:
        return 1.0
    return 0.3


def terminal_of(n: int) -> int:
    return n % 10


def compute_analysis(values: List[int]) -> Dict[str, Any]:
    """values: mais-recente-primeiro (values[0] = último a sair). NÃO inverter."""
    n = len(values)
    wfreq: Dict[int, float] = defaultdict(float)
    for i, x in enumerate(values):
        wfreq[x] += recency_weight(i)

    # transições: g (mais antigo = values[i+1]) puxa a (mais recente = values[i])
    trans: Dict[int, Dict[int, float]] = defaultdict(lambda: defaultdict(float))
    for i in range(n - 1):
        g = values[i + 1]
        a = values[i]
        trans[g][a] += recency_weight(i)
    pulled = {num: sum(trans[g].get(num, 0.0) for g in trans) for num in range(37)}

    term_act: Dict[int, float] = defaultdict(float)
    for num in range(37):
        term_act[terminal_of(num)] += wfreq.get(num, 0.0)

    cav_act = {name: sum(wfreq.get(x, 0.0) for x in members) for name, members in CAVALOS.items()}

    def max_cavalo_act(num: int) -> float:
        acts = [cav_act[name] for name, members in CAVALOS.items() if num in members]
        return max(acts) if acts else 0.0

    recent = set(values[:RECENT_WINDOW])

    score: Dict[int, float] = {}
    for num in range(37):
        s = (
            wfreq.get(num, 0.0)
            + 0.5 * pulled[num]
            + 0.20 * term_act[terminal_of(num)]
            + 0.12 * max_cavalo_act(num)
        )
        if num in recent and any(m in recent for m in MIRROR_MAP.get(num, ())):
            s += 3.0
        score[num] = s

    # zero ganha força com 10/20/30 recentes e cavalo 047
    if 0 in recent or any(x in recent for x in (10, 20, 30)):
        score[0] += 0.25 * cav_act["047"]

    ranked = sorted(range(37), key=lambda x: (-score[x], x))
    fortes = sorted(ranked[:FORTES_COUNT])
    fortes_set = set(fortes)

    def trig(g: int) -> Tuple[float, int]:
        al = [(a, w) for a, w in trans[g].items() if a in fortes_set and a != g]
        if not al:
            return 0.0, 0
        weight = sum(w for _, w in al) * (1 + 0.3 * (len(al) - 1))
        return weight, len(al)

    cand: List[Tuple[int, float, int]] = []
    for g in fortes:
        if g not in recent:
            continue
        w, fanout = trig(g)
        if w > 0:
            cand.append((g, w, fanout))
    cand.sort(key=lambda t: (-t[1], t[0]))
    chosen = cand[:GATILHOS_MAX]
    gatilhos = sorted(g for g, _, _ in chosen)
    gatilho_meta = {g: {"weight": round(w, 3), "fanout": fanout} for g, w, fanout in chosen}

    score_top = [{"number": num, "score": round(score[num], 3)} for num in ranked[:FORTES_COUNT]]

    return {
        "numeros_fortes": fortes,
        "gatilhos": gatilhos,
        "gatilho_meta": gatilho_meta,
        "score_top": score_top,
    }


def strength_from_fanout(fanout: int) -> str:
    if fanout >= 5:
        return "muito_forte"
    if fanout >= 3:
        return "forte"
    if fanout == 2:
        return "mediano"
    return "fraco"


# ── Infra ───────────────────────────────────────────────────────────────────

def resolve_target_roulettes() -> List[str]:
    raw = (ROULETTE_IDS_RAW or "").strip()
    if not raw or raw.lower() in ("all", "*"):
        slugs = [
            s for s in history_coll.distinct("roulette_id")
            if isinstance(s, str) and s.startswith("pragmatic-")
        ]
        return sorted(slugs)
    return [s.strip() for s in raw.split(",") if s.strip()]


def ensure_indexes() -> None:
    signals_coll.create_index([("roulette_id", ASCENDING), ("status", ASCENDING)])
    signals_coll.create_index([("created_at", DESCENDING)])
    signals_coll.create_index([("strength", ASCENDING)])


def get_recent_values(rid: str, n: int) -> Tuple[List[int], Optional[Any]]:
    docs = list(
        history_coll.find(
            {"roulette_id": rid},
            {"value": 1, "timestamp": 1},
        ).sort("timestamp", DESCENDING).limit(n)
    )
    if not docs:
        return [], None
    values = [int(d["value"]) for d in docs]   # values[0] = mais recente
    return values, docs[0]["timestamp"]


def update_live(rid: str, analysis: Dict[str, Any], values: List[int], has_active: bool) -> None:
    live_coll.update_one(
        {"_id": rid},
        {"$set": {
            "roulette_id": rid,
            "numeros_fortes": analysis["numeros_fortes"],
            "gatilhos": analysis["gatilhos"],
            "score_top": analysis["score_top"],
            "last_numbers": values[:15],
            "has_active_signal": has_active,
            "updated_at": datetime.now(tz=timezone.utc),
        }},
        upsert=True,
    )


def create_signal(rid: str, gatilho: int, analysis: Dict[str, Any], values: List[int], trigger_ts: Any) -> Dict[str, Any]:
    now = datetime.now(tz=timezone.utc)
    fortes = analysis["numeros_fortes"]
    meta = analysis["gatilho_meta"].get(gatilho, {"weight": 0.0, "fanout": 0})
    strength = strength_from_fanout(meta["fanout"])
    doc = {
        "roulette_id":       rid,
        "status":            "monitoring",
        "gatilho":           gatilho,
        "gatilho_weight":    meta["weight"],
        "gatilho_fanout":    meta["fanout"],
        "numeros_fortes":    fortes,
        "gatilhos_snapshot": analysis["gatilhos"],
        "bet":               fortes,
        "fortes_count":      len(fortes),
        "strength":          strength,
        "score_top":         analysis["score_top"],
        "last_numbers":      values[:15],
        "window_size":       len(values),
        "X_timestamp":       trigger_ts,
        "attempts":          [],
        "won_at_attempt":    None,
        "pnl":               None,
        "created_at":        now,
        "resolved_at":       None,
        "config": {
            "spins":         SPINS_TO_FETCH,
            "fortes_count":  FORTES_COUNT,
            "gatilhos_max":  GATILHOS_MAX,
            "recent_window": RECENT_WINDOW,
            "max_attempts":  MAX_ATTEMPTS,
            "multipliers":   ATTEMPT_MULTIPLIERS,
        },
    }
    result = signals_coll.insert_one(doc)
    doc["_id"] = result.inserted_id
    log.info(
        "[%s] SIGNAL gatilho=%d strength=%s fanout=%d fortes=%s",
        rid, gatilho, strength, meta["fanout"], fortes,
    )
    try:
        _redis.xadd(SIGNAL_STREAM, {
            "signal_id": str(result.inserted_id),
            "data": json.dumps({
                "id":             str(result.inserted_id),
                "roulette_id":    rid,
                "gatilho":        gatilho,
                "strength":       strength,
                "numeros_fortes": fortes,
                "type":           "new_signal",
            }),
        }, maxlen=200)
    except Exception as exc:
        log.warning("[%s] falha ao publicar no Redis stream: %s", rid, exc)
    return doc


def process_roulette(rid: str, st: Dict[str, Any]) -> None:
    values, latest_ts = get_recent_values(rid, SPINS_TO_FETCH)
    if not values:
        return
    if st.get("last_ts") is not None and latest_ts <= st["last_ts"]:
        return
    st["last_ts"] = latest_ts
    latest_val = values[0]

    active = st.get("active")

    # 1. Tentativa do sinal ativo
    if active is not None:
        attempt_num = len(active.get("attempts", [])) + 1
        multiplier = ATTEMPT_MULTIPLIERS[attempt_num - 1] if attempt_num <= len(ATTEMPT_MULTIPLIERS) else ATTEMPT_MULTIPLIERS[-1]
        hit = latest_val in active["bet"]
        entry = {"attempt": attempt_num, "value": latest_val, "hit": hit, "timestamp": latest_ts, "multiplier": multiplier}
        if hit:
            bet_size = len(active.get("bet", []))
            all_attempts = active.get("attempts", []) + [entry]
            total_cost = sum(
                bet_size * (ATTEMPT_MULTIPLIERS[a["attempt"] - 1] if a["attempt"] <= len(ATTEMPT_MULTIPLIERS) else ATTEMPT_MULTIPLIERS[-1])
                for a in all_attempts
            )
            pnl = 36 * multiplier - total_cost
            signals_coll.update_one(
                {"_id": active["_id"]},
                {"$set": {"status": "won", "won_at_attempt": attempt_num,
                          "resolved_at": datetime.now(tz=timezone.utc), "pnl": pnl},
                 "$push": {"attempts": entry}},
            )
            log.info("[%s] WON attempt=%d value=%d pnl=%+d", rid, attempt_num, latest_val, pnl)
            active = None
        elif attempt_num >= MAX_ATTEMPTS:
            bet_size = len(active.get("bet", []))
            total_cost = bet_size * sum(ATTEMPT_MULTIPLIERS[:MAX_ATTEMPTS])
            pnl = -total_cost
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
            log.info("[%s] attempt %d/%d: %d (%s) mult=×%d", rid, attempt_num, MAX_ATTEMPTS, latest_val,
                     "HIT" if hit else "miss", multiplier)

    # 2. Recalcula a análise a cada número
    if len(values) >= MIN_HISTORY:
        analysis = compute_analysis(values)
    else:
        analysis = {"numeros_fortes": [], "gatilhos": [], "gatilho_meta": {}, "score_top": []}

    # 3. Novo sinal se nenhum ativo E o número que saiu é um gatilho
    if active is None and analysis["gatilhos"] and latest_val in analysis["gatilhos"]:
        active = create_signal(rid, latest_val, analysis, values, latest_ts)

    st["active"] = active

    # 4. Snapshot ao vivo (cálculo ajustado a cada número)
    update_live(rid, analysis, values, active is not None)


def main() -> None:
    ensure_indexes()

    targets = resolve_target_roulettes()
    if not targets:
        log.error("Nenhuma roleta para monitorar. NUMEROS_FORTES_ROULETTE_IDS=%s", ROULETTE_IDS_RAW)
        return

    log.info(
        "Worker iniciado. roletas=%d spins=%d fortes=%d gatilhos_max=%d max_attempts=%d poll=%ss",
        len(targets), SPINS_TO_FETCH, FORTES_COUNT, GATILHOS_MAX, MAX_ATTEMPTS, POLL_SECONDS,
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
            last_ts = active.get("X_timestamp")
        state[rid] = {"active": active, "last_ts": last_ts}
        if active:
            log.info("[%s] sinal ativo retomado id=%s attempts=%d",
                     rid, active["_id"], len(active.get("attempts", [])))

    while True:
        for rid in targets:
            try:
                process_roulette(rid, state[rid])
            except Exception as exc:
                log.exception("[%s] erro: %s", rid, exc)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
