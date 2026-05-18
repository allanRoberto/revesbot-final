from __future__ import annotations

import logging
import os
import sys
import time
from collections import Counter
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
ROULETTE_ID    = os.getenv("TRIO_RANKING_ROULETTE_ID",    "pragmatic-auto-roulette")
HISTORY_COUNT  = int(os.getenv("TRIO_RANKING_HISTORY_COUNT", "5"))
TOP_NEXT1      = int(os.getenv("TRIO_RANKING_TOP_NEXT1",   "0"))
TOP_NEXT2      = int(os.getenv("TRIO_RANKING_TOP_NEXT2",   "0"))
TOP_NEXT3      = int(os.getenv("TRIO_RANKING_TOP_NEXT3",  "10"))
MAX_ATTEMPTS   = int(os.getenv("TRIO_RANKING_MAX_ATTEMPTS", "4"))
TOP_N_BET      = int(os.getenv("TRIO_RANKING_TOP_N_BET",   "10"))
MAX_POST_TRACK = int(os.getenv("TRIO_RANKING_MAX_POST",    "20"))
POLL_SECONDS   = float(os.getenv("TRIO_RANKING_POLL_SECONDS", "2"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("trio-ranking-worker")

_mongo = MongoClient(MONGO_URL)
_db = _mongo["roleta_db"]
history_coll:  Collection = _db["history"]
triplets_coll: Collection = _db["history_triplets"]
signals_coll:  Collection = _db["trio_ranking_signals"]


def ensure_indexes() -> None:
    signals_coll.create_index([("roulette_id", ASCENDING), ("status", ASCENDING)])
    signals_coll.create_index([("created_at", DESCENDING)])
    signals_coll.create_index([("status", ASCENDING), ("needs_post_track", ASCENDING)])


def get_last_spins(n: int) -> List[Dict]:
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


def build_ranking(numbers: List[int]) -> List[Dict]:
    scores: Counter = Counter()
    for i in range(len(numbers) - 2):
        a, b, c = numbers[i], numbers[i + 1], numbers[i + 2]
        trio = sorted([a, b, c])
        for field, top_n in [("next1", TOP_NEXT1), ("next2", TOP_NEXT2), ("next3", TOP_NEXT3)]:
            if top_n == 0:
                continue
            results = list(triplets_coll.aggregate([
                {"$match": {"a": trio[0], "b": trio[1], "c": trio[2]}},
                {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": top_n},
            ]))
            if not results:
                results = list(triplets_coll.aggregate([
                    {"$match": {"a": a, "b": b, "c": c}},
                    {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
                    {"$sort": {"count": -1}},
                    {"$limit": top_n},
                ]))
            for r in results:
                if r["_id"] is not None and 0 <= r["_id"] <= 36:
                    scores[r["_id"]] += r["count"]

    return [{"number": n, "score": s} for n, s in scores.most_common(37)]


def create_signal(spins: List[Dict]) -> Optional[Dict]:
    numbers = [s["value"] for s in spins]
    if len(numbers) < 3:
        return None

    ranking = build_ranking(numbers)
    top_n   = [r["number"] for r in ranking[:TOP_N_BET]]

    if not top_n:
        log.warning("Ranking vazio, sinal não gerado")
        return None

    # Números do top_n que já estão no histórico (inversão)
    hist_set       = set(numbers)
    inversion_nums = [n for n in top_n if n in hist_set]

    now = datetime.now(tz=timezone.utc)
    doc = {
        "roulette_id":       ROULETTE_ID,
        "config": {
            "history_count": HISTORY_COUNT,
            "top_next1":     TOP_NEXT1,
            "top_next2":     TOP_NEXT2,
            "top_next3":     TOP_NEXT3,
            "max_attempts":  MAX_ATTEMPTS,
            "top_n_bet":     TOP_N_BET,
        },
        "history_numbers":   numbers,
        "last_spin":         numbers[-1],
        "last_spin_ts":      spins[-1]["timestamp"],
        "ranking":           ranking,
        "top_n":             top_n,
        "inversion":         len(inversion_nums) > 0,
        "inversion_numbers": inversion_nums,
        "status":            "monitoring",
        "attempts":          [],
        "won_at_attempt":    None,
        "post_attempts":     [],
        "needs_post_track":  False,
        "created_at":        now,
        "resolved_at":       None,
    }
    result = signals_coll.insert_one(doc)
    doc["_id"] = result.inserted_id
    log.info("Sinal criado: top%d=%s inversion=%s", TOP_N_BET, top_n, inversion_nums)
    return doc


def main() -> None:
    ensure_indexes()

    # Recupera sinal ativo ao reiniciar
    active: Optional[Dict] = signals_coll.find_one(
        {"roulette_id": ROULETTE_ID, "status": "monitoring"},
        sort=[("created_at", DESCENDING)],
    )
    if active:
        log.info("Sinal ativo encontrado: id=%s tentativas=%d", active["_id"], len(active.get("attempts", [])))

    last_ts: Optional[Any] = None
    if active and active.get("attempts"):
        last_ts = max(a["timestamp"] for a in active["attempts"])
    elif active:
        last_ts = active.get("last_spin_ts")

    log.info("Worker iniciado. Roleta=%s history=%d next3_top=%d max_att=%d",
             ROULETTE_ID, HISTORY_COUNT, TOP_NEXT3, MAX_ATTEMPTS)

    while True:
        try:
            # ── 1. Detecta novo spin ─────────────────────────────────────────
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
            log.debug("Novo spin: %d @ %s", latest_val, latest_ts)

            # ── 2. Processa tentativa do sinal ativo ─────────────────────────
            if active is not None:
                attempt_num = len(active.get("attempts", [])) + 1
                hit         = latest_val in active["top_n"]

                attempt_entry = {
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
                         "$push": {"attempts": attempt_entry}},
                    )
                    log.info("WON na tentativa %d | número %d", attempt_num, latest_val)
                    active = None

                elif attempt_num >= MAX_ATTEMPTS:
                    signals_coll.update_one(
                        {"_id": active["_id"]},
                        {"$set": {
                            "status":            "lost",
                            "resolved_at":       datetime.now(tz=timezone.utc),
                            "needs_post_track":  True,
                        },
                         "$push": {"attempts": attempt_entry}},
                    )
                    log.info("LOST após %d tentativas", MAX_ATTEMPTS)
                    active = None

                else:
                    signals_coll.update_one(
                        {"_id": active["_id"]},
                        {"$push": {"attempts": attempt_entry}},
                    )
                    active.setdefault("attempts", []).append(attempt_entry)
                    log.info("Tentativa %d: %d (%s)", attempt_num, latest_val, "HIT" if hit else "miss")

            # ── 3. Gera novo sinal se não há ativo ──────────────────────────
            if active is None:
                spins = get_last_spins(HISTORY_COUNT)
                active = create_signal(spins)

            # ── 4. Rastreia pós-derrota (sem bloquear novo sinal) ────────────
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
                    hit_post = latest_val in lost_tracking["top_n"]
                    signals_coll.update_one(
                        {"_id": lost_tracking["_id"]},
                        {"$push": {"post_attempts": {
                            "spin": len(post) + 1,
                            "value": latest_val,
                            "hit": hit_post,
                            "timestamp": latest_ts,
                        }}},
                    )
                    if hit_post:
                        signals_coll.update_one(
                            {"_id": lost_tracking["_id"]},
                            {"$set": {"needs_post_track": False}},
                        )
                        log.info("POST-LOSS pago no spin %d extra (número %d)", len(post) + 1, latest_val)

        except Exception as exc:
            log.exception("Erro no loop principal: %s", exc)
            time.sleep(5)
            continue

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
