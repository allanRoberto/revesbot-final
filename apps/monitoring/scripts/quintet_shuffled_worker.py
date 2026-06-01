from __future__ import annotations

"""Quintet Shuffled Worker
==========================
Usa os últimos 5 números como CONJUNTO (ordem irrelevante) para buscar
padrões em history_triplets (campos prev_2, prev_1, a, b, c).

Ao contrário dos workers de terminal, NÃO analisa confluência de terminal.
A aposta são os TOP 18 números do ranking de frequência gerado pelo conjunto.

Matching: qualquer documento cujo multiset {prev_2,prev_1,a,b,c} == multiset
dos 5 últimos giros. Implementado como:
  - pré-filtro DB: cada um dos 5 campos em $in da união dos valores
  - pós-filtro Python: sorted(campos_doc) == sorted(valores_usuario)
"""

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
REDIS_URL        = os.getenv("REDIS_CONNECT", "redis://localhost:6379")
SIGNAL_STREAM    = "streams:signals:new"
ROULETTE_IDS_RAW = (
    os.getenv("QUINSHUF_ROULETTE_IDS")
    or "pragmatic-auto-roulette,pragmatic-brazilian-roulette"
)
SPINS_TO_FETCH   = int(os.getenv("QUINSHUF_SPINS",        "500"))
PRE_WINDOW       = int(os.getenv("QUINSHUF_PRE_WINDOW",   "5"))
MAX_ATTEMPTS     = int(os.getenv("QUINSHUF_MAX_ATTEMPTS", "4"))
MAX_POST_TRACK   = int(os.getenv("QUINSHUF_MAX_POST",     "20"))
MIN_OCCURRENCES  = int(os.getenv("QUINSHUF_MIN_OCCUR",    "3"))
TOP_N_BET        = int(os.getenv("QUINSHUF_TOP_N",        "18"))   # quantos números usar na aposta
POLL_SECONDS     = float(os.getenv("QUINSHUF_POLL_SECONDS", "2"))

# Bet multiplier per attempt: 1x, 1x, 2x, 4x
ATTEMPT_MULTIPLIERS = [1, 1, 2, 4]

# Os 5 campos do esquema history_triplets que correspondem à chave quintet
QUINTET_SCHEMA_FIELDS = ["prev_2", "prev_1", "a", "b", "c"]
# Posições à frente para montar o ranking
TARGET_FIELDS = ["next1", "next2", "next3"]


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("quintet-shuffled-worker")

_mongo = MongoClient(MONGO_URL)
_db    = _mongo["roleta_db"]
history_coll:  Collection = _db["history"]
triplets_coll: Collection = _db["history_triplets"]
signals_coll:  Collection = _db["quintet_shuffled_signals"]

_redis = redis_lib.from_url(REDIS_URL, decode_responses=True)


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


def get_recent_spins(rid: str, n: int) -> List[Dict[str, Any]]:
    docs = list(
        history_coll.find(
            {"roulette_id": rid},
            {"value": 1, "timestamp": 1},
        ).sort("timestamp", DESCENDING).limit(n)
    )
    docs.reverse()
    return [{"value": int(d["value"]), "timestamp": d["timestamp"]} for d in docs]


def query_shuffled_ranking(values: List[int]) -> Tuple[int, List[Dict]]:
    """Busca documentos em history_triplets cujo multiset {prev_2,prev_1,a,b,c}
    é igual ao multiset `values` (5 números).

    Retorna (total_ocorrencias, ranking_completo) onde ranking_completo é uma
    lista de {'number': int, 'count': int} ordenada por count desc."""
    union_vals = list(set(values))

    # Pré-filtro: cada um dos 5 campos deve ser um dos valores buscados
    pre_match: Dict[str, Any] = {f: {"$in": union_vals} for f in QUINTET_SCHEMA_FIELDS}

    target_counts: Counter = Counter()
    total_occ = 0
    sorted_values = sorted(values)  # para comparação multiset

    projection = {f: 1 for f in QUINTET_SCHEMA_FIELDS}
    for tf in TARGET_FIELDS:
        projection[tf] = 1
    projection["_id"] = 0

    for doc in triplets_coll.find(pre_match, projection):
        doc_vals = [doc.get(f) for f in QUINTET_SCHEMA_FIELDS]
        if any(v is None for v in doc_vals):
            continue
        # Verificação multiset: conjunto de ocorrências deve ser idêntico
        if sorted(doc_vals) != sorted_values:
            continue
        total_occ += 1
        for tf in TARGET_FIELDS:
            tgt = doc.get(tf)
            if tgt is not None and 0 <= int(tgt) <= 36:
                target_counts[int(tgt)] += 1

    if total_occ < MIN_OCCURRENCES:
        return total_occ, []

    total_appearances = sum(target_counts.values()) or 1
    ranking = [
        {
            "number":     num,
            "count":      cnt,
            "percentage": round(cnt / total_appearances * 100, 2),
        }
        for num, cnt in sorted(target_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return total_occ, ranking


def try_generate_signal(spins: List[Dict]) -> Optional[Dict[str, Any]]:
    """Tenta gerar sinal a partir dos últimos 5 giros."""
    if len(spins) < 5:
        return None

    values = [spins[-5]["value"], spins[-4]["value"], spins[-3]["value"],
              spins[-2]["value"], spins[-1]["value"]]
    trigger_ts = spins[-1]["timestamp"]

    total_occ, ranking = query_shuffled_ranking(values)
    if not ranking:
        return None

    # Top N como aposta
    bet = [r["number"] for r in ranking[:TOP_N_BET]]
    if not bet:
        return None

    pre_start = max(0, len(spins) - 1 - PRE_WINDOW)
    pre_window = [spins[i]["value"] for i in range(pre_start, len(spins) - 1)]
    pre_window_ts = [spins[i]["timestamp"] for i in range(pre_start, len(spins) - 1)]

    return {
        "values":       values,          # os 5 números (sem ordem)
        "trigger_ts":   trigger_ts,
        "ranking":      ranking,
        "bet":          bet,
        "total_occ":    total_occ,
        "pre_window":   pre_window,
        "pre_window_ts": pre_window_ts,
    }


def create_signal(rid: str, info: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(tz=timezone.utc)
    bet = info["bet"]
    pre_window = info.get("pre_window", []) or []
    inversion_paid_before = any(v in bet for v in pre_window)

    doc = {
        "roulette_id":        rid,
        "status":             "monitoring",
        "quintet":            sorted(info["values"]),  # armazena ordenado para identificação
        "quintet_raw":        info["values"],          # ordem de chegada
        "top_bet":            len(bet),
        "bet":                bet,
        "ranking":            info["ranking"],
        "total_occ":          info["total_occ"],
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
            "min_occur":    MIN_OCCURRENCES,
            "top_n_bet":    TOP_N_BET,
            "shuffled":     True,
            "key_length":   5,
        },
    }
    result = signals_coll.insert_one(doc)
    doc["_id"] = result.inserted_id
    log.info(
        "[%s] SIGNAL quintet=%s top_occ=%d bet_size=%d top1=%s inv=%s",
        rid, sorted(info["values"]), info["total_occ"], len(bet),
        info["ranking"][0] if info["ranking"] else None, inversion_paid_before,
    )
    try:
        _redis.xadd(SIGNAL_STREAM, {
            "signal_id": str(result.inserted_id),
            "data": json.dumps({
                "id":          str(result.inserted_id),
                "roulette_id": rid,
                "quintet":     sorted(info["values"]),
                "type":        "new_signal",
                "source":      "quintet_shuffled",
            }),
        }, maxlen=200)
    except Exception as exc:
        log.warning("[%s] falha ao publicar sinal no Redis stream: %s", rid, exc)
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
        multiplier = ATTEMPT_MULTIPLIERS[attempt_num - 1] if attempt_num <= len(ATTEMPT_MULTIPLIERS) else ATTEMPT_MULTIPLIERS[-1]
        hit = latest_val in active["bet"]
        entry = {"attempt": attempt_num, "value": latest_val, "hit": hit,
                 "timestamp": latest_ts, "multiplier": multiplier}
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
                {"$set": {
                    "status":         "won",
                    "won_at_attempt": attempt_num,
                    "resolved_at":    datetime.now(tz=timezone.utc),
                    "pnl":            pnl,
                }, "$push": {"attempts": entry}},
            )
            log.info("[%s] WON attempt=%d value=%d pnl=%+d", rid, attempt_num, latest_val, pnl)
            active = None
        elif attempt_num >= MAX_ATTEMPTS:
            bet_size = len(active.get("bet", []))
            total_cost = bet_size * sum(ATTEMPT_MULTIPLIERS[:MAX_ATTEMPTS])
            pnl = -total_cost
            signals_coll.update_one(
                {"_id": active["_id"]},
                {"$set": {
                    "status":           "lost",
                    "resolved_at":      datetime.now(tz=timezone.utc),
                    "needs_post_track": True,
                    "pnl":              pnl,
                }, "$push": {"attempts": entry}},
            )
            log.info("[%s] LOST apos %d tentativas pnl=%+d", rid, MAX_ATTEMPTS, pnl)
            active = None
        else:
            signals_coll.update_one({"_id": active["_id"]}, {"$push": {"attempts": entry}})
            active.setdefault("attempts", []).append(entry)
            log.info("[%s] attempt %d/%d: %d (%s) mult=×%d", rid, attempt_num, MAX_ATTEMPTS,
                     latest_val, "HIT" if hit else "miss", multiplier)

    # 2. Gerar novo sinal se não houver ativo
    if active is None:
        spins = get_recent_spins(rid, SPINS_TO_FETCH)
        info = try_generate_signal(spins)
        if info:
            active = create_signal(rid, info)

    st["active"] = active

    # 3. Post-loss tracking
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
                log.info("[%s] INVERSAO PAGA: spin extra %d, valor=%d", rid, len(post) + 1, latest_val)


def main() -> None:
    ensure_indexes()

    targets = resolve_target_roulettes()
    if not targets:
        log.error("Nenhuma roleta para monitorar. QUINSHUF_ROULETTE_IDS=%s", ROULETTE_IDS_RAW)
        return

    log.info(
        "Quintet-Shuffled worker iniciado. Roletas=%d max_attempts=%d min_occur=%d top_n=%d poll=%ss",
        len(targets), MAX_ATTEMPTS, MIN_OCCURRENCES, TOP_N_BET, POLL_SECONDS,
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
