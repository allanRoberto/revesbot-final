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
# Pode ser "all" (default) ou lista separada por virgulas (ex: "pragmatic-auto-roulette,pragmatic-mega-roulette").
# Aceita TERMINAL_7_ROULETTE_ID (singular, legado) ou TERMINAL_7_ROULETTE_IDS (plural).
ROULETTE_IDS_RAW = os.getenv("TERMINAL_7_ROULETTE_IDS") or os.getenv("TERMINAL_7_ROULETTE_ID") or "all"
TRIGGER_VALUE  = int(os.getenv("TERMINAL_7_TRIGGER_VALUE", "34"))
TERMINAL       = int(os.getenv("TERMINAL_7_TERMINAL",      "7"))
NEIGHBOR_SPAN  = int(os.getenv("TERMINAL_7_NEIGHBOR_SPAN", "1"))
MAX_ATTEMPTS   = int(os.getenv("TERMINAL_7_MAX_ATTEMPTS",  "2"))
PRE_WINDOW     = int(os.getenv("TERMINAL_7_PRE_WINDOW",    "5"))
MAX_POST_TRACK = int(os.getenv("TERMINAL_7_MAX_POST",      "20"))
POLL_SECONDS   = float(os.getenv("TERMINAL_7_POLL_SECONDS", "2"))
PRAGMATIC_PREFIX = os.getenv("TERMINAL_7_PRAGMATIC_PREFIX", "pragmatic-")

# Roda europeia
WHEEL = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]
WHEEL_IDX = {n: i for i, n in enumerate(WHEEL)}


def wheel_neighbors(n: int, span: int = 1) -> List[int]:
    if n not in WHEEL_IDX:
        return []
    i = WHEEL_IDX[n]
    out: List[int] = []
    for offset in range(-span, span + 1):
        if offset != 0:
            out.append(WHEEL[(i + offset) % len(WHEEL)])
    return out


def compute_bet() -> List[int]:
    s: set = set()
    for n in range(0, 37):
        if n % 10 == TERMINAL:
            s.add(n)
            for nb in wheel_neighbors(n, span=NEIGHBOR_SPAN):
                s.add(nb)
    # O 0 sempre entra na aposta (cobertura do verde)
    s.add(0)
    return sorted(s)


BET: List[int] = compute_bet()
TERMINAL_NUMBERS: List[int] = sorted([n for n in range(37) if n % 10 == TERMINAL])

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("terminal-7-signal-worker")

_mongo = MongoClient(MONGO_URL)
_db = _mongo["roleta_db"]
history_coll: Collection = _db["history"]
signals_coll: Collection = _db["terminal_7_signal_signals"]


def resolve_target_roulettes() -> List[str]:
    raw = (ROULETTE_IDS_RAW or "all").strip().lower()
    if raw in ("", "all", "*"):
        # Pega todas as roletas pragmatic presentes no historico
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


def get_pre_window(rid: str, latest_ts: Any) -> List[Dict[str, Any]]:
    docs = list(
        history_coll.find(
            {"roulette_id": rid, "timestamp": {"$lt": latest_ts}},
            {"value": 1, "timestamp": 1},
        ).sort("timestamp", DESCENDING).limit(PRE_WINDOW)
    )
    docs.reverse()
    return docs


def create_signal(rid: str, trigger_value: int, trigger_ts: Any) -> Dict[str, Any]:
    pre_docs = get_pre_window(rid, trigger_ts)
    pre_vals = [int(d["value"]) for d in pre_docs]
    pre_ts   = [d["timestamp"] for d in pre_docs]
    inversion_paid_before = any(v in BET for v in pre_vals)
    now = datetime.now(tz=timezone.utc)
    doc = {
        "roulette_id":   rid,
        "config": {
            "trigger_value":     trigger_value,
            "terminal":          TERMINAL,
            "terminal_numbers":  TERMINAL_NUMBERS,
            "neighbor_span":     NEIGHBOR_SPAN,
            "max_attempts":      MAX_ATTEMPTS,
            "pre_window":        PRE_WINDOW,
            "max_post":          MAX_POST_TRACK,
        },
        "X":             trigger_value,
        "X_timestamp":   trigger_ts,
        "bet":           BET,
        "pre_window":    pre_vals,
        "pre_window_ts": pre_ts,
        "inversion_paid_before": inversion_paid_before,
        "status":        "monitoring",
        "attempts":      [],
        "won_at_attempt": None,
        "post_attempts": [],
        "needs_post_track": False,
        "created_at":    now,
        "resolved_at":   None,
    }
    result = signals_coll.insert_one(doc)
    doc["_id"] = result.inserted_id
    log.info("[%s] SIGNAL trigger=%d bet=%s pre=%s inv=%s",
             rid, trigger_value, BET, pre_vals, inversion_paid_before)
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
        hit         = latest_val in BET
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
            log.info("[%s] WON attempt=%d value=%d", rid, attempt_num, latest_val)
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
            log.info("[%s] LOST apos %d tentativas", rid, MAX_ATTEMPTS)
            active = None
        else:
            signals_coll.update_one(
                {"_id": active["_id"]},
                {"$push": {"attempts": entry}},
            )
            active.setdefault("attempts", []).append(entry)
            log.info("[%s] attempt %d/%d: %d (%s)", rid, attempt_num, MAX_ATTEMPTS, latest_val,
                     "HIT" if hit else "miss")

    # 2. Gatilho -> cria sinal novo se nao ha ativo
    if active is None and latest_val == TRIGGER_VALUE:
        active = create_signal(rid, latest_val, latest_ts)

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
                log.info("[%s] POST PAGO no spin extra %d, valor=%d",
                         rid, len(post) + 1, latest_val)


def main() -> None:
    ensure_indexes()

    targets = resolve_target_roulettes()
    if not targets:
        log.error("Nenhuma roleta para monitorar (TERMINAL_7_ROULETTE_IDS=%s). Encerrando.", ROULETTE_IDS_RAW)
        return

    log.info(
        "Worker iniciado. Roletas (%d) trigger=%d terminal=%d span=%d max_attempts=%d bet=%s",
        len(targets), TRIGGER_VALUE, TERMINAL, NEIGHBOR_SPAN, MAX_ATTEMPTS, BET,
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
