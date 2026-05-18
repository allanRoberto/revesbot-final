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

from api.services.triplet_strategy_constants import (
    EUROPEAN_WHEEL, WHEEL_INDEX, WHEEL_LEN, evaluate_skip,
)

MONGO_URL = os.getenv(
    "MONGO_URL",
    "mongodb://revesbot:DlBnGmlimRZpIblr@127.0.0.1:27017/roleta_db?authSource=admin",
)
POLL_SECONDS = int(os.getenv("GATILHO_POLL_SECONDS", "2"))
GENERATION_EVERY_N = int(os.getenv("GATILHO_GENERATION_EVERY_N", "21"))
LAST_N = 21
POSITIONS = 3
MIN_OCCURRENCES = int(os.getenv("GATILHO_MIN_OCC", "5"))
MIN_TRIGGER_PCT_DEFAULT = float(os.getenv("GATILHO_MIN_PCT", "4.5"))
EXPIRE_MINUTES = int(os.getenv("GATILHO_EXPIRE_MINUTES", "60"))
CONFIG_CACHE_TTL = 120  # segundos entre re-leituras do banco

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("gatilho-worker")

_mongo = MongoClient(MONGO_URL)
_db = _mongo["roleta_db"]
history_coll: Collection = _db["history"]
triplets_coll: Collection = _db["history_triplets"]
gatilhos_coll: Collection = _db["gatilhos"]
state_coll: Collection = _db["gatilho_worker_state"]
roulettes_config_coll: Collection = _db["roulettes_config"]
app_settings_coll: Collection = _db["app_settings"]

_config: Dict[str, Any] = {"roulettes": [], "min_pct": MIN_TRIGGER_PCT_DEFAULT, "loaded_at": 0.0}


def refresh_config() -> None:
    settings_doc = app_settings_coll.find_one({"_id": "global"}) or {}
    _config["min_pct"] = float(settings_doc.get("gatilho_min_pct", MIN_TRIGGER_PCT_DEFAULT))
    roulettes = list(roulettes_config_coll.find({"monitor_gatilhos": True}, {"_id": 1}))
    _config["roulettes"] = [r["_id"] for r in roulettes]
    _config["loaded_at"] = time.time()
    log.info("Config recarregada: roulettes=%s min_pct=%.1f", _config["roulettes"], _config["min_pct"])


def get_config() -> Dict[str, Any]:
    if time.time() - _config["loaded_at"] > CONFIG_CACHE_TTL:
        refresh_config()
    return _config


def ensure_indexes() -> None:
    gatilhos_coll.create_index(
        [("trigger_number", ASCENDING), ("status", ASCENDING)],
        name="g_trigger_status",
    )
    gatilhos_coll.create_index(
        [("roulette_id", ASCENDING), ("status", ASCENDING), ("created_at", DESCENDING)],
        name="g_roulette_status_created",
    )
    gatilhos_coll.create_index(
        [("roulette_id", ASCENDING), ("triplet_a", ASCENDING), ("triplet_b", ASCENDING),
         ("triplet_c", ASCENDING), ("trigger_number", ASCENDING), ("status", ASCENDING)],
        name="g_dedup",
    )
    gatilhos_coll.create_index([("created_at", DESCENDING)], name="g_created_desc")
    gatilhos_coll.create_index(
        [("status", ASCENDING), ("created_at", ASCENDING)],
        name="g_status_expiry",
    )
    log.info("Indexes prontos.")


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


# ─── Expiry ───────────────────────────────────────────────────────────────────

def expire_old_gatilhos() -> None:
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(minutes=EXPIRE_MINUTES)
    result = gatilhos_coll.update_many(
        {"status": {"$in": ["pending", "pending_confirmation"]}, "created_at": {"$lt": cutoff}},
        {"$set": {"status": "expired", "expired_at": datetime.datetime.utcnow()}},
    )
    if result.modified_count > 0:
        log.info("Expirados %d gatilhos", result.modified_count)


# ─── State ────────────────────────────────────────────────────────────────────

def get_state(roulette_id: str) -> Optional[Dict[str, Any]]:
    return state_coll.find_one({"_id": roulette_id})


def update_state(
    roulette_id: str,
    last_processed_id: Any,
    window_spin_count: int,
    generation: int,
) -> None:
    state_coll.update_one(
        {"_id": roulette_id},
        {"$set": {
            "last_processed_id": last_processed_id,
            "window_spin_count": window_spin_count,
            "generation": generation,
            "updated_at": datetime.datetime.utcnow(),
        }},
        upsert=True,
    )


# ─── Detecção de gatilhos ─────────────────────────────────────────────────────

def gatilho_exists(roulette_id: str, a: int, b: int, c: int) -> bool:
    return gatilhos_coll.find_one({
        "roulette_id": roulette_id,
        "triplet_a": a, "triplet_b": b, "triplet_c": c,
        "status": {"$in": ["pending", "pending_confirmation"]},
    }) is not None


def save_gatilho(
    roulette_id: str, generation: int,
    a: int, b: int, c: int,
    top: Dict[str, Any], total_occ: int,
    ranking: List[Dict[str, Any]],
    bet_numbers: List[int], last_21: List[int],
) -> bool:
    if gatilho_exists(roulette_id, a, b, c):
        return False
    confirmation_numbers = [r["number"] for r in ranking[:3]]
    gatilhos_coll.insert_one({
        "roulette_id": roulette_id,
        "generation": generation,
        "triplet": [a, b, c],
        "triplet_a": a, "triplet_b": b, "triplet_c": c,
        "trigger_number": None,
        "trigger_pct": top["percentage"],
        "total_occurrences": total_occ,
        "ranking_snapshot": ranking[:10],
        "confirmation_numbers": confirmation_numbers,
        "confirmation_spins_seen": 0,
        "bet_numbers": bet_numbers,
        "last_21": last_21,
        "status": "pending_confirmation",
        "created_at": datetime.datetime.utcnow(),
        "expired_at": None,
        "signal_ids": [],
        "signals_won": 0,
        "signals_lost": 0,
        "first_signal_at": None,
        "last_won_at": None,
    })
    return True


def run_generation(roulette_id: str, generation: int) -> int:
    spins = list(history_coll.find(
        {"roulette_id": roulette_id},
        projection={"value": 1},
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
        if top["percentage"] < get_config()["min_pct"]:
            continue
        bet_numbers = assemble_bet_numbers(a, b, c)
        prior = set(values[:i])
        if prior & set(bet_numbers):
            continue
        saved = save_gatilho(roulette_id, generation, a, b, c, top, total_occ, ranking, bet_numbers, values)
        if saved:
            new_count += 1
            log.info("[%s] GEN=%d NOVO GATILHO (%d,%d,%d) n=%d pct=%.2f%% occ=%d",
                     roulette_id, generation, a, b, c, top["number"], top["percentage"], total_occ)
    return new_count


# ─── Loop principal ───────────────────────────────────────────────────────────

def process_roulette(roulette_id: str) -> None:
    state = get_state(roulette_id)

    query: Dict[str, Any] = {"roulette_id": roulette_id}
    if state and state.get("last_processed_id"):
        query["_id"] = {"$gt": state["last_processed_id"]}

    new_docs = list(history_coll.find(
        query,
        projection={"_id": 1},
        sort=[("_id", ASCENDING)],
    ))
    if not new_docs:
        return

    window_spin_count = ((state or {}).get("window_spin_count") or 0) + len(new_docs)
    generation = ((state or {}).get("generation") or 0)
    last_id = new_docs[-1]["_id"]

    if window_spin_count >= GENERATION_EVERY_N:
        generation += 1
        count = run_generation(roulette_id, generation)
        window_spin_count = window_spin_count % GENERATION_EVERY_N
        if count > 0:
            log.info("[%s] Geração %d: %d novo(s) gatilho(s)", roulette_id, generation, count)

    update_state(roulette_id, last_id, window_spin_count, generation)


def main() -> None:
    ensure_indexes()
    refresh_config()
    log.info("Gatilho worker iniciado. gen_a_cada=%d expire=%dmin", GENERATION_EVERY_N, EXPIRE_MINUTES)
    last_expire = 0.0
    while True:
        try:
            now = time.time()
            if now - last_expire > 60:
                expire_old_gatilhos()
                last_expire = now
            cfg = get_config()
            for rid in cfg["roulettes"]:
                try:
                    process_roulette(rid)
                except Exception:
                    log.exception("Erro processando %s", rid)
        except Exception:
            log.exception("Erro no loop principal")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
