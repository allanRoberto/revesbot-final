from __future__ import annotations

# ============================================================
#  ENSEMBLE WORKER  —  meta-sinal de consenso
# ------------------------------------------------------------
#  A cada giro (por roleta) olha TODOS os sinais que estao
#  `monitoring` nos demais sistemas, soma um voto PONDERADO por
#  numero e aposta nos TOP-6 do ranking de consenso. Faz gale ate
#  4 tentativas (espelhando os outros workers), para que a
#  assertividade seja diretamente comparavel.
#
#  Peso de cada voto = (1 / tamanho_da_aposta) * WR_historica_do_sistema
#    - especificidade: numero apostado por um sistema que aposta
#      poucos numeros vale mais que num terminal de 17.
#    - assertividade: pondera pela taxa de acerto historica de cada
#      sistema.
#
#  Zero: os sistemas de terminal (T3/T4/T5) sempre incluem o 0 na
#  aposta (artefato estrutural) -> o 0 deles e' descartado.
#
#  Modos:
#    live      -> usa status=monitoring dos sistemas-fonte
#    --backfill-> reconstroi, por giro, quais sinais estavam ativos
#                 (X_timestamp <= T <= resolved_at) e refaz o ensemble
# ============================================================

import json
import logging
import os
import sys
import time
from collections import Counter, defaultdict
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
REDIS_URL = os.getenv("REDIS_CONNECT", "redis://localhost:6379")
SIGNAL_STREAM = "streams:signals:new"

ROULETTE_IDS_RAW = (
    os.getenv("ENSEMBLE_ROULETTE_IDS")
    or "pragmatic-auto-roulette,pragmatic-brazilian-roulette"
)
SPINS_TO_FETCH = int(os.getenv("ENSEMBLE_SPINS", "500"))
TOP_N_BET = int(os.getenv("ENSEMBLE_TOP_N", "6"))
MAX_ATTEMPTS = int(os.getenv("ENSEMBLE_MAX_ATTEMPTS", "4"))
MIN_SOURCES = int(os.getenv("ENSEMBLE_MIN_SOURCES", "3"))
POLL_SECONDS = float(os.getenv("ENSEMBLE_POLL_SECONDS", "2"))
WR_REFRESH_SECONDS = float(os.getenv("ENSEMBLE_WR_REFRESH", "300"))
WR_DEFAULT = float(os.getenv("ENSEMBLE_WR_DEFAULT", "0.9"))

# multiplicador da aposta por tentativa (igual ao terminal worker)
ATTEMPT_MULTIPLIERS = [1, 1, 2, 4]

# Backfill
BACKFILL = (
    os.getenv("ENSEMBLE_BACKFILL", "").strip().lower() in ("1", "true", "yes", "on")
    or "--backfill" in sys.argv
)
BACKFILL_LIMIT = int(os.getenv("ENSEMBLE_BACKFILL_LIMIT", "0"))
for _i, _a in enumerate(sys.argv):
    if _a == "--limit" and _i + 1 < len(sys.argv):
        BACKFILL_LIMIT = int(sys.argv[_i + 1])

SOURCE = "live"

# coleção fonte -> (campo_da_aposta, tag, força_zero?)
SYS: Dict[str, Tuple[str, str, bool]] = {
    "triplet_terminal_signals":        ("bet", "T3", True),
    "quadruplet_terminal_signals":     ("bet", "T4", True),
    "quintet_terminal_signals":        ("bet", "T5", True),
    "quintet_shuffled_signals":        ("bet", "QS", False),
    "t8t9_signals":                    ("bet", "T8", False),
    "numeros_fortes_signals":          ("bet", "NF", False),
    "numeros_fortes_inversao_signals": ("bet", "NFi", False),
    "occurrence_signal_signals":       ("bet", "OC", False),
    "terminal_7_signal_signals":       ("bet", "t7", False),
    "trio_ranking_signals":            ("top_n", "TR", False),
    "puxado_trigger_signals":          ("bet_numbers", "PX", False),
}
HIDRA_COLL = "hidra_signals"
HIDRA_TAG = "HD"

# HIDRA: lados -> conjunto de números
REDS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
_COLS = {
    "col1": {1, 4, 7, 10, 13, 16, 19, 22, 25, 28, 31, 34},
    "col2": {2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32, 35},
    "col3": {3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36},
}


def side_to_nums(s: str) -> set:
    if s == "vermelho":
        return set(REDS)
    if s == "preto":
        return set(range(1, 37)) - REDS
    if s == "par":
        return {n for n in range(1, 37) if n % 2 == 0}
    if s == "impar":
        return {n for n in range(1, 37) if n % 2 == 1}
    if s in _COLS:
        return set(_COLS[s])
    if s == "dz1":
        return set(range(1, 13))
    if s == "dz2":
        return set(range(13, 25))
    if s == "dz3":
        return set(range(25, 37))
    return set()


def clean_bet(raw: Any, force_zero: bool) -> set:
    out = set()
    for x in raw or []:
        if isinstance(x, bool):
            continue
        if isinstance(x, (int, float)) and 0 <= x <= 36:
            out.add(int(x))
    if force_zero:
        out.discard(0)
    return out


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("ensemble-worker")

_mongo = MongoClient(MONGO_URL)
_db = _mongo["roleta_db"]
history_coll: Collection = _db["history"]
signals_coll: Collection = _db["ensemble_signals"]
state_coll: Collection = _db["ensemble_state"]

_redis = redis_lib.from_url(REDIS_URL, decode_responses=True)

# WR (taxa de acerto historica) por coleção-fonte
WR: Dict[str, float] = {}


def refresh_weights() -> None:
    for coll in list(SYS.keys()) + [HIDRA_COLL]:
        try:
            won = _db[coll].count_documents({"status": "won"})
            lost = _db[coll].count_documents({"status": "lost"})
            WR[coll] = (won / (won + lost)) if (won + lost) else WR_DEFAULT
        except Exception:
            WR[coll] = WR_DEFAULT


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
    signals_coll.create_index([("status", ASCENDING)])
    signals_coll.create_index([("n_sources", ASCENDING)])
    state_coll.create_index([("roulette_id", ASCENDING)])


def get_recent_spins(rid: str, n: int) -> List[Dict[str, Any]]:
    docs = list(
        history_coll.find({"roulette_id": rid}, {"value": 1, "timestamp": 1})
        .sort("timestamp", DESCENDING).limit(n)
    )
    docs.reverse()
    return [{"value": int(d["value"]), "timestamp": d["timestamp"]} for d in docs]


def get_history_spins(rid: str, limit: int) -> List[Dict[str, Any]]:
    if limit and limit > 0:
        docs = list(
            history_coll.find({"roulette_id": rid}, {"value": 1, "timestamp": 1})
            .sort("timestamp", DESCENDING).limit(limit)
        )
        docs.reverse()
    else:
        docs = list(
            history_coll.find({"roulette_id": rid}, {"value": 1, "timestamp": 1})
            .sort("timestamp", ASCENDING)
        )
    return [{"value": int(d["value"]), "timestamp": d["timestamp"]} for d in docs]


def _ts_to_dt(ts: Any) -> datetime:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    if isinstance(ts, (int, float)):
        v = float(ts)
        if v > 1e12:
            v /= 1000.0
        return datetime.fromtimestamp(v, tz=timezone.utc)
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return datetime.now(tz=timezone.utc)


def _event_time(ts: Any) -> datetime:
    return _ts_to_dt(ts) if SOURCE == "backfill" else datetime.now(tz=timezone.utc)


# ------------------------------------------------------------
#  Consenso ponderado
# ------------------------------------------------------------
def compute_consensus(active: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[int, int], Dict[int, set]]:
    """active: lista de {tag, system, nums:set, bet_size}. Retorna ranking ordenado."""
    score: Dict[int, float] = defaultdict(float)
    votes: Dict[int, int] = defaultdict(int)
    backers: Dict[int, set] = defaultdict(set)
    for a in active:
        bs = a["bet_size"]
        if bs <= 0:
            continue
        w = (1.0 / bs) * WR.get(a["system"], WR_DEFAULT)
        for n in a["nums"]:
            score[n] += w
            votes[n] += 1
            backers[n].add(a["tag"])
    ranking = [
        {"number": n, "score": round(sc, 4), "votes": votes[n], "backers": sorted(backers[n])}
        for n, sc in sorted(score.items(), key=lambda kv: (-kv[1], -votes[kv[0]], kv[0]))
    ]
    return ranking, votes, backers


# ------------------------------------------------------------
#  Estado persistido (retomada)
# ------------------------------------------------------------
def _state_key(rid: str) -> str:
    return rid


def load_state(rid: str) -> Optional[Dict[str, Any]]:
    return state_coll.find_one({"_id": _state_key(rid)})


def save_state(rid: str, active: Optional[Dict[str, Any]], last_ts: Any) -> None:
    state_coll.update_one(
        {"_id": _state_key(rid)},
        {"$set": {
            "roulette_id": rid,
            "active_id": active["_id"] if active else None,
            "last_ts": last_ts,
            "updated_at": datetime.now(tz=timezone.utc),
        }},
        upsert=True,
    )


# ------------------------------------------------------------
#  Criação / resolução do sinal de ensemble
# ------------------------------------------------------------
def create_signal(rid: str, ranking: List[Dict[str, Any]], active: List[Dict[str, Any]],
                  trigger_ts: Any) -> Dict[str, Any]:
    bet = [r["number"] for r in ranking[:TOP_N_BET]]
    now = _event_time(trigger_ts)
    sources = Counter(a["tag"] for a in active)
    doc = {
        "roulette_id": rid,
        "source": SOURCE,
        "status": "monitoring",
        "bet": bet,
        "bet_size": len(bet),
        "ranking": ranking[:12],
        "n_sources": len(active),
        "sources": dict(sources),
        "X_timestamp": trigger_ts,
        "attempts": [],
        "won_at_attempt": None,
        "pnl": None,
        "created_at": now,
        "resolved_at": None,
        "config": {
            "top_n": TOP_N_BET,
            "max_attempts": MAX_ATTEMPTS,
            "min_sources": MIN_SOURCES,
            "weighting": "specificity*wr",
        },
    }
    result = signals_coll.insert_one(doc)
    doc["_id"] = result.inserted_id
    log.info("[%s] SINAL ensemble bet=%s n_sources=%d sources=%s",
             rid, bet, len(active), dict(sources))
    if SOURCE == "live":
        try:
            _redis.xadd(SIGNAL_STREAM, {
                "signal_id": str(result.inserted_id),
                "data": json.dumps({
                    "id": str(result.inserted_id), "roulette_id": rid,
                    "bet": bet, "type": "new_signal",
                }),
            }, maxlen=200)
        except Exception as exc:
            log.warning("[%s] falha ao publicar no Redis: %s", rid, exc)
    return doc


def ensemble_step(rid: str, state: Dict[str, Any], value: int, ts: Any,
                  active_provider) -> None:
    """Um giro. active_provider() -> lista de fontes ativas (chamado só quando ocioso)."""
    ae = state.get("active")

    # ---- em ciclo (gale) ----
    if ae is not None:
        attempt_num = len(ae["attempts"]) + 1
        mult = ATTEMPT_MULTIPLIERS[attempt_num - 1] if attempt_num <= len(ATTEMPT_MULTIPLIERS) else ATTEMPT_MULTIPLIERS[-1]
        hit = value in ae["bet_set"]
        entry = {"attempt": attempt_num, "value": value, "hit": hit, "multiplier": mult, "timestamp": ts}
        bet_size = ae["bet_size"]
        if hit:
            all_att = ae["attempts"] + [entry]
            total_cost = sum(
                bet_size * (ATTEMPT_MULTIPLIERS[a["attempt"] - 1] if a["attempt"] <= len(ATTEMPT_MULTIPLIERS) else ATTEMPT_MULTIPLIERS[-1])
                for a in all_att
            )
            pnl = 36 * mult - total_cost
            signals_coll.update_one({"_id": ae["_id"]}, {"$set": {
                "status": "won", "won_at_attempt": attempt_num,
                "resolved_at": _event_time(ts), "pnl": pnl,
            }, "$push": {"attempts": entry}})
            log.info("[%s] WON tentativa=%d valor=%d pnl=%+d", rid, attempt_num, value, pnl)
            state["active"] = None
        elif attempt_num >= MAX_ATTEMPTS:
            total_cost = bet_size * sum(ATTEMPT_MULTIPLIERS[:MAX_ATTEMPTS])
            pnl = -total_cost
            signals_coll.update_one({"_id": ae["_id"]}, {"$set": {
                "status": "lost", "resolved_at": _event_time(ts), "pnl": pnl,
            }, "$push": {"attempts": entry}})
            log.info("[%s] LOST apos %d tentativas pnl=%+d", rid, MAX_ATTEMPTS, pnl)
            state["active"] = None
        else:
            ae["attempts"].append(entry)
            signals_coll.update_one({"_id": ae["_id"]}, {"$push": {"attempts": entry}})
        return

    # ---- ocioso: tenta disparar ----
    active = active_provider()
    if len(active) < MIN_SOURCES:
        return
    ranking, _, _ = compute_consensus(active)
    if not ranking:
        return
    doc = create_signal(rid, ranking, active, ts)
    state["active"] = {"_id": doc["_id"], "bet_set": set(doc["bet"]), "bet_size": doc["bet_size"], "attempts": []}


# ------------------------------------------------------------
#  Fontes ativas — modo LIVE (status=monitoring agora)
# ------------------------------------------------------------
def active_source_bets_live(rid: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for coll, (field, tag, fz) in SYS.items():
        for d in _db[coll].find({"status": "monitoring", "roulette_id": rid}, {field: 1}):
            nums = clean_bet(d.get(field), fz)
            if nums:
                out.append({"tag": tag, "system": coll, "nums": nums, "bet_size": len(nums)})
    for d in _db[HIDRA_COLL].find({"status": "monitoring", "roulette_id": rid}, {"bet_sides": 1}):
        nums = set()
        for s in d.get("bet_sides") or []:
            nums |= side_to_nums(s)
        if nums:
            out.append({"tag": HIDRA_TAG, "system": HIDRA_COLL, "nums": nums, "bet_size": len(nums)})
    return out


def process_roulette(rid: str, st: Dict[str, Any]) -> None:
    spins = get_recent_spins(rid, SPINS_TO_FETCH)
    if not spins:
        return
    last_ts = st.get("last_ts")
    if last_ts is None:
        st["last_ts"] = spins[-1]["timestamp"]
        save_state(rid, st.get("active"), st["last_ts"])
        return
    new_spins = [s for s in spins if s["timestamp"] > last_ts]
    if not new_spins:
        return
    for sp in new_spins:
        try:
            ensemble_step(rid, st, sp["value"], sp["timestamp"], lambda: active_source_bets_live(rid))
        except Exception as exc:
            log.exception("[%s] erro no step: %s", rid, exc)
        st["last_ts"] = sp["timestamp"]
    save_state(rid, st.get("active"), st["last_ts"])


def init_roulette_state(rid: str) -> Dict[str, Any]:
    saved = load_state(rid)
    active = None
    last_ts = None
    if saved:
        last_ts = saved.get("last_ts")
        aid = saved.get("active_id")
        if aid:
            doc = signals_coll.find_one({"_id": aid, "status": "monitoring"})
            if doc:
                active = {"_id": doc["_id"], "bet_set": set(doc.get("bet", [])),
                          "bet_size": doc.get("bet_size", len(doc.get("bet", []))),
                          "attempts": list(doc.get("attempts", []))}
    if active:
        log.info("[%s] sinal ativo retomado id=%s tentativas=%d", rid, active["_id"], len(active["attempts"]))
    return {"active": active, "last_ts": last_ts}


# ------------------------------------------------------------
#  Backfill — reconstrói as janelas ativas dos sistemas-fonte
# ------------------------------------------------------------
def _load_source_windows(rid: str, t0: Any, t1: Any) -> List[Tuple[Any, Any, str, str, frozenset, int]]:
    """Retorna (t_start, t_end, tag, system, nums, bet_size) de sinais-fonte que
    se sobrepõem à janela [t0, t1]."""
    out: List[Tuple[Any, Any, str, str, frozenset, int]] = []
    specs = list(SYS.items()) + [(HIDRA_COLL, ("bet_sides", HIDRA_TAG, False))]
    for coll, (field, tag, fz) in specs:
        proj = {field: 1, "X_timestamp": 1, "resolved_at": 1}
        cur = _db[coll].find({"roulette_id": rid, "X_timestamp": {"$lte": t1}}, proj)
        for d in cur:
            ts = d.get("X_timestamp")
            if ts is None:
                continue
            te = d.get("resolved_at") or t1
            if te < t0:
                continue
            if coll == HIDRA_COLL:
                nums = set()
                for s in d.get(field) or []:
                    nums |= side_to_nums(s)
            else:
                nums = clean_bet(d.get(field), fz)
            if not nums:
                continue
            out.append((ts, te, tag, coll, frozenset(nums), len(nums)))
    return out


def run_backfill() -> None:
    global SOURCE
    ensure_indexes()
    refresh_weights()
    targets = resolve_target_roulettes()
    if not targets:
        log.error("Backfill: nenhuma roleta. ENSEMBLE_ROULETTE_IDS=%s", ROULETTE_IDS_RAW)
        return
    SOURCE = "backfill"
    log.info("BACKFILL ensemble iniciado. roletas=%d top_n=%d min_sources=%d limit=%s WR=%s",
             len(targets), TOP_N_BET, MIN_SOURCES, BACKFILL_LIMIT or "all",
             {k.split("_")[0]: round(v, 3) for k, v in WR.items()})

    for rid in targets:
        removed = signals_coll.delete_many({"roulette_id": rid, "source": "backfill"}).deleted_count
        spins = get_history_spins(rid, BACKFILL_LIMIT)
        if not spins:
            log.warning("[%s] backfill: sem historico", rid)
            continue
        t0, t1 = spins[0]["timestamp"], spins[-1]["timestamp"]
        src = _load_source_windows(rid, t0, t1)
        starts = sorted(src, key=lambda x: x[0])
        log.info("[%s] backfill: %d spins, %d janelas-fonte carregadas", rid, len(spins), len(src))

        state: Dict[str, Any] = {"active": None}
        active_set: List[Tuple] = []
        si = 0

        prev_level = log.level
        log.setLevel(logging.WARNING)
        for sp in spins:
            T, val = sp["timestamp"], sp["value"]
            while si < len(starts) and starts[si][0] <= T:
                active_set.append(starts[si])
                si += 1
            if active_set:
                active_set = [a for a in active_set if a[1] >= T]

            def provider(_a=active_set):
                return [{"tag": a[2], "system": a[3], "nums": set(a[4]), "bet_size": a[5]} for a in _a]

            ensemble_step(rid, state, val, T, provider)
        log.setLevel(prev_level)

        save_state(rid, state.get("active"), t1)

        q = {"roulette_id": rid, "source": "backfill"}
        won = signals_coll.count_documents({**q, "status": "won"})
        lost = signals_coll.count_documents({**q, "status": "lost"})
        mon = signals_coll.count_documents({**q, "status": "monitoring"})
        res = won + lost
        wr = (100.0 * won / res) if res else 0.0
        net = sum(d.get("pnl", 0) or 0 for d in signals_coll.find({**q, "status": {"$in": ["won", "lost"]}}, {"pnl": 1}))
        log.info("[%s] backfill: %d sinais -> %dW/%dL/%dmon WR=%.1f%% NET=%+d (removidos %d antigos)",
                 rid, won + lost + mon, won, lost, mon, wr, net, removed)

    SOURCE = "live"
    log.info("BACKFILL finalizado.")


def main() -> None:
    if BACKFILL:
        run_backfill()
        return

    ensure_indexes()
    refresh_weights()
    targets = resolve_target_roulettes()
    if not targets:
        log.error("Nenhuma roleta para monitorar. ENSEMBLE_ROULETTE_IDS=%s", ROULETTE_IDS_RAW)
        return

    log.info("Worker ENSEMBLE iniciado. roletas=%d top_n=%d min_sources=%d gale=%d poll=%ss",
             len(targets), TOP_N_BET, MIN_SOURCES, MAX_ATTEMPTS, POLL_SECONDS)
    log.info("WR por sistema: %s", {SYS.get(k, (None, k, None))[1] if k in SYS else HIDRA_TAG: round(v, 3) for k, v in WR.items()})

    state: Dict[str, Dict[str, Any]] = {}
    for rid in targets:
        try:
            state[rid] = init_roulette_state(rid)
        except Exception as exc:
            log.exception("[%s] erro init: %s", rid, exc)
            state[rid] = {"active": None, "last_ts": None}

    last_wr = time.time()
    while True:
        if time.time() - last_wr > WR_REFRESH_SECONDS:
            refresh_weights()
            last_wr = time.time()
        for rid in targets:
            try:
                process_roulette(rid, state[rid])
            except Exception as exc:
                log.exception("[%s] erro: %s", rid, exc)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
