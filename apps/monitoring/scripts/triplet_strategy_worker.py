from __future__ import annotations

import datetime
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection


REPO_ROOT = Path(__file__).resolve().parents[3]
APPS_ROOT = REPO_ROOT / "apps"
if str(APPS_ROOT) not in sys.path:
    sys.path.insert(0, str(APPS_ROOT))

from api.services.triplet_strategy_constants import (  # noqa: E402
    MAX_ATTEMPTS,
    MONITORED_ROULETTES,
    POSITIONS,
    TOP_N,
    assemble_bet_numbers,
    evaluate_skip,
)


MONGO_URL = os.getenv(
    "MONGO_URL",
    "mongodb://revesbot:DlBnGmlimRZpIblr@127.0.0.1:27017/roleta_db?authSource=admin",
)
POLL_SECONDS = int(os.getenv("TRIPLET_STRATEGY_POLL_SECONDS", "2"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("triplet-strategy-worker")

client = MongoClient(MONGO_URL)
db = client["roleta_db"]
history_coll: Collection = db["history"]
triplets_coll: Collection = db["history_triplets"]
bets_coll: Collection = db["triplet_strategy_bets"]
state_coll: Collection = db["triplet_strategy_state"]


def ensure_indexes() -> None:
    bets_coll.create_index([("roulette_id", ASCENDING), ("status", ASCENDING)], name="idx_rid_status")
    bets_coll.create_index([("roulette_id", ASCENDING), ("created_at", DESCENDING)], name="idx_rid_created")
    bets_coll.create_index([("roulette_id", ASCENDING), ("trigger_timestamp", DESCENDING)], name="idx_rid_trigger_ts")
    log.info("Indexes ready.")


def compute_top_numbers(a: int, b: int, c: int) -> List[Dict[str, Any]]:
    next_fields = [f"$next{i}" for i in range(1, POSITIONS + 1)]
    pipeline = [
        {"$match": {"a": a, "b": b, "c": c}},
        {"$project": {"nexts": next_fields}},
        {"$unwind": "$nexts"},
        {"$group": {"_id": "$nexts", "count": {"$sum": 1}}},
        {"$sort": {"count": -1, "_id": 1}},
        {"$limit": TOP_N},
    ]
    rows = list(triplets_coll.aggregate(pipeline))
    total = triplets_coll.count_documents({"a": a, "b": b, "c": c})
    total_appearances = total * POSITIONS if total else 0
    return [
        {
            "number": int(r["_id"]),
            "count": int(r["count"]),
            "percentage": round(r["count"] / total_appearances * 100, 2) if total_appearances else 0.0,
        }
        for r in rows
    ]


def get_open_bet(roulette_id: str) -> Optional[Dict[str, Any]]:
    return bets_coll.find_one({"roulette_id": roulette_id, "status": "pending"})


def apply_attempt(open_bet: Dict[str, Any], history_doc: Dict[str, Any]) -> None:
    attempt_num = len(open_bet.get("attempts", [])) + 1
    value = int(history_doc["value"])
    bet_numbers = open_bet["bet_numbers"]
    hit = value in bet_numbers
    attempt_record = {
        "attempt": attempt_num,
        "history_id": history_doc["_id"],
        "value": value,
        "timestamp": history_doc["timestamp"],
        "hit": hit,
    }
    update: Dict[str, Any] = {"$push": {"attempts": attempt_record}}
    set_fields: Dict[str, Any] = {}
    now = datetime.datetime.now(datetime.UTC)
    if hit:
        set_fields["status"] = "won"
        set_fields["won_at_attempt"] = attempt_num
        set_fields["resolved_at"] = now
    elif attempt_num >= MAX_ATTEMPTS:
        set_fields["status"] = "lost"
        set_fields["resolved_at"] = now
    if set_fields:
        update["$set"] = set_fields
    bets_coll.update_one({"_id": open_bet["_id"]}, update)
    if hit:
        log.info(
            "[%s] WIN attempt=%d value=%d bet=%s",
            open_bet["roulette_id"], attempt_num, value, bet_numbers,
        )
    elif attempt_num >= MAX_ATTEMPTS:
        log.info(
            "[%s] LOSS after %d attempts. trigger=%s bet=%s",
            open_bet["roulette_id"], MAX_ATTEMPTS, open_bet["trigger_triplet"], bet_numbers,
        )


def try_create_bet(roulette_id: str, anchor_doc: Dict[str, Any]) -> None:
    window = list(history_coll.find(
        {"roulette_id": roulette_id, "_id": {"$lte": anchor_doc["_id"]}},
        projection={"value": 1, "timestamp": 1},
        sort=[("_id", DESCENDING)],
        limit=3,
    ))
    if len(window) < 3:
        return
    window.reverse()
    a, b, c = [int(h["value"]) for h in window]
    skip, reason = evaluate_skip(a, b, c)
    if skip:
        log.debug("[%s] skip triplet (%d,%d,%d): %s", roulette_id, a, b, c, reason)
        return
    ranking = compute_top_numbers(a, b, c)
    if not ranking:
        log.info("[%s] sem ranking para trio (%d,%d,%d) — pulando", roulette_id, a, b, c)
        return
    top_numbers = [r["number"] for r in ranking]
    bet_numbers = assemble_bet_numbers(top_numbers)
    doc = {
        "roulette_id": roulette_id,
        "trigger_triplet": [a, b, c],
        "trigger_history_id": anchor_doc["_id"],
        "trigger_timestamp": anchor_doc["timestamp"],
        "bet_numbers": bet_numbers,
        "ranking_snapshot": ranking,
        "attempts": [],
        "status": "pending",
        "won_at_attempt": None,
        "resolved_at": None,
        "created_at": datetime.datetime.now(datetime.UTC),
    }
    bets_coll.insert_one(doc)
    log.info(
        "[%s] NEW BET trigger=(%d,%d,%d) cover=%d nums",
        roulette_id, a, b, c, len(bet_numbers),
    )


def get_state(roulette_id: str) -> Optional[Dict[str, Any]]:
    return state_coll.find_one({"_id": roulette_id})


def update_state(roulette_id: str, history_doc: Dict[str, Any]) -> None:
    state_coll.update_one(
        {"_id": roulette_id},
        {"$set": {
            "last_processed_history_id": history_doc["_id"],
            "last_processed_ts": history_doc["timestamp"],
            "updated_at": datetime.datetime.now(datetime.UTC),
        }},
        upsert=True,
    )


def initialize_roulette(roulette_id: str) -> None:
    latest = history_coll.find_one(
        {"roulette_id": roulette_id},
        sort=[("_id", DESCENDING)],
        projection={"_id": 1, "value": 1, "timestamp": 1},
    )
    if not latest:
        log.info("[%s] sem historico ainda — aguardando", roulette_id)
        return
    update_state(roulette_id, latest)
    try_create_bet(roulette_id, latest)
    log.info("[%s] estado inicializado em history_id=%s", roulette_id, latest["_id"])


def process_roulette(roulette_id: str) -> int:
    state = get_state(roulette_id)
    if state is None:
        initialize_roulette(roulette_id)
        return 0
    last_id = state.get("last_processed_history_id")
    query: Dict[str, Any] = {"roulette_id": roulette_id}
    if last_id is not None:
        query["_id"] = {"$gt": last_id}
    new_docs = list(history_coll.find(
        query,
        projection={"value": 1, "timestamp": 1},
        sort=[("_id", ASCENDING)],
    ))
    if not new_docs:
        return 0
    processed = 0
    for doc in new_docs:
        open_bet = get_open_bet(roulette_id)
        if open_bet is not None:
            apply_attempt(open_bet, doc)
        else:
            try_create_bet(roulette_id, doc)
        update_state(roulette_id, doc)
        processed += 1
    return processed


def main() -> None:
    ensure_indexes()
    log.info(
        "Starting triplet strategy worker. roulettes=%s top_n=%d positions=%d max_attempts=%d poll=%ss",
        MONITORED_ROULETTES, TOP_N, POSITIONS, MAX_ATTEMPTS, POLL_SECONDS,
    )
    while True:
        try:
            total = 0
            for rid in MONITORED_ROULETTES:
                try:
                    total += process_roulette(rid)
                except Exception:
                    log.exception("erro processando %s", rid)
            if total > 0:
                log.info("processou %d novos spins", total)
        except Exception:
            log.exception("erro no loop principal")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
