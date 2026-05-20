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
ROULETTE_ID    = os.getenv("OCCURRENCE_SIGNAL_ROULETTE_ID",   "pragmatic-auto-roulette")
SPINS_TO_FETCH = int(os.getenv("OCCURRENCE_SIGNAL_SPINS",      "1000"))
ZERO_WINDOW    = int(os.getenv("OCCURRENCE_SIGNAL_ZERO_WINDOW", "7"))
PRE_WINDOW     = int(os.getenv("OCCURRENCE_SIGNAL_PRE_WINDOW",  "5"))
TOP_N          = int(os.getenv("OCCURRENCE_SIGNAL_TOP_N",       "4"))
MAX_ATTEMPTS   = int(os.getenv("OCCURRENCE_SIGNAL_MAX_ATTEMPTS", "4"))
MAX_POST_TRACK = int(os.getenv("OCCURRENCE_SIGNAL_MAX_POST",    "20"))
POLL_SECONDS   = float(os.getenv("OCCURRENCE_SIGNAL_POLL_SECONDS", "2"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("occurrence-signal-worker")

_mongo = MongoClient(MONGO_URL)
_db = _mongo["roleta_db"]
history_coll:  Collection = _db["history"]
triplets_coll: Collection = _db["history_triplets"]
signals_coll:  Collection = _db["occurrence_signal_signals"]


def ensure_indexes() -> None:
    signals_coll.create_index([("roulette_id", ASCENDING), ("status", ASCENDING)])
    signals_coll.create_index([("created_at", DESCENDING)])
    signals_coll.create_index([("status", ASCENDING), ("needs_post_track", ASCENDING)])


def get_recent_spins(n: int) -> List[Dict]:
    docs = list(
        history_coll.find(
            {"roulette_id": ROULETTE_ID},
            {"value": 1, "timestamp": 1},
        )
        .sort("timestamp", DESCENDING)
        .limit(n)
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

    # Janela pre-gatilho: ate `PRE_WINDOW` jogadas imediatamente antes de X (cronologico)
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


def create_signal(info: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(tz=timezone.utc)
    bet = info["bet"]
    pre_window = info.get("pre_window", []) or []
    inversion_paid_before = any(v in bet for v in pre_window)
    doc = {
        "roulette_id":         ROULETTE_ID,
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
    log.info("SIGNAL X=%d trio=%s top4=%s bet=%s match_count=%d",
             info["X"], info["trio"], info["top4"], info["bet"], info["triplet_match_count"])
    return doc


def main() -> None:
    ensure_indexes()

    active: Optional[Dict] = signals_coll.find_one(
        {"roulette_id": ROULETTE_ID, "status": "monitoring"},
        sort=[("created_at", DESCENDING)],
    )
    if active:
        log.info("Sinal ativo retomado: id=%s attempts=%d", active["_id"], len(active.get("attempts", [])))

    last_ts: Optional[Any] = None
    if active and active.get("attempts"):
        last_ts = max(a["timestamp"] for a in active["attempts"])
    elif active:
        last_ts = active.get("X_timestamp")

    log.info(
        "Worker iniciado. Roleta=%s max_attempts=%d top_n=%d zero_window=%d max_post=%d poll=%ss",
        ROULETTE_ID, MAX_ATTEMPTS, TOP_N, ZERO_WINDOW, MAX_POST_TRACK, POLL_SECONDS,
    )

    while True:
        try:
            latest_doc = history_coll.find_one(
                {"roulette_id": ROULETTE_ID},
                {"value": 1, "timestamp": 1},
                sort=[("timestamp", DESCENDING)],
            )
            if not latest_doc:
                time.sleep(POLL_SECONDS)
                continue

            latest_ts  = latest_doc["timestamp"]
            latest_val = int(latest_doc["value"])

            if last_ts is not None and latest_ts <= last_ts:
                time.sleep(POLL_SECONDS)
                continue
            last_ts = latest_ts

            # 1. Processa tentativa do sinal ativo
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
                    log.info("WON attempt=%d value=%d (bet=%s)", attempt_num, latest_val, active["bet"])
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
                    log.info("LOST apos %d tentativas (bet=%s) -> rastreando inversao", MAX_ATTEMPTS, active["bet"])
                    active = None

                else:
                    signals_coll.update_one(
                        {"_id": active["_id"]},
                        {"$push": {"attempts": entry}},
                    )
                    active.setdefault("attempts", []).append(entry)
                    log.info("attempt %d/%d: %d (%s)", attempt_num, MAX_ATTEMPTS, latest_val, "HIT" if hit else "miss")

            # 2. Gera novo sinal se nao ha ativo
            if active is None:
                spins = get_recent_spins(SPINS_TO_FETCH)
                info  = try_generate_signal(spins)
                if info:
                    active = create_signal(info)

            # 3. Rastreia pos-derrota (inversao paga)
            lost_tracking = signals_coll.find_one(
                {"roulette_id": ROULETTE_ID, "status": "lost", "needs_post_track": True},
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
                        log.info("INVERSAO PAGA: spin extra %d, valor=%d (bet=%s)",
                                 len(post) + 1, latest_val, lost_tracking["bet"])

        except Exception as exc:
            log.exception("erro no loop: %s", exc)
            time.sleep(5)
            continue

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
