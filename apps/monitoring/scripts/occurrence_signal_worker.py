from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

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
# Pode ser "all" (default) ou lista separada por virgulas.
# Aceita OCCURRENCE_SIGNAL_ROULETTE_ID (singular, legado) ou OCCURRENCE_SIGNAL_ROULETTE_IDS (plural).
ROULETTE_IDS_RAW = (
    os.getenv("OCCURRENCE_SIGNAL_ROULETTE_IDS")
    or os.getenv("OCCURRENCE_SIGNAL_ROULETTE_ID")
    or "all"
)
SPINS_TO_FETCH = int(os.getenv("OCCURRENCE_SIGNAL_SPINS",      "1000"))
ZERO_WINDOW    = int(os.getenv("OCCURRENCE_SIGNAL_ZERO_WINDOW", "7"))
PRE_WINDOW     = int(os.getenv("OCCURRENCE_SIGNAL_PRE_WINDOW",  "5"))
TOP_N          = int(os.getenv("OCCURRENCE_SIGNAL_TOP_N",       "4"))
MAX_ATTEMPTS   = int(os.getenv("OCCURRENCE_SIGNAL_MAX_ATTEMPTS", "4"))
MAX_POST_TRACK = int(os.getenv("OCCURRENCE_SIGNAL_MAX_POST",    "20"))
POLL_SECONDS   = float(os.getenv("OCCURRENCE_SIGNAL_POLL_SECONDS", "2"))
PRAGMATIC_PREFIX = os.getenv("OCCURRENCE_SIGNAL_PRAGMATIC_PREFIX", "pragmatic-")

WHEEL = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]
WHEEL_IDX = {n: i for i, n in enumerate(WHEEL)}
MIRROR = {1:[10],2:[20],3:[30],10:[1],12:[21],13:[31],20:[2],21:[12],23:[32],30:[3],31:[13],32:[23]}


def link_to_bet(value: Optional[int], bet_set: set) -> Dict[str, Any]:
    """Verifica se `value` tem alguma ligacao (sequencia +-1, vizinho de roda, ou espelho)
    com algum numero da `bet_set`. Matches exatos sao ignorados (esses ja foram filtrados
    pelo anti-eco). Retorna {value, has_link, types, hits}."""
    if value is None:
        return {"value": None, "has_link": False, "types": [], "hits": []}
    v = int(value)
    types: set = set()
    hits: List[List[Any]] = []
    # Sequencia numerica
    for nb in (v - 1, v + 1):
        if 0 <= nb <= 36 and nb in bet_set and nb != v:
            types.add("sequencia"); hits.append([v, nb, "sequencia"])
    # Vizinho na roda
    if v in WHEEL_IDX:
        i = WHEEL_IDX[v]
        for nb in (WHEEL[(i - 1) % 37], WHEEL[(i + 1) % 37]):
            if nb in bet_set and nb != v:
                types.add("vizinho"); hits.append([v, nb, "vizinho"])
    # Espelho
    for nb in MIRROR.get(v, []):
        if nb in bet_set and nb != v:
            types.add("espelho"); hits.append([v, nb, "espelho"])
    return {"value": v, "has_link": len(types) > 0, "types": sorted(types), "hits": hits}


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("occurrence-signal-worker")

_mongo = MongoClient(MONGO_URL)
_db = _mongo["roleta_db"]
history_coll:  Collection = _db["history"]
triplets_coll: Collection = _db["history_triplets"]
signals_coll:  Collection = _db["occurrence_signal_signals"]


def resolve_target_roulettes() -> List[str]:
    raw = (ROULETTE_IDS_RAW or "all").strip().lower()
    if raw in ("", "all", "*"):
        slugs = [
            s for s in history_coll.distinct("roulette_id")
            if isinstance(s, str) and s.startswith(PRAGMATIC_PREFIX)
        ]
        return sorted(slugs)
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


def try_generate_signal(spins: List[Dict]) -> Optional[Dict[str, Any]]:
    """Avalia o padrao no estado atual e retorna info de sinal ativo, ou None."""
    if len(spins) < 10:
        return None

    L = len(spins) - 1
    X = spins[L]["value"]
    zero_start = max(0, L - ZERO_WINDOW + 1)
    zero_window = [spins[i]["value"] for i in range(zero_start, L + 1)]
    if 0 in zero_window:
        return None

    prior = [i for i in range(L) if spins[i]["value"] == X]
    if len(prior) < 3:
        return None

    last3 = prior[-3:]
    occ_oldest_idx, occ_middle_idx, occ_recent_idx = last3
    if occ_oldest_idx == 0 or occ_oldest_idx >= L:
        return None

    prev_n = spins[occ_oldest_idx - 1]["value"]
    next_n = spins[occ_oldest_idx + 1]["value"]

    match = {"a": prev_n, "b": X, "c": next_n}
    rows = list(triplets_coll.aggregate([
        {"$match": match},
        {"$project": {"nums": ["$next1", "$next2", "$next3"]}},
        {"$unwind": "$nums"},
        {"$match": {"nums": {"$ne": None, "$gte": 0, "$lte": 36}}},
        {"$group": {"_id": "$nums", "count": {"$sum": 1}}},
        {"$sort": {"count": -1, "_id": 1}},
    ]))
    if not rows:
        return None

    top4 = [int(r["_id"]) for r in rows[:TOP_N]]
    triplet_match_count = triplets_coll.count_documents(match)

    def window_after(idx: int) -> List[int]:
        out: List[int] = []
        for offset in range(1, 4):
            j = idx + offset
            if j >= L:
                break
            out.append(spins[j]["value"])
        return out

    middle_window = window_after(occ_middle_idx)
    recent_window = window_after(occ_recent_idx)
    check_values = middle_window + recent_window

    if any(v in top4 for v in check_values):
        return None  # top 4 ja apareceu na janela, sinal inativo

    bet = sorted(set(top4 + [0]))

    pre_start = max(0, L - PRE_WINDOW)
    pre_window = [spins[i]["value"] for i in range(pre_start, L)]
    pre_window_ts = [spins[i]["timestamp"] for i in range(pre_start, L)]

    return {
        "X": X,
        "X_timestamp": spins[L]["timestamp"],
        "X_index": L,
        "occ_oldest_idx": occ_oldest_idx,
        "occ_middle_idx": occ_middle_idx,
        "occ_recent_idx": occ_recent_idx,
        "trio": [prev_n, X, next_n],
        "top4": top4,
        "bet": bet,
        "check_middle_window": middle_window,
        "check_recent_window": recent_window,
        "zero_window": zero_window,
        "pre_window": pre_window,
        "pre_window_ts": pre_window_ts,
        "triplet_match_count": triplet_match_count,
        "ranking_top10": [{"number": int(r["_id"]), "count": int(r["count"])} for r in rows[:10]],
    }


def create_signal(rid: str, info: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(tz=timezone.utc)
    bet = info["bet"]
    bet_set = set(bet)
    pre_window = info.get("pre_window", []) or []
    inversion_paid_before = any(v in bet for v in pre_window)
    mid_win = info.get("check_middle_window") or []
    rec_win = info.get("check_recent_window") or []
    middle_next_link = link_to_bet(mid_win[0] if mid_win else None, bet_set)
    recent_next_link = link_to_bet(rec_win[0] if rec_win else None, bet_set)
    doc = {
        "roulette_id":         rid,
        "config": {
            "zero_window":  ZERO_WINDOW,
            "pre_window":   PRE_WINDOW,
            "top_n":        TOP_N,
            "max_attempts": MAX_ATTEMPTS,
            "max_post":     MAX_POST_TRACK,
        },
        "X":                   info["X"],
        "X_timestamp":         info["X_timestamp"],
        "trio":                info["trio"],
        "top4":                info["top4"],
        "bet":                 info["bet"],
        "ranking_top10":       info["ranking_top10"],
        "check_middle_window": info["check_middle_window"],
        "check_recent_window": info["check_recent_window"],
        "zero_window":         info["zero_window"],
        "pre_window":          pre_window,
        "pre_window_ts":       info.get("pre_window_ts", []),
        "inversion_paid_before": inversion_paid_before,
        "middle_next_link":    middle_next_link,
        "recent_next_link":    recent_next_link,
        "triplet_match_count": info["triplet_match_count"],
        "status":              "monitoring",
        "attempts":            [],
        "won_at_attempt":      None,
        "post_attempts":       [],
        "needs_post_track":    False,
        "created_at":          now,
        "resolved_at":         None,
    }
    result = signals_coll.insert_one(doc)
    doc["_id"] = result.inserted_id
    log.info("[%s] SIGNAL X=%d trio=%s top4=%s bet=%s match_count=%d",
             rid, info["X"], info["trio"], info["top4"], info["bet"], info["triplet_match_count"])
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

    # 1. Tentativa do sinal ativo
    if active is not None:
        attempt_num = len(active.get("attempts", [])) + 1
        hit         = latest_val in active["bet"]
        entry = {
            "attempt":   attempt_num,
            "value":     latest_val,
            "hit":       hit,
            "timestamp": latest_ts,
        }
        if hit:
            signals_coll.update_one(
                {"_id": active["_id"]},
                {"$set": {
                    "status":         "won",
                    "won_at_attempt": attempt_num,
                    "resolved_at":    datetime.now(tz=timezone.utc),
                },
                 "$push": {"attempts": entry}},
            )
            log.info("[%s] WON attempt=%d value=%d (bet=%s)", rid, attempt_num, latest_val, active["bet"])
            active = None
        elif attempt_num >= MAX_ATTEMPTS:
            signals_coll.update_one(
                {"_id": active["_id"]},
                {"$set": {
                    "status":           "lost",
                    "resolved_at":      datetime.now(tz=timezone.utc),
                    "needs_post_track": True,
                },
                 "$push": {"attempts": entry}},
            )
            log.info("[%s] LOST apos %d tentativas (bet=%s)", rid, MAX_ATTEMPTS, active["bet"])
            active = None
        else:
            signals_coll.update_one(
                {"_id": active["_id"]},
                {"$push": {"attempts": entry}},
            )
            active.setdefault("attempts", []).append(entry)
            log.info("[%s] attempt %d/%d: %d (%s)", rid, attempt_num, MAX_ATTEMPTS, latest_val,
                     "HIT" if hit else "miss")

    # 2. Gera novo sinal se nao ha ativo
    if active is None:
        spins = get_recent_spins(rid, SPINS_TO_FETCH)
        info = try_generate_signal(spins)
        if info:
            active = create_signal(rid, info)

    st["active"] = active

    # 3. Rastreia pos-derrota da roleta corrente
    lost_tracking = signals_coll.find_one(
        {"roulette_id": rid, "status": "lost", "needs_post_track": True},
        sort=[("resolved_at", DESCENDING)],
    )
    if lost_tracking:
        post = lost_tracking.get("post_attempts", [])
        already_found = any(p.get("hit") for p in post)
        if already_found or len(post) >= MAX_POST_TRACK:
            signals_coll.update_one(
                {"_id": lost_tracking["_id"]},
                {"$set": {"needs_post_track": False}},
            )
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
                signals_coll.update_one(
                    {"_id": lost_tracking["_id"]},
                    {"$set": {"needs_post_track": False}},
                )
                log.info("[%s] INVERSAO PAGA: spin extra %d, valor=%d",
                         rid, len(post) + 1, latest_val)


def main() -> None:
    ensure_indexes()

    targets = resolve_target_roulettes()
    if not targets:
        log.error("Nenhuma roleta para monitorar (OCCURRENCE_SIGNAL_ROULETTE_IDS=%s). Encerrando.", ROULETTE_IDS_RAW)
        return

    log.info(
        "Worker iniciado. Roletas (%d) max_attempts=%d top_n=%d zero_window=%d pre_window=%d max_post=%d poll=%ss",
        len(targets), MAX_ATTEMPTS, TOP_N, ZERO_WINDOW, PRE_WINDOW, MAX_POST_TRACK, POLL_SECONDS,
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
            log.info("[%s] sinal ativo retomado: id=%s attempts=%d",
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
