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
REDIS_URL          = os.getenv("REDIS_CONNECT", "redis://localhost:6379")
SIGNAL_STREAM      = "streams:signals:new"
ROULETTE_IDS_RAW   = (
    os.getenv("QUIN_TERMINAL_ROULETTE_IDS")
    or "pragmatic-auto-roulette,pragmatic-brazilian-roulette"
)
SPINS_TO_FETCH     = int(os.getenv("QUIN_TERMINAL_SPINS",        "500"))
PRE_WINDOW         = int(os.getenv("QUIN_TERMINAL_PRE_WINDOW",   "5"))   # 5 spins exibidos no pré
MAX_ATTEMPTS       = int(os.getenv("QUIN_TERMINAL_MAX_ATTEMPTS", "4"))
MAX_POST_TRACK     = int(os.getenv("QUIN_TERMINAL_MAX_POST",     "20"))
MIN_OCCURRENCES    = int(os.getenv("QUIN_TERMINAL_MIN_OCCUR",    "3"))
MIN_SCORE          = int(os.getenv("QUIN_TERMINAL_MIN_SCORE",    "3"))
NEIGHBOR_SPAN      = int(os.getenv("QUIN_TERMINAL_NEIGHBOR_SPAN","1"))
POSITIONS          = 3   # top-3 ranking — fixo
POLL_SECONDS       = float(os.getenv("QUIN_TERMINAL_POLL_SECONDS", "2"))

_blocked_raw = os.getenv("QUIN_TERMINAL_BLOCKED_TERMINALS", "").strip()
BLOCKED_TERMINALS: set = {int(x) for x in _blocked_raw.split(",") if x.strip()} if _blocked_raw else set()

# Bet multiplier per attempt: 1x, 1x, 2x, 4x
ATTEMPT_MULTIPLIERS = [1, 1, 2, 4]

WHEEL = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]
WHEEL_IDX = {n: i for i, n in enumerate(WHEEL)}


def wheel_neighbors(n: int, span: int = 1) -> List[int]:
    if n not in WHEEL_IDX:
        return []
    i = WHEEL_IDX[n]
    return [WHEEL[(i + offset) % len(WHEEL)] for offset in range(-span, span + 1) if offset != 0]


def digit_sum(n: int) -> int:
    return sum(int(d) for d in str(n))


def get_terminal_numbers(t: int) -> List[int]:
    return [n for n in range(37) if n % 10 == t]


def get_digit_sum_numbers(t: int) -> List[int]:
    """Numbers (0-36) whose digit sum equals t but don't directly end in t."""
    return [n for n in range(37) if digit_sum(n) == t and n % 10 != t]


def build_bet(t: int, span: int = 1) -> List[int]:
    """Build the full bet set for terminal t: direct numbers + digit-sum numbers + their neighbors + 0."""
    terminal_nums = get_terminal_numbers(t)
    sum_nums = get_digit_sum_numbers(t)
    base = set(terminal_nums + sum_nums)
    expanded = set(base)
    for n in base:
        for nb in wheel_neighbors(n, span=span):
            expanded.add(nb)
    expanded.add(0)
    return sorted(expanded)


def compute_connection(n: int, t: int) -> Tuple[str, int]:
    """Return (connection_type, score) for number n and terminal t."""
    if n % 10 == t:
        return ("direct", 3)
    if digit_sum(n) == t:
        return ("sum", 2)
    terminal_set = set(get_terminal_numbers(t))
    for nb in wheel_neighbors(n, span=1):
        if nb in terminal_set:
            return ("neighbor", 1)
    return ("none", 0)


def compute_terminal_confluence(top3: List[int]) -> Dict[str, Any]:
    """Find the best terminal and its confluence strength across the top-3 ranking numbers."""
    best: Dict[str, Any] = {"terminal": -1, "score": 0, "strength": "fraco", "details": []}

    for t in range(10):
        details: List[Dict] = []
        total_score = 0
        direct_count = 0
        sum_count = 0
        neighbor_count = 0

        for n in top3:
            conn_type, score = compute_connection(n, t)
            details.append({"number": n, "connection": conn_type, "score": score})
            total_score += score
            if conn_type == "direct":
                direct_count += 1
            elif conn_type == "sum":
                sum_count += 1
            elif conn_type == "neighbor":
                neighbor_count += 1

        if total_score > best["score"]:
            strong_count = direct_count + sum_count
            if direct_count == 3:
                strength = "muito_forte"
            elif strong_count == 3:
                strength = "forte"
            elif strong_count >= 2 or (strong_count >= 1 and neighbor_count >= 1):
                strength = "mediano"
            else:
                strength = "fraco"

            best = {
                "terminal": t,
                "score": total_score,
                "strength": strength,
                "details": details,
                "direct_count": direct_count,
                "sum_count": sum_count,
                "neighbor_count": neighbor_count,
            }

    return best


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("quintet-terminal-worker")

_mongo = MongoClient(MONGO_URL)
_db = _mongo["roleta_db"]
history_coll:  Collection = _db["history"]
triplets_coll: Collection = _db["history_triplets"]
signals_coll:  Collection = _db["quintet_terminal_signals"]

_redis = redis_lib.from_url(REDIS_URL, decode_responses=True)


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
    signals_coll.create_index([("status", ASCENDING), ("needs_post_track", ASCENDING)])
    signals_coll.create_index([("strength", ASCENDING)])
    signals_coll.create_index([("positions", ASCENDING)])


def get_recent_spins(rid: str, n: int) -> List[Dict[str, Any]]:
    docs = list(
        history_coll.find(
            {"roulette_id": rid},
            {"value": 1, "timestamp": 1},
        ).sort("timestamp", DESCENDING).limit(n)
    )
    docs.reverse()
    return [{"value": int(d["value"]), "timestamp": d["timestamp"]} for d in docs]


def query_quintet_ranking(prev2: int, prev1: int, a: int, b: int, c: int) -> Tuple[int, List[int]]:
    """Query history_triplets for quintet (prev_2, prev_1, a, b, c) and return (total_occurrences, top3_numbers).
    Uses 5-number key, returning the top-3 most frequent next numbers."""
    match = {"prev_2": prev2, "prev_1": prev1, "a": a, "b": b, "c": c}
    total = triplets_coll.count_documents(match)
    if total < MIN_OCCURRENCES:
        return total, []

    rows = list(triplets_coll.aggregate([
        {"$match": match},
        {"$project": {"nums": ["$next1", "$next2", "$next3"]}},
        {"$unwind": "$nums"},
        {"$match": {"nums": {"$ne": None, "$gte": 0, "$lte": 36}}},
        {"$group": {"_id": "$nums", "count": {"$sum": 1}}},
        {"$sort": {"count": -1, "_id": 1}},
    ]))
    top3 = [int(r["_id"]) for r in rows[:3]]
    return total, top3


def try_generate_signal(spins: List[Dict]) -> Optional[Dict[str, Any]]:
    # Need at least 5 spins to have prev2, prev1, a, b, c
    if len(spins) < 5:
        return None

    # Quintet key: last 5 spins
    # prev2 = spins[-5], prev1 = spins[-4], a = spins[-3], b = spins[-2], c = spins[-1]
    prev2 = spins[-5]["value"]
    prev1 = spins[-4]["value"]
    a     = spins[-3]["value"]
    b     = spins[-2]["value"]
    c     = spins[-1]["value"]
    trigger_ts = spins[-1]["timestamp"]

    total_occ, top3 = query_quintet_ranking(prev2, prev1, a, b, c)
    if not top3:
        return None

    confluence = compute_terminal_confluence(top3)
    if confluence["score"] < MIN_SCORE:
        return None

    t = confluence["terminal"]

    if BLOCKED_TERMINALS and t in BLOCKED_TERMINALS:
        return None

    bet = build_bet(t, span=NEIGHBOR_SPAN)

    pre_start = max(0, len(spins) - 1 - PRE_WINDOW)
    pre_window = [spins[i]["value"] for i in range(pre_start, len(spins) - 1)]
    pre_window_ts = [spins[i]["timestamp"] for i in range(pre_start, len(spins) - 1)]

    return {
        "prev2": prev2,
        "prev1": prev1,
        "a": a,
        "b": b,
        "c": c,
        "trigger_ts": trigger_ts,
        "top3": top3,
        "terminal": t,
        "confluence": confluence,
        "bet": bet,
        "total_occ": total_occ,
        "pre_window": pre_window,
        "pre_window_ts": pre_window_ts,
    }


def create_signal(rid: str, info: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(tz=timezone.utc)
    bet = info["bet"]
    pre_window = info.get("pre_window", []) or []
    inversion_paid_before = any(v in bet for v in pre_window)
    confluence = info["confluence"]
    doc = {
        "roulette_id":        rid,
        "status":             "monitoring",
        "quintet":            [info["prev2"], info["prev1"], info["a"], info["b"], info["c"]],
        "quadruplet":         [info["prev1"], info["a"], info["b"], info["c"]],  # compat
        "triplet":            [info["a"], info["b"], info["c"]],                  # compat
        "top3":               info["top3"],
        "terminal":           info["terminal"],
        "strength":           confluence["strength"],
        "confluence_score":   confluence["score"],
        "confluence_details": confluence.get("details", []),
        "direct_count":       confluence.get("direct_count", 0),
        "sum_count":          confluence.get("sum_count", 0),
        "neighbor_count":     confluence.get("neighbor_count", 0),
        "bet":                bet,
        "total_occ":          info["total_occ"],
        "pre_window":         pre_window,
        "pre_window_ts":      info.get("pre_window_ts", []),
        "inversion_paid_before": inversion_paid_before,
        "X_timestamp":        info["trigger_ts"],
        "positions":          POSITIONS,
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
            "min_score":    MIN_SCORE,
            "neighbor_span": NEIGHBOR_SPAN,
            "positions":    POSITIONS,
            "key_length":   5,  # identifica que usa 5-number key
        },
    }
    result = signals_coll.insert_one(doc)
    doc["_id"] = result.inserted_id
    log.info(
        "[%s] SIGNAL quintet=%s top3=%s terminal=%d strength=%s score=%d bet_size=%d inv=%s",
        rid, [info["prev2"], info["prev1"], info["a"], info["b"], info["c"]], info["top3"],
        info["terminal"], confluence["strength"], confluence["score"],
        len(bet), inversion_paid_before,
    )
    try:
        _redis.xadd(SIGNAL_STREAM, {
            "signal_id": str(result.inserted_id),
            "data": json.dumps({
                "id":         str(result.inserted_id),
                "roulette_id": rid,
                "terminal":   info["terminal"],
                "strength":   confluence["strength"],
                "score":      confluence["score"],
                "quintet":    [info["prev2"], info["prev1"], info["a"], info["b"], info["c"]],
                "type":       "new_signal",
                "source":     "quintet_terminal",
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

    # 1. Process active signal attempt
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
                {"$set": {
                    "status":         "won",
                    "won_at_attempt": attempt_num,
                    "resolved_at":    datetime.now(tz=timezone.utc),
                    "pnl":            pnl,
                }, "$push": {"attempts": entry}},
            )
            log.info("[%s] WON attempt=%d value=%d strength=%s pnl=%+d", rid, attempt_num, latest_val, active.get("strength"), pnl)
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
            log.info("[%s] LOST apos %d tentativas strength=%s pnl=%+d", rid, MAX_ATTEMPTS, active.get("strength"), pnl)
            active = None
        else:
            signals_coll.update_one({"_id": active["_id"]}, {"$push": {"attempts": entry}})
            active.setdefault("attempts", []).append(entry)
            log.info("[%s] attempt %d/%d: %d (%s) mult=×%d", rid, attempt_num, MAX_ATTEMPTS, latest_val,
                     "HIT" if hit else "miss", multiplier)

    # 2. Generate new signal if none active
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
        log.error("Nenhuma roleta para monitorar. QUIN_TERMINAL_ROULETTE_IDS=%s", ROULETTE_IDS_RAW)
        return

    log.info(
        "Quintet worker iniciado. Roletas=%d max_attempts=%d min_occur=%d min_score=%d neighbor_span=%d poll=%ss",
        len(targets), MAX_ATTEMPTS, MIN_OCCURRENCES, MIN_SCORE, NEIGHBOR_SPAN, POLL_SECONDS,
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
            log.info("[%s] sinal ativo retomado id=%s strength=%s attempts=%d",
                     rid, active["_id"], active.get("strength"), len(active.get("attempts", [])))

    while True:
        for rid in targets:
            try:
                process_roulette(rid, state[rid])
            except Exception as exc:
                log.exception("[%s] erro: %s", rid, exc)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
