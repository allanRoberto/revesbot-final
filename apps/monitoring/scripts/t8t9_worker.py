from __future__ import annotations

"""Double Malice Terminal 3 — T8T9 Worker
==========================================
Padrão: dois clusters de terminais 8/9 no histórico, separados por >= 6 posições,
com pelo menos um cluster "forte" (>=2 de T8 E >=2 de T9).
Gatilho: último número saído é terminal 8 ou 9.
Fundo limpo: nenhum zero nas posições 1–4 anteriores ao gatilho.
Aposta: [0, 8, 9, 18, 19, 28, 29] — 7 números.
Multiplicadores: [1.0, 1.5, 2.0, 3.0] (4 tentativas).
"""

import json
import logging
import math
import os
import sys
import time
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
REDIS_URL        = os.getenv("REDIS_CONNECT", "redis://localhost:6379")
SIGNAL_STREAM    = "streams:signals:new"
ROULETTE_IDS_RAW = (
    os.getenv("T8T9_ROULETTE_IDS")
    or "pragmatic-auto-roulette,pragmatic-brazilian-roulette"
)
SPINS_TO_FETCH   = int(os.getenv("T8T9_SPINS",        "500"))
PRE_WINDOW       = int(os.getenv("T8T9_PRE_WINDOW",   "10"))   # últimas 10 para exibição e inversão
MAX_ATTEMPTS     = int(os.getenv("T8T9_MAX_ATTEMPTS", "4"))
MAX_POST_TRACK   = int(os.getenv("T8T9_MAX_POST",     "10"))   # 10 rodadas pós-derrota
POLL_SECONDS     = float(os.getenv("T8T9_POLL_SECONDS", "2"))
MIN_PROFIT       = float(os.getenv("T8T9_MIN_PROFIT",  "1.0"))

# Payout por slug (mega = 30, demais = 36)
PAYOUT_MAP = {
    "pragmatic-mega-roulette":            30,
    "pragmatic-mega-roulette-brazilian":  30,
    "pragmatic-auto-mega-roulette":       30,
    "pragmatic-turkish-mega-roulette":    30,
    "pragmatic-italian-mega-roulette":    30,
}

# Aposta fixa: terminais 8 e 9 + zero
BET_NUMBERS: List[int] = sorted([n for n in range(37) if n % 10 in (8, 9)] + [0])
# = [0, 8, 9, 18, 19, 28, 29]


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("t8t9-worker")

_mongo = MongoClient(MONGO_URL)
_db    = _mongo["roleta_db"]
history_coll: Collection = _db["history"]
signals_coll: Collection = _db["t8t9_signals"]

_redis = redis_lib.from_url(REDIS_URL, decode_responses=True)


# ─── helpers ──────────────────────────────────────────────────────────────────

def get_payout(slug: str) -> int:
    return PAYOUT_MAP.get(slug, 36)


def calc_multipliers(bet_count: int, steps: int, payout: int = 36, min_profit: float = 1.0) -> List[float]:
    """Multipliers dinâmicos idênticos ao RouletteMath.calculate_dynamic_mults do script original."""
    if steps == 2:
        return [1.0, 1.0]
    mults: List[float] = []
    cost = 0.0
    for i in range(steps):
        if i == 0:
            m = 1.0
        else:
            if payout > bet_count:
                raw_m = math.ceil((cost + min_profit) / (payout - bet_count))
                if steps == 3:
                    fallback = [1.0, 2.0, 3.0][i]
                elif steps == 4:
                    fallback = [1.0, 1.5, 2.0, 3.0][i]
                else:
                    fallback = mults[-1] * 2.0
                m = max(float(raw_m), fallback)
            else:
                m = mults[-1] * 2.0
        mults.append(float(m))
        cost += bet_count * float(m)
    return mults


def get_clusters(raw: List[int], tA: int = 8, tB: int = 9) -> List[Dict[str, Any]]:
    """Encontra clusters de números terminal-tA ou terminal-tB no histórico.

    raw[0] = mais recente. Começa em i=1 (pula o gatilho atual).
    Um cluster é um grupo de posições onde a distância entre posições consecutivas <= 3.
    """
    clusters: List[List[int]] = []
    curr_cl: List[int] = []

    for i in range(1, len(raw)):
        if raw[i] % 10 in (tA, tB):
            if not curr_cl:
                curr_cl.append(i)
            elif i - curr_cl[-1] <= 3:
                curr_cl.append(i)
            else:
                if len(curr_cl) >= 2:
                    clusters.append(curr_cl)
                curr_cl = [i]
    if len(curr_cl) >= 2:
        clusters.append(curr_cl)

    parsed: List[Dict[str, Any]] = []
    for cl in clusters:
        terms = [raw[i] % 10 for i in cl]
        cA = terms.count(tA)
        cB = terms.count(tB)
        # start = posição mais antiga (maior índice), end = mais recente (menor índice)
        parsed.append({
            "start":  max(cl),
            "end":    min(cl),
            "strong": (cA >= 2 and cB >= 2),
            "count":  len(cl),
            "t8":     cA,
            "t9":     cB,
        })
    return parsed


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
    signals_coll.create_index([("status", ASCENDING), ("needs_post_track", ASCENDING)])
    signals_coll.create_index([("has_strong_cluster", ASCENDING)])


def get_recent_spins(rid: str, n: int) -> List[Dict[str, Any]]:
    docs = list(
        history_coll.find(
            {"roulette_id": rid},
            {"value": 1, "timestamp": 1},
        ).sort("timestamp", DESCENDING).limit(n)
    )
    docs.reverse()  # mais antigo primeiro
    return [{"value": int(d["value"]), "timestamp": d["timestamp"]} for d in docs]


def try_generate_signal(spins: List[Dict], slug: str) -> Optional[Dict[str, Any]]:
    """Aplica a lógica DoubleMaliceTerm3Engine.analyze do script original."""
    if len(spins) < 20:
        return None

    # Converte para raw[0]=mais recente (inverso de spins que é oldest-first)
    raw = [spins[-(i + 1)]["value"] for i in range(len(spins))]
    timestamps = [spins[-(i + 1)]["timestamp"] for i in range(len(spins))]

    curr = raw[0]
    T_curr = curr % 10

    # Fundo limpo: nenhum zero nas posições 1–4
    if 0 in raw[1:5]:
        return None

    # Gatilho: terminal deve ser 8 ou 9
    if T_curr not in (8, 9):
        return None

    clusters = get_clusters(raw, tA=8, tB=9)
    if len(clusters) < 2:
        return None

    base_found = False
    strong_cluster = False
    for i in range(len(clusters)):
        if clusters[i]["start"] < 6:
            continue
        for j in range(i + 1, len(clusters)):
            if clusters[j]["start"] - clusters[i]["end"] >= 6:
                if clusters[i]["strong"] or clusters[j]["strong"]:
                    base_found = True
                    strong_cluster = clusters[i]["strong"] or clusters[j]["strong"]
                    break
        if base_found:
            break

    if not base_found:
        return None

    trigger_ts = spins[-1]["timestamp"]

    # Pré-janela: raw[1:PRE_WINDOW+1] (10 números antes do gatilho)
    pre_window = raw[1: PRE_WINDOW + 1]
    pre_window_ts = timestamps[1: PRE_WINDOW + 1]

    # Últimas 10 para exibição (igual ao fundo_str do script original)
    last_10 = raw[1:11]

    payout = get_payout(slug)

    return {
        "trigger_val":       curr,
        "trigger_terminal":  T_curr,
        "trigger_ts":        trigger_ts,
        "last_10":           last_10,
        "clusters":          clusters[:5],   # guarda até 5 clusters para diagnóstico
        "cluster_count":     len(clusters),
        "has_strong_cluster": strong_cluster,
        "pre_window":        pre_window,
        "pre_window_ts":     pre_window_ts,
        "payout":            payout,
    }


def create_signal(rid: str, info: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(tz=timezone.utc)
    payout = info["payout"]
    mults  = calc_multipliers(len(BET_NUMBERS), MAX_ATTEMPTS, payout=payout, min_profit=MIN_PROFIT)

    pre_window = info.get("pre_window", []) or []
    inversion_paid_before = any(v in BET_NUMBERS for v in pre_window)

    doc = {
        "roulette_id":        rid,
        "status":             "monitoring",
        "trigger_val":        info["trigger_val"],
        "trigger_terminal":   info["trigger_terminal"],
        "last_10":            info["last_10"],
        "cluster_count":      info["cluster_count"],
        "has_strong_cluster": info["has_strong_cluster"],
        "clusters":           info["clusters"],
        "bet":                BET_NUMBERS,
        "multipliers":        mults,
        "payout":             payout,
        "pre_window":         pre_window,
        "pre_window_ts":      info.get("pre_window_ts", []),
        "inversion_paid_before": inversion_paid_before,
        "X_timestamp":        info["trigger_ts"],
        "attempts":           [],
        "won_at_attempt":     None,
        "pnl":                None,
        "post_attempts":      [],
        "needs_post_track":   False,
        "created_at":         now,
        "resolved_at":        None,
        "config": {
            "pre_window":   PRE_WINDOW,
            "max_attempts": MAX_ATTEMPTS,
            "max_post":     MAX_POST_TRACK,
            "min_profit":   MIN_PROFIT,
            "payout":       payout,
            "multipliers":  mults,
        },
    }
    result = signals_coll.insert_one(doc)
    doc["_id"] = result.inserted_id
    log.info(
        "[%s] SIGNAL trigger=%d terminal=T%d strong=%s clusters=%d bet_size=%d mults=%s inv=%s",
        rid, info["trigger_val"], info["trigger_terminal"],
        info["has_strong_cluster"], info["cluster_count"],
        len(BET_NUMBERS), mults, inversion_paid_before,
    )
    try:
        _redis.xadd(SIGNAL_STREAM, {
            "signal_id": str(result.inserted_id),
            "data": json.dumps({
                "id":          str(result.inserted_id),
                "roulette_id": rid,
                "trigger_val": info["trigger_val"],
                "type":        "new_signal",
                "source":      "t8t9",
            }),
        }, maxlen=200)
    except Exception as exc:
        log.warning("[%s] falha ao publicar sinal no Redis: %s", rid, exc)
    return doc


def process_roulette(rid: str, st: Dict[str, Any]) -> None:
    latest_doc = history_coll.find_one(
        {"roulette_id": rid},
        {"value": 1, "timestamp": 1},
        sort=[("timestamp", DESCENDING)],
    )
    if not latest_doc:
        return

    latest_ts  = latest_doc["timestamp"]
    latest_val = int(latest_doc["value"])

    if st.get("last_ts") is not None and latest_ts <= st["last_ts"]:
        return
    st["last_ts"] = latest_ts

    active = st.get("active")

    # 1. Processar tentativa do sinal ativo
    if active is not None:
        attempt_num = len(active.get("attempts", [])) + 1
        mults       = active.get("multipliers", calc_multipliers(len(BET_NUMBERS), MAX_ATTEMPTS))
        multiplier  = mults[attempt_num - 1] if attempt_num <= len(mults) else mults[-1]
        hit         = latest_val in active["bet"]
        entry       = {
            "attempt": attempt_num, "value": latest_val, "hit": hit,
            "timestamp": latest_ts, "multiplier": multiplier,
        }

        if hit:
            bet_size    = len(active["bet"])
            all_att     = active.get("attempts", []) + [entry]
            total_cost  = sum(
                bet_size * (mults[a["attempt"] - 1] if a["attempt"] <= len(mults) else mults[-1])
                for a in all_att
            )
            pnl = active.get("payout", 36) * multiplier - total_cost
            signals_coll.update_one(
                {"_id": active["_id"]},
                {"$set": {
                    "status":         "won",
                    "won_at_attempt": attempt_num,
                    "resolved_at":    datetime.now(tz=timezone.utc),
                    "pnl":            round(pnl, 2),
                }, "$push": {"attempts": entry}},
            )
            log.info("[%s] WON attempt=%d value=%d pnl=%+.2f", rid, attempt_num, latest_val, pnl)
            active = None

        elif attempt_num >= MAX_ATTEMPTS:
            bet_size   = len(active["bet"])
            total_cost = bet_size * sum(mults[:MAX_ATTEMPTS])
            pnl        = -total_cost
            signals_coll.update_one(
                {"_id": active["_id"]},
                {"$set": {
                    "status":           "lost",
                    "resolved_at":      datetime.now(tz=timezone.utc),
                    "needs_post_track": True,
                    "pnl":              round(pnl, 2),
                }, "$push": {"attempts": entry}},
            )
            log.info("[%s] LOST apos %d tentativas pnl=%+.2f", rid, MAX_ATTEMPTS, pnl)
            active = None

        else:
            signals_coll.update_one({"_id": active["_id"]}, {"$push": {"attempts": entry}})
            active.setdefault("attempts", []).append(entry)
            log.info("[%s] attempt %d/%d: %d (%s) mult=×%.1f",
                     rid, attempt_num, MAX_ATTEMPTS, latest_val,
                     "HIT" if hit else "miss", multiplier)

    # 2. Gerar novo sinal se não houver ativo
    if active is None:
        spins = get_recent_spins(rid, SPINS_TO_FETCH)
        info  = try_generate_signal(spins, rid)
        if info:
            active = create_signal(rid, info)

    st["active"] = active

    # 3. Post-loss tracking (10 rodadas)
    lost_tracking = signals_coll.find_one(
        {"roulette_id": rid, "status": "lost", "needs_post_track": True},
        sort=[("resolved_at", DESCENDING)],
    )
    if lost_tracking:
        post = lost_tracking.get("post_attempts", [])
        already_found = any(p.get("hit") for p in post)
        if already_found or len(post) >= MAX_POST_TRACK:
            signals_coll.update_one({"_id": lost_tracking["_id"]}, {"$set": {"needs_post_track": False}})
        else:
            hit_post = latest_val in lost_tracking["bet"]
            signals_coll.update_one(
                {"_id": lost_tracking["_id"]},
                {"$push": {"post_attempts": {
                    "spin":      len(post) + 1,
                    "value":     latest_val,
                    "hit":       hit_post,
                    "timestamp": latest_ts,
                }}},
            )
            if hit_post:
                signals_coll.update_one({"_id": lost_tracking["_id"]}, {"$set": {"needs_post_track": False}})
                log.info("[%s] INVERSAO PAGA pos-derrota: spin=%d valor=%d", rid, len(post) + 1, latest_val)


def main() -> None:
    ensure_indexes()

    targets = resolve_target_roulettes()
    if not targets:
        log.error("Nenhuma roleta para monitorar. T8T9_ROULETTE_IDS=%s", ROULETTE_IDS_RAW)
        return

    log.info(
        "T8T9 worker iniciado. Roletas=%d max_attempts=%d max_post=%d poll=%ss bet=%s",
        len(targets), MAX_ATTEMPTS, MAX_POST_TRACK, POLL_SECONDS, BET_NUMBERS,
    )
    log.info("Roletas monitoradas: %s", ", ".join(targets))

    state: Dict[str, Dict[str, Any]] = {}
    for rid in targets:
        active = signals_coll.find_one(
            {"roulette_id": rid, "status": "monitoring"},
            sort=[("created_at", DESCENDING)],
        )
        last_ts = None
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
