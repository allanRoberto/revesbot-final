import logging, os, time
from pymongo import MongoClient, ASCENDING, errors

MONGO_URL = os.getenv("MONGO_URL", "mongodb://revesbot:DlBnGmlimRZpIblr@127.0.0.1:27017/roleta_db?authSource=admin")
POLL_SECONDS = int(os.getenv("TRIPLET_POLL_SECONDS", "2"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("triplet-maintainer")

client = MongoClient(MONGO_URL)
db = client["roleta_db"]
history = db["history"]
triplets = db["history_triplets"]


def get_last_base_ts(rid):
    doc = triplets.find_one({"roulette_id": rid}, sort=[("timestamp", -1)])
    return doc["timestamp"] if doc else None


def process_roulette(rid):
    last_ts = get_last_base_ts(rid)
    query = {"roulette_id": rid}
    if last_ts is not None:
        query["timestamp"] = {"$gt": last_ts}
    candidates = list(history.find(
        query,
        {"value": 1, "timestamp": 1, "_id": 1},
        sort=[("timestamp", ASCENDING)],
    ))
    if not candidates:
        return 0
    seed_query = {"roulette_id": rid}
    if last_ts is not None:
        seed_query["timestamp"] = {"$lte": last_ts}
    seed = list(history.find(
        seed_query,
        {"value": 1, "timestamp": 1, "_id": 1},
        sort=[("timestamp", -1)],
        limit=8,
    ))
    seed.reverse()
    window = seed + candidates
    docs_to_insert = []
    insert_start = len(seed)
    for i in range(insert_start, len(window) - 5):
        base = window[i]
        doc = {
            "_id": base["_id"],
            "roulette_id": rid,
            "timestamp": base["timestamp"],
            "a": window[i]["value"],
            "b": window[i+1]["value"],
            "c": window[i+2]["value"],
            "next1": window[i+3]["value"],
            "next2": window[i+4]["value"],
            "next3": window[i+5]["value"],
        }
        if i - 1 >= 0:
            doc["prev_1"] = window[i-1]["value"]
        if i - 2 >= 0:
            doc["prev_2"] = window[i-2]["value"]
        if i - 3 >= 0:
            doc["prev_3"] = window[i-3]["value"]
        docs_to_insert.append(doc)
    if not docs_to_insert:
        return 0
    try:
        result = triplets.insert_many(docs_to_insert, ordered=False)
        return len(result.inserted_ids)
    except errors.BulkWriteError as e:
        return e.details.get("nInserted", 0)


def main():
    log.info("Starting triplet maintainer, poll=%ss", POLL_SECONDS)
    while True:
        try:
            roulettes = history.distinct("roulette_id")
            total_inserted = 0
            for rid in roulettes:
                try:
                    n = process_roulette(rid)
                    total_inserted += n
                except Exception:
                    log.exception("error processing %s", rid)
            if total_inserted > 0:
                log.info("inserted %d new triplets across %d roulettes", total_inserted, len(roulettes))
        except Exception:
            log.exception("loop error")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
