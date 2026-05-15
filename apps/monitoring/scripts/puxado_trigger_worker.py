from __future__ import annotations

import datetime
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
POLL_SECONDS = int(os.getenv("PUXADO_TRIGGER_POLL_SECONDS", "2"))
LAST_N = 21
POSITIONS = 3
MIN_OCCURRENCES = int(os.getenv("PUXADO_TRIGGER_MIN_OCC", "5"))
MIN_TRIGGER_PCT = float(os.getenv("PUXADO_TRIGGER_MIN_PCT", "6.5"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("puxado-trigger-worker")

client = MongoClient(MONGO_URL)
db = client["roleta_db"]
history_coll: Collection = db["history"]
triplets_coll: Collection = db["history_triplets"]
triggers_coll: Collection = db["puxado_trigger_signals"]
state_coll: Collection = db["puxado_trigger_state"]


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
        [
            ("roulette_id", ASCENDING),
            ("triplet_a", ASCENDING),
            ("triplet_b", ASCENDING),
            ("triplet_c", ASCENDING),
            ("trigger_number", ASCENDING),
            ("status", ASCENDING),
        ],
        name="idx_dedup",
    )
    log.info("Indexes ready.")


def wheel_neighbors_1(n: int) -> Tuple[int, int]:
    """Returns (left, right) immediate neighbors of n on the European wheel."""
    idx = WHEEL_INDEX[n]
    left = EUROPEAN_WHEEL[(idx - 1) % WHEEL_LEN]
    right = EUROPEAN_WHEEL[(idx + 1) % WHEEL_LEN]
    return left, right


def assemble_bet_numbers(a: int, b: int, c: int) -> List[int]:
    """
    Bet numbers = each triplet number + its immediate wheel neighbors (±1) + 0.
    Returns a sorted, deduplicated list.
    """
    nums: set[int] = {0}
    for n in (a, b, c):
        left, right = wheel_neighbors_1(n)
        nums.update((n, left, right))
    return sorted(nums)


def compute_ranking(a: int, b: int, c: int) -> Tuple[List[Dict[str, Any]], int]:
    """Returns (ranking, total_occurrences) for triplet (a, b, c)."""
    total = triplets_coll.count_documents({"a": a, "b": b, "c": c})
    if total == 0:
        return [], 0
    next_fields = [f"$next{i}" for i in range(1, POSITIONS + 1)]
    pipeline = [
        {"$match": {"a": a, "b": b, "c": c}},
        {"$project": {"nexts": next_fields}},
        {"$unwind": "$nexts"},
        {"$match": {"nexts": {"$ne": None}}},
        {"$group": {"_id": "$nexts", "count": {"$sum": 1}}},
        {"$sort": {"count": -1, "_id": 1}},
    ]
    rows = list(triplets_coll.aggregate(pipeline))
    total_appearances = total * POSITIONS
    ranking = [
        {
            "number": int(r["_id"]),
            "count": int(r["count"]),
            "percentage": round(r["count"] / total_appearances * 100, 2),
        }
        for r in rows
    ]
    return ranking, total


def trigger_exists(roulette_id: str, a: int, b: int, c: int, trigger_number: int) -> bool:
    return triggers_coll.find_one({
        "roulette_id": roulette_id,
        "triplet_a": a,
        "triplet_b": b,
        "triplet_c": c,
        "trigger_number": trigger_number,
        "status": "pending",
    }) is not None


def save_trigger(
    roulette_id: str,
    a: int,
    b: int,
    c: int,
    trigger_number: int,
    trigger_pct: float,
    total_occurrences: int,
    ranking_snapshot: List[Dict[str, Any]],
    bet_numbers: List[int],
    last_21: List[int],
    source_history_id: Any,
) -> bool:
    if trigger_exists(roulette_id, a, b, c, trigger_number):
        return False
    doc: Dict[str, Any] = {
        "roulette_id": roulette_id,
        "triplet": [a, b, c],
        "triplet_a": a,
        "triplet_b": b,
        "triplet_c": c,
        "trigger_number": trigger_number,
        "trigger_pct": trigger_pct,
        "total_occurrences": total_occurrences,
        "ranking_snapshot": ranking_snapshot[:10],
        "bet_numbers": bet_numbers,
        "last_21": last_21,
        "source_history_id": source_history_id,
        "status": "pending",
        "created_at": datetime.datetime.now(datetime.UTC),
    }
    triggers_coll.insert_one(doc)
    return True


def find_and_save_triggers(roulette_id: str, source_doc: Dict[str, Any]) -> int:
    """Evaluates last 21 spins and saves qualifying triggers. Returns count of new triggers."""
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
    last_21 = values.copy()

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
        saved = save_trigger(
            roulette_id=roulette_id,
            a=a, b=b, c=c,
            trigger_number=top["number"],
            trigger_pct=top["percentage"],
            total_occurrences=total_occ,
            ranking_snapshot=ranking,
            bet_numbers=bet_numbers,
            last_21=last_21,
            source_history_id=source_doc["_id"],
        )
        if saved:
            new_count += 1
            log.info(
                "[%s] NEW TRIGGER triplet=(%d,%d,%d) gatilho=%d pct=%.2f%% occ=%d bet=%s",
                roulette_id, a, b, c, top["number"], top["percentage"], total_occ, bet_numbers,
            )

    return new_count


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
    if last_id is not None:
        query["_id"] = {"$gt": last_id}

    new_docs = list(history_coll.find(
        query,
        projection={"value": 1, "timestamp": 1},
        sort=[("_id", ASCENDING)],
    ))
    if not new_docs:
        return 0

    last_doc = new_docs[-1]
    find_and_save_triggers(roulette_id, last_doc)
    update_state(roulette_id, last_doc)

    return len(new_docs)


def main() -> None:
    ensure_indexes()
    log.info(
        "Starting puxado trigger worker. roulettes=%s last_n=%d positions=%d "
        "min_occ=%d min_pct=%.1f poll=%ss",
        MONITORED_ROULETTES, LAST_N, POSITIONS, MIN_OCCURRENCES, MIN_TRIGGER_PCT, POLL_SECONDS,
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
                log.debug("processou %d novos spins", total)
        except Exception:
            log.exception("erro no loop principal")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
