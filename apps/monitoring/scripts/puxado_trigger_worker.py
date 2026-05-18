from __future__ import annotations

import datetime
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import redis as redis_lib
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection


REPO_ROOT = Path(__file__).resolve().parents[3]
APPS_ROOT = REPO_ROOT / "apps"
if str(APPS_ROOT) not in sys.path:
    sys.path.insert(0, str(APPS_ROOT))

from api.services.triplet_strategy_constants import (  # noqa: E402
    EUROPEAN_WHEEL,
    MONITORED_ROULETTES,
    WHEEL_INDEX,
    WHEEL_LEN,
    evaluate_skip,
)

MONGO_URL = os.getenv(
    "MONGO_URL",
    "mongodb://revesbot:DlBnGmlimRZpIblr@127.0.0.1:27017/roleta_db?authSource=admin",
)
REDIS_URL = os.getenv("REDIS_CONNECT", "redis://localhost:6379")
RESULT_CHANNEL = os.getenv("RESULT_CHANNEL", "new_result")
POLL_SECONDS = int(os.getenv("PUXADO_TRIGGER_POLL_SECONDS", "2"))
LAST_N = 21
POSITIONS = 3
MIN_OCCURRENCES = int(os.getenv("PUXADO_TRIGGER_MIN_OCC", "5"))
MIN_TRIGGER_PCT = float(os.getenv("PUXADO_TRIGGER_MIN_PCT", "5.5"))
MAX_ATTEMPTS = 4
EXPIRE_MINUTES = int(os.getenv("PUXADO_TRIGGER_EXPIRE_MINUTES", "60"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("puxado-trigger-worker")

_mongo = MongoClient(MONGO_URL)
_db = _mongo["roleta_db"]
history_coll: Collection = _db["history"]
triplets_coll: Collection = _db["history_triplets"]
triggers_coll: Collection = _db["puxado_trigger_signals"]
assertiveness_coll: Collection = _db["puxado_trigger_assertiveness"]
state_coll: Collection = _db["puxado_trigger_state"]


def ensure_indexes() -> None:
    triggers_coll.create_index(
        [("roulette_id", ASCENDING), ("status", ASCENDING)],
        name="idx_rid_status",
    )
    triggers_coll.create_index(
        [("roulette_id", ASCENDING), ("created_at", DESCENDING)],
        name="idx_rid_created",
    )
    triggers_coll.create_index(
        [("roulette_id", ASCENDING), ("triplet_a", ASCENDING),
         ("triplet_b", ASCENDING), ("triplet_c", ASCENDING),
         ("trigger_number", ASCENDING), ("status", ASCENDING)],
        name="idx_dedup",
    )
    triggers_coll.create_index(
        [("trigger_number", ASCENDING), ("status", ASCENDING)],
        name="idx_trigger_num_status",
    )
    triggers_coll.create_index(
        [("fired_on_roulette", ASCENDING), ("status", ASCENDING)],
        name="idx_fired_roulette_status",
    )
    log.info("Indexes ready.")


# ─── Wheel helpers ────────────────────────────────────────────────────────────

def wheel_neighbors_2(n: int) -> Tuple[int, int, int, int]:
    idx = WHEEL_INDEX[n]
    return (
        EUROPEAN_WHEEL[(idx - 2) % WHEEL_LEN],
        EUROPEAN_WHEEL[(idx - 1) % WHEEL_LEN],
        EUROPEAN_WHEEL[(idx + 1) % WHEEL_LEN],
        EUROPEAN_WHEEL[(idx + 2) % WHEEL_LEN],
    )


def assemble_bet_numbers(a: int, b: int, c: int) -> List[int]:
    nums: set = {0}
    for n in (a, b, c):
        nums.update((n,) + wheel_neighbors_2(n))
    return sorted(nums)


# ─── Ranking ──────────────────────────────────────────────────────────────────

def compute_ranking(a: int, b: int, c: int) -> Tuple[List[Dict[str, Any]], int]:
    total = triplets_coll.count_documents({"a": a, "b": b, "c": c})
    if total == 0:
        return [], 0
    pipeline = [
        {"$match": {"a": a, "b": b, "c": c}},
        {"$project": {"nexts": ["$next1", "$next2", "$next3"]}},
        {"$unwind": "$nexts"},
        {"$match": {"nexts": {"$ne": None}}},
        {"$group": {"_id": "$nexts", "count": {"$sum": 1}}},
        {"$sort": {"count": -1, "_id": 1}},
    ]
    rows = list(triplets_coll.aggregate(pipeline))
    total_appearances = total * POSITIONS
    return [
        {
            "number": int(r["_id"]),
            "count": int(r["count"]),
            "percentage": round(r["count"] / total_appearances * 100, 2),
        }
        for r in rows
    ], total


# ─── Assertividade ────────────────────────────────────────────────────────────

def update_assertiveness(trigger_number: int) -> None:
    pipeline = [
        {"$match": {"trigger_number": trigger_number, "status": {"$in": ["won", "lost"]}}},
        {"$group": {
            "_id": None,
            "won":  {"$sum": {"$cond": [{"$eq": ["$status", "won"]},  1, 0]}},
            "lost": {"$sum": {"$cond": [{"$eq": ["$status", "lost"]}, 1, 0]}},
            "total": {"$sum": 1},
        }},
    ]
    rows = list(triggers_coll.aggregate(pipeline))
    if not rows:
        return
    row = rows[0]
    won, lost, total = row["won"], row["lost"], row["total"]
    assertiveness_coll.update_one(
        {"_id": trigger_number},
        {"$set": {
            "trigger_number": trigger_number,
            "won": won,
            "lost": lost,
            "total_resolved": total,
            "assertiveness": round(won / total * 100, 2) if total else 0.0,
            "updated_at": datetime.datetime.utcnow(),
        }},
        upsert=True,
    )


# ─── Expiry ───────────────────────────────────────────────────────────────────

def expire_old_triggers() -> None:
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(minutes=EXPIRE_MINUTES)
    result = triggers_coll.update_many(
        {"status": "pending", "created_at": {"$lt": cutoff}},
        {"$set": {"status": "expired", "resolved_at": datetime.datetime.utcnow()}},
    )
    if result.modified_count > 0:
        log.info("Expired %d old triggers", result.modified_count)


# ─── Real-time: disparar e rastrear tentativas ────────────────────────────────

def process_number(number: int, roulette_id: str) -> None:
    now = datetime.datetime.utcnow()

    # Dispara todos os triggers pending cujo trigger_number == number (qualquer mesa)
    for t in list(triggers_coll.find({"trigger_number": number, "status": "pending"})):
        triggers_coll.update_one(
            {"_id": t["_id"]},
            {"$set": {
                "status": "fired",
                "fired_at": now,
                "fired_on_roulette": roulette_id,
            }},
        )
        log.info("[FIRED] #%d em %s | trio=%s (gerado em %s)",
                 number, roulette_id, t.get("triplet"), t.get("roulette_id"))

    # Registra tentativa para todos os triggers disparados nesta mesa
    for t in list(triggers_coll.find({"fired_on_roulette": roulette_id, "status": "fired"})):
        attempts = t.get("attempts") or []
        attempt_num = len(attempts) + 1
        bet_numbers = t.get("bet_numbers") or []
        hit = number in bet_numbers

        update: Dict[str, Any] = {"$push": {"attempts": {
            "attempt": attempt_num,
            "value": number,
            "hit": hit,
            "timestamp": now,
        }}}
        set_fields: Dict[str, Any] = {}

        if hit:
            set_fields.update({"status": "won", "won_at_attempt": attempt_num, "resolved_at": now})
            log.info("[WON]  trigger=%d tentativa=%d valor=%d bet=%s",
                     t["trigger_number"], attempt_num, number, bet_numbers)
        elif attempt_num >= MAX_ATTEMPTS:
            set_fields.update({"status": "lost", "resolved_at": now})
            log.info("[LOST] trigger=%d após %d tentativas | bet=%s",
                     t["trigger_number"], MAX_ATTEMPTS, bet_numbers)

        if set_fields:
            update["$set"] = set_fields
        triggers_coll.update_one({"_id": t["_id"]}, update)

        if "status" in set_fields:
            update_assertiveness(t["trigger_number"])


def run_redis_subscriber() -> None:
    log.info("Redis subscriber iniciando: %s canal=%s", REDIS_URL, RESULT_CHANNEL)
    last_expire = 0.0
    while True:
        try:
            r = redis_lib.from_url(REDIS_URL, decode_responses=True)
            pubsub = r.pubsub()
            pubsub.subscribe(RESULT_CHANNEL)
            log.info("Redis subscriber pronto.")
            for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                now = time.time()
                if now - last_expire > 60:
                    expire_old_triggers()
                    last_expire = now
                try:
                    data = json.loads(message.get("data") or "{}")
                    slug = data.get("slug") or ""
                    result = data.get("result")
                    if slug and result is not None:
                        process_number(int(result), slug)
                except Exception:
                    log.exception("Erro processando mensagem Redis")
        except Exception:
            log.exception("Redis erro — reconectando em 5s")
            time.sleep(5)


# ─── Detector: novos triggers dos últimos 21 spins ────────────────────────────

def trigger_exists(roulette_id: str, a: int, b: int, c: int, trigger_number: int) -> bool:
    return triggers_coll.find_one({
        "roulette_id": roulette_id,
        "triplet_a": a, "triplet_b": b, "triplet_c": c,
        "trigger_number": trigger_number,
        "status": {"$in": ["pending", "fired"]},
    }) is not None


def save_trigger(
    roulette_id: str, a: int, b: int, c: int,
    trigger_number: int, trigger_pct: float, total_occurrences: int,
    ranking_snapshot: List[Dict[str, Any]], bet_numbers: List[int],
    last_21: List[int], source_history_id: Any,
) -> bool:
    if trigger_exists(roulette_id, a, b, c, trigger_number):
        return False
    triggers_coll.insert_one({
        "roulette_id": roulette_id,
        "triplet": [a, b, c],
        "triplet_a": a, "triplet_b": b, "triplet_c": c,
        "trigger_number": trigger_number,
        "trigger_pct": trigger_pct,
        "total_occurrences": total_occurrences,
        "ranking_snapshot": ranking_snapshot[:10],
        "bet_numbers": bet_numbers,
        "last_21": last_21,
        "source_history_id": source_history_id,
        "status": "pending",
        "fired_at": None,
        "fired_on_roulette": None,
        "attempts": [],
        "won_at_attempt": None,
        "resolved_at": None,
        "created_at": datetime.datetime.utcnow(),
    })
    return True


def find_and_save_triggers(roulette_id: str, source_doc: Dict[str, Any]) -> int:
    spins = list(history_coll.find(
        {"roulette_id": roulette_id},
        projection={"value": 1, "timestamp": 1},
        sort=[("_id", DESCENDING)],
        limit=LAST_N,
    ))
    if len(spins) < 3:
        return 0
    spins.reverse()
    values = [int(s["value"]) for s in spins]
    new_count = 0
    for i in range(len(values) - 2):
        a, b, c = values[i], values[i + 1], values[i + 2]
        skip, _ = evaluate_skip(a, b, c)
        if skip:
            continue
        ranking, total_occ = compute_ranking(a, b, c)
        if not ranking or total_occ < MIN_OCCURRENCES:
            continue
        top = ranking[0]
        if top["percentage"] < MIN_TRIGGER_PCT:
            continue
        bet_numbers = assemble_bet_numbers(a, b, c)
        # Cancela se qualquer número da aposta já apareceu antes do trio na janela
        prior = set(values[:i])
        if prior & set(bet_numbers):
            continue
        saved = save_trigger(
            roulette_id=roulette_id, a=a, b=b, c=c,
            trigger_number=top["number"], trigger_pct=top["percentage"],
            total_occurrences=total_occ, ranking_snapshot=ranking,
            bet_numbers=bet_numbers,
            last_21=values.copy(), source_history_id=source_doc["_id"],
        )
        if saved:
            new_count += 1
            log.info("[%s] NEW TRIGGER (%d,%d,%d) gatilho=%d pct=%.2f%% occ=%d",
                     roulette_id, a, b, c, top["number"], top["percentage"], total_occ)
    return new_count


def get_state(roulette_id: str) -> Optional[Dict[str, Any]]:
    return state_coll.find_one({"_id": roulette_id})


def update_state(roulette_id: str, doc: Dict[str, Any]) -> None:
    state_coll.update_one(
        {"_id": roulette_id},
        {"$set": {
            "last_processed_history_id": doc["_id"],
            "last_processed_ts": doc["timestamp"],
            "updated_at": datetime.datetime.utcnow(),
        }},
        upsert=True,
    )


def process_roulette(roulette_id: str) -> int:
    state = get_state(roulette_id)
    if state is None:
        latest = history_coll.find_one(
            {"roulette_id": roulette_id},
            sort=[("_id", DESCENDING)],
            projection={"_id": 1, "value": 1, "timestamp": 1},
        )
        if not latest:
            return 0
        find_and_save_triggers(roulette_id, latest)
        update_state(roulette_id, latest)
        return 1
    last_id = state.get("last_processed_history_id")
    query: Dict[str, Any] = {"roulette_id": roulette_id}
    if last_id:
        query["_id"] = {"$gt": last_id}
    new_docs = list(history_coll.find(query, projection={"value": 1, "timestamp": 1},
                                      sort=[("_id", ASCENDING)]))
    if not new_docs:
        return 0
    last_doc = new_docs[-1]
    find_and_save_triggers(roulette_id, last_doc)
    update_state(roulette_id, last_doc)
    return len(new_docs)


def run_detector_loop() -> None:
    ensure_indexes()
    log.info("Detector iniciado. roulettes=%s min_pct=%.1f expire=%dmin",
             MONITORED_ROULETTES, MIN_TRIGGER_PCT, EXPIRE_MINUTES)
    while True:
        try:
            for rid in MONITORED_ROULETTES:
                try:
                    process_roulette(rid)
                except Exception:
                    log.exception("erro processando %s", rid)
        except Exception:
            log.exception("erro no detector loop")
        time.sleep(POLL_SECONDS)


def main() -> None:
    t = threading.Thread(target=run_redis_subscriber, daemon=True)
    t.start()
    run_detector_loop()


if __name__ == "__main__":
    main()
