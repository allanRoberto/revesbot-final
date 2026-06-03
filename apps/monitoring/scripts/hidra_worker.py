from __future__ import annotations

# ============================================================
#  HIDRA WORKER  —  4 sub-estrategias seguras (Cor, Par/Impar, Colunas, Duzias)
# ------------------------------------------------------------
#  Logica fiel ao backtest HIDRA (strategies.js + backtest.js):
#    - janela deslizante por estrategia
#    - se um lado DOMINA a janela (count >= threshold), aposta CONTRA
#      o lado dominante (espera reversao) e faz gale ate max_attempts
#    - WIN  = +R$2 liquido fixo (independente do gale)
#    - LOSS = perde a soma de TODAS as apostas do ciclo x cobertura
#    - zero (verde) e NEUTRO: nao entra na janela, nao resolve aposta,
#      nao avanca gale
#    - o spin que dispara o sinal NAO entra na janela; a 1a aposta so
#      resolve no proximo spin
#    - quando um ciclo resolve (win/loss) o spin NAO inicia nova busca
#      no mesmo giro (janela ja esta vazia)
#
#  Cada sinal vira 1 documento em `hidra_signals` (status monitoring ->
#  won/lost). O estado da janela por (roleta, estrategia) e persistido em
#  `hidra_state` para retomada exata apos restart.
# ============================================================

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import redis as redis_lib
from bson import ObjectId
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
    os.getenv("HIDRA_ROULETTE_IDS")
    or "pragmatic-auto-roulette,pragmatic-brazilian-roulette"
)
SPINS_TO_FETCH = int(os.getenv("HIDRA_SPINS", "500"))
POLL_SECONDS = float(os.getenv("HIDRA_POLL_SECONDS", "2"))

# Quais sub-estrategias rodar (csv). Default: todas.
_enabled_raw = (os.getenv("HIDRA_STRATEGIES", "") or "").strip()
ENABLED_STRATEGIES = [s.strip() for s in _enabled_raw.split(",") if s.strip()]

# Backfill: varre o historico e popula `hidra_signals` retroativo, depois sai.
# Ativado por `--backfill` (ou HIDRA_BACKFILL=1). `--limit N` (ou HIDRA_BACKFILL_LIMIT)
# limita aos N spins mais recentes (0 = todo o historico).
BACKFILL = (
    os.getenv("HIDRA_BACKFILL", "").strip().lower() in ("1", "true", "yes", "on")
    or "--backfill" in sys.argv
)
BACKFILL_LIMIT = int(os.getenv("HIDRA_BACKFILL_LIMIT", "0"))
for _i, _a in enumerate(sys.argv):
    if _a == "--limit" and _i + 1 < len(sys.argv):
        BACKFILL_LIMIT = int(sys.argv[_i + 1])

# Origem do sinal gravado: "live" (ao vivo) ou "backfill" (retroativo).
SOURCE = "live"

# ---------- classificadores (fieis ao strategies.js) ----------
REDS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
COL1 = {1, 4, 7, 10, 13, 16, 19, 22, 25, 28, 31, 34}
COL2 = {2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32, 35}
COL3 = {3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36}


def classify_cor(n: int) -> Optional[str]:
    if n == 0:
        return None
    return "vermelho" if n in REDS else "preto"


def classify_parimpar(n: int) -> Optional[str]:
    if n == 0:
        return None
    return "par" if n % 2 == 0 else "impar"


def classify_colunas(n: int) -> Optional[str]:
    if n == 0:
        return None
    if n in COL1:
        return "col1"
    if n in COL2:
        return "col2"
    if n in COL3:
        return "col3"
    return None


def classify_duzias(n: int) -> Optional[str]:
    if n == 0:
        return None
    if 1 <= n <= 12:
        return "dz1"
    if 13 <= n <= 24:
        return "dz2"
    if 25 <= n <= 36:
        return "dz3"
    return None


# ---------- definicao das 4 sub-estrategias ----------
STRATEGIES: Dict[str, Dict[str, Any]] = {
    "cor": {
        "name": "Cor",
        "window": 14,
        "threshold": 9,
        "max_attempts": 8,
        "bets": [2, 4, 8, 16, 32, 64, 128, 256],
        "coverage": 1,
        "sides": ["vermelho", "preto"],
        "classify": classify_cor,
    },
    "parimpar": {
        "name": "Par/Impar",
        "window": 11,
        "threshold": 9,
        "max_attempts": 7,
        "bets": [2, 4, 8, 16, 32, 64, 128],
        "coverage": 1,
        "sides": ["par", "impar"],
        "classify": classify_parimpar,
    },
    "colunas": {
        "name": "Colunas",
        "window": 10,
        "threshold": 8,
        "max_attempts": 5,
        "bets": [2, 6, 18, 54, 162],
        "coverage": 2,
        "sides": ["col1", "col2", "col3"],
        "classify": classify_colunas,
    },
    "duzias": {
        "name": "Duzias",
        "window": 10,
        "threshold": 8,
        "max_attempts": 5,
        "bets": [2, 6, 18, 54, 162],
        "coverage": 2,
        "sides": ["dz1", "dz2", "dz3"],
        "classify": classify_duzias,
    },
}

# risco (perda total do ciclo) por estrategia = soma(bets) * cobertura
for _k, _s in STRATEGIES.items():
    _s["risk"] = sum(_s["bets"][: _s["max_attempts"]]) * _s["coverage"]

ACTIVE_STRATEGIES: List[str] = (
    [k for k in ENABLED_STRATEGIES if k in STRATEGIES]
    if ENABLED_STRATEGIES
    else list(STRATEGIES.keys())
)
if not ACTIVE_STRATEGIES:
    raise ValueError(f"HIDRA_STRATEGIES invalido: {_enabled_raw}")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("hidra-worker")

_mongo = MongoClient(MONGO_URL)
_db = _mongo["roleta_db"]
history_coll: Collection = _db["history"]
signals_coll: Collection = _db["hidra_signals"]
state_coll: Collection = _db["hidra_state"]

_redis = redis_lib.from_url(REDIS_URL, decode_responses=True)


def resolve_target_roulettes() -> List[str]:
    raw = (ROULETTE_IDS_RAW or "").strip()
    if not raw or raw.lower() in ("all", "*"):
        slugs = [
            s
            for s in history_coll.distinct("roulette_id")
            if isinstance(s, str) and s.startswith("pragmatic-")
        ]
        return sorted(slugs)
    return [s.strip() for s in raw.split(",") if s.strip()]


def ensure_indexes() -> None:
    signals_coll.create_index([("roulette_id", ASCENDING), ("strategy", ASCENDING), ("status", ASCENDING)])
    signals_coll.create_index([("created_at", DESCENDING)])
    signals_coll.create_index([("strategy", ASCENDING), ("status", ASCENDING)])
    signals_coll.create_index([("status", ASCENDING)])
    state_coll.create_index([("roulette_id", ASCENDING)])


def get_recent_spins(rid: str, n: int) -> List[Dict[str, Any]]:
    docs = list(
        history_coll.find(
            {"roulette_id": rid},
            {"value": 1, "timestamp": 1},
        )
        .sort("timestamp", DESCENDING)
        .limit(n)
    )
    docs.reverse()
    return [{"value": int(d["value"]), "timestamp": d["timestamp"]} for d in docs]


def get_history_spins(rid: str, limit: int) -> List[Dict[str, Any]]:
    """Historico em ordem cronologica (mais antigo -> mais recente).
    limit > 0 = apenas os N spins mais recentes; 0 = todo o historico."""
    if limit and limit > 0:
        docs = list(
            history_coll.find({"roulette_id": rid}, {"value": 1, "timestamp": 1})
            .sort("timestamp", DESCENDING)
            .limit(limit)
        )
        docs.reverse()
    else:
        docs = list(
            history_coll.find({"roulette_id": rid}, {"value": 1, "timestamp": 1})
            .sort("timestamp", ASCENDING)
        )
    return [{"value": int(d["value"]), "timestamp": d["timestamp"]} for d in docs]


# ------------------------------------------------------------
#  Persistencia do estado da janela por (roleta, estrategia)
# ------------------------------------------------------------
def _state_key(rid: str, strat: str) -> str:
    return f"{rid}:{strat}"


def load_state(rid: str, strat: str) -> Optional[Dict[str, Any]]:
    return state_coll.find_one({"_id": _state_key(rid, strat)})


def save_state(rid: str, strat: str, sstate: Dict[str, Any], last_ts: Any = None) -> None:
    active = sstate.get("active")
    state_coll.update_one(
        {"_id": _state_key(rid, strat)},
        {
            "$set": {
                "roulette_id": rid,
                "strategy": strat,
                "window": sstate.get("window", []),
                "active_id": active["_id"] if active else None,
                "last_ts": last_ts,
                "updated_at": datetime.now(tz=timezone.utc),
            }
        },
        upsert=True,
    )


def _ts_to_dt(ts: Any) -> datetime:
    """Converte um timestamp do historico (datetime / epoch / ISO) em datetime UTC."""
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    if isinstance(ts, (int, float)):
        v = float(ts)
        if v > 1e12:  # epoch em milissegundos
            v /= 1000.0
        return datetime.fromtimestamp(v, tz=timezone.utc)
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return datetime.now(tz=timezone.utc)


def _event_time(ts: Any) -> datetime:
    """Hora do evento: agora (ao vivo) ou a hora historica do spin (backfill)."""
    return _ts_to_dt(ts) if SOURCE == "backfill" else datetime.now(tz=timezone.utc)


# ------------------------------------------------------------
#  Criacao / resolucao de sinais
# ------------------------------------------------------------
def create_signal(rid: str, strat: str, cfg: Dict[str, Any], window_snapshot: List[str],
                  dominant: str, dominant_count: int, trigger_ts: Any) -> Dict[str, Any]:
    now = _event_time(trigger_ts)
    bet_sides = [s for s in cfg["sides"] if s != dominant]
    doc = {
        "roulette_id": rid,
        "strategy": strat,
        "strategy_name": cfg["name"],
        "source": SOURCE,
        "status": "monitoring",
        "window_snapshot": window_snapshot,
        "dominant_side": dominant,
        "dominant_count": dominant_count,
        "bet_sides": bet_sides,
        "coverage": cfg["coverage"],
        "threshold": cfg["threshold"],
        "window_size": cfg["window"],
        "max_attempts": cfg["max_attempts"],
        "bets": cfg["bets"],
        "risk": cfg["risk"],
        "X_timestamp": trigger_ts,
        "attempt_index": 0,
        "attempts": [],
        "won_at_attempt": None,
        "pnl": None,
        "created_at": now,
        "resolved_at": None,
        "config": {
            "window": cfg["window"],
            "threshold": cfg["threshold"],
            "max_attempts": cfg["max_attempts"],
            "coverage": cfg["coverage"],
            "bets": cfg["bets"],
        },
    }
    result = signals_coll.insert_one(doc)
    doc["_id"] = result.inserted_id
    log.info(
        "[%s][%s] SINAL dominante=%s (%d/%d) -> aposta %s gale=%d risco=R$%d",
        rid, strat, dominant, dominant_count, cfg["window"],
        bet_sides, cfg["max_attempts"], cfg["risk"],
    )
    if SOURCE == "live":
        try:
            _redis.xadd(
                SIGNAL_STREAM,
                {
                    "signal_id": str(result.inserted_id),
                    "data": json.dumps(
                        {
                            "id": str(result.inserted_id),
                            "roulette_id": rid,
                            "strategy": strat,
                            "dominant_side": dominant,
                            "bet_sides": bet_sides,
                            "type": "new_signal",
                        }
                    ),
                },
                maxlen=200,
            )
        except Exception as exc:
            log.warning("[%s][%s] falha ao publicar sinal no Redis: %s", rid, strat, exc)
    return doc


def step(rid: str, strat: str, cfg: Dict[str, Any], sstate: Dict[str, Any],
         value: int, ts: Any) -> None:
    """Processa UM spin para UMA estrategia (fiel ao loop do backtest.js)."""
    side = cfg["classify"](value)
    active = sstate.get("active")

    # ---- modo 1: em ciclo de aposta (lock) ----
    if active is not None:
        if side is None:
            return  # zero nao resolve / nao avanca gale

        ai = active["attempt_index"]              # 0-based: qual aposta esta viva
        attempt_num = ai + 1
        bet_amount = cfg["bets"][ai] * cfg["coverage"]
        hit = side in active["bet_sides"]
        entry = {
            "attempt": attempt_num,
            "value": value,
            "side": side,
            "hit": hit,
            "bet_amount": bet_amount,
            "timestamp": ts,
        }

        if hit:
            # WIN = +R$2 liquido fixo (modelo HIDRA)
            pnl = 2
            signals_coll.update_one(
                {"_id": active["_id"]},
                {
                    "$set": {
                        "status": "won",
                        "won_at_attempt": attempt_num,
                        "resolved_at": _event_time(ts),
                        "pnl": pnl,
                    },
                    "$push": {"attempts": entry},
                },
            )
            log.info("[%s][%s] WON gale=%d valor=%d (%s) pnl=%+d", rid, strat, attempt_num, value, side, pnl)
            sstate["active"] = None
            return

        # errou nesta tentativa
        if ai + 1 < cfg["max_attempts"]:
            active["attempt_index"] = ai + 1
            active["attempts"].append(entry)
            signals_coll.update_one({"_id": active["_id"]}, {"$push": {"attempts": entry}})
            log.info("[%s][%s] gale %d/%d: %d (%s) miss mult=R$%d",
                     rid, strat, attempt_num, cfg["max_attempts"], value, side, bet_amount)
        else:
            # estourou todos os gales -> LOSS
            pnl = -cfg["risk"]
            signals_coll.update_one(
                {"_id": active["_id"]},
                {
                    "$set": {
                        "status": "lost",
                        "resolved_at": _event_time(ts),
                        "pnl": pnl,
                    },
                    "$push": {"attempts": entry},
                },
            )
            log.info("[%s][%s] LOST apos %d gales pnl=%+d", rid, strat, cfg["max_attempts"], pnl)
            sstate["active"] = None
        return

    # ---- modo 2: procurando sinal (sem lock) ----
    if side is None:
        return  # zero nao entra na janela

    window: List[str] = sstate["window"]
    window.append(side)
    if len(window) > cfg["window"]:
        del window[: len(window) - cfg["window"]]
    if len(window) < cfg["window"]:
        return

    counts: Dict[str, int] = {s: 0 for s in cfg["sides"]}
    for w in window:
        counts[w] += 1
    dominant = None
    for s in cfg["sides"]:
        if counts[s] >= cfg["threshold"]:
            dominant = s
            break
    if dominant is None:
        return

    # SINAL: aposta contra o dominante, zera a janela
    doc = create_signal(rid, strat, cfg, list(window), dominant, counts[dominant], ts)
    sstate["active"] = doc
    sstate["window"] = []


# ------------------------------------------------------------
#  Processamento por roleta
# ------------------------------------------------------------
def process_roulette(rid: str, st: Dict[str, Any]) -> None:
    spins = get_recent_spins(rid, SPINS_TO_FETCH)
    if not spins:
        return

    last_ts = st.get("last_ts")
    if last_ts is None:
        # cold start: nao faz backfill historico, comeca do ultimo spin
        st["last_ts"] = spins[-1]["timestamp"]
        for strat in ACTIVE_STRATEGIES:
            save_state(rid, strat, st["strats"][strat], st["last_ts"])
        return

    new_spins = [s for s in spins if s["timestamp"] > last_ts]
    if not new_spins:
        return

    for sp in new_spins:
        value = sp["value"]
        ts = sp["timestamp"]
        for strat in ACTIVE_STRATEGIES:
            try:
                step(rid, strat, STRATEGIES[strat], st["strats"][strat], value, ts)
            except Exception as exc:
                log.exception("[%s][%s] erro no step: %s", rid, strat, exc)
        st["last_ts"] = ts

    for strat in ACTIVE_STRATEGIES:
        save_state(rid, strat, st["strats"][strat], st["last_ts"])


def init_roulette_state(rid: str) -> Dict[str, Any]:
    """Carrega estado persistido (janela + sinal ativo) por estrategia."""
    strats: Dict[str, Dict[str, Any]] = {}
    last_ts: Any = None
    for strat in ACTIVE_STRATEGIES:
        saved = load_state(rid, strat)
        active = None
        window: List[str] = []
        if saved:
            window = list(saved.get("window", []) or [])
            active_id = saved.get("active_id")
            if active_id:
                active = signals_coll.find_one({"_id": active_id, "status": "monitoring"})
            saved_last = saved.get("last_ts")
            if saved_last is not None and (last_ts is None or saved_last > last_ts):
                last_ts = saved_last
        strats[strat] = {"window": window, "active": active}
        if active and active.get("attempts"):
            cand = max(a["timestamp"] for a in active["attempts"])
            if last_ts is None or cand > last_ts:
                last_ts = cand
        elif active:
            cand = active.get("X_timestamp")
            if cand is not None and (last_ts is None or cand > last_ts):
                last_ts = cand
        if active:
            log.info("[%s][%s] sinal ativo retomado id=%s gale_idx=%d",
                     rid, strat, active["_id"], active.get("attempt_index", 0))
    return {"strats": strats, "last_ts": last_ts}


def run_backfill() -> None:
    """Varre o historico e popula `hidra_signals` retroativo (source=backfill).
    Idempotente: remove o backfill anterior por roleta antes de recriar.
    Ao final grava `hidra_state` para o worker ao vivo continuar de onde parou."""
    global SOURCE
    ensure_indexes()

    targets = resolve_target_roulettes()
    if not targets:
        log.error("Backfill: nenhuma roleta. HIDRA_ROULETTE_IDS=%s", ROULETTE_IDS_RAW)
        return

    SOURCE = "backfill"
    log.info(
        "BACKFILL iniciado. roletas=%d estrategias=%s limit=%s",
        len(targets), ",".join(ACTIVE_STRATEGIES), BACKFILL_LIMIT or "all",
    )

    for rid in targets:
        removed = signals_coll.delete_many({"roulette_id": rid, "source": "backfill"}).deleted_count
        spins = get_history_spins(rid, BACKFILL_LIMIT)
        if not spins:
            log.warning("[%s] backfill: sem historico", rid)
            continue

        strat_states = {s: {"window": [], "active": None} for s in ACTIVE_STRATEGIES}

        # suprime logs por-sinal durante o replay (seriam milhares)
        prev_level = log.level
        log.setLevel(logging.WARNING)
        for sp in spins:
            value = sp["value"]
            ts = sp["timestamp"]
            for strat in ACTIVE_STRATEGIES:
                try:
                    step(rid, strat, STRATEGIES[strat], strat_states[strat], value, ts)
                except Exception as exc:
                    log.exception("[%s][%s] backfill step erro: %s", rid, strat, exc)
        log.setLevel(prev_level)

        last_ts = spins[-1]["timestamp"]
        for strat in ACTIVE_STRATEGIES:
            save_state(rid, strat, strat_states[strat], last_ts)

        for strat in ACTIVE_STRATEGIES:
            q = {"roulette_id": rid, "strategy": strat, "source": "backfill"}
            won = signals_coll.count_documents({**q, "status": "won"})
            lost = signals_coll.count_documents({**q, "status": "lost"})
            mon = signals_coll.count_documents({**q, "status": "monitoring"})
            res = won + lost
            wr = (100.0 * won / res) if res else 0.0
            net = won * 2 - lost * STRATEGIES[strat]["risk"]
            log.info(
                "[%s][%-8s] backfill: %d spins -> %dW/%dL/%dmon WR=%.1f%% NET=R$%d",
                rid, strat, len(spins), won, lost, mon, wr, net,
            )
        log.info("[%s] backfill concluido (removidos %d antigos)", rid, removed)

    SOURCE = "live"
    log.info("BACKFILL finalizado.")


def main() -> None:
    if BACKFILL:
        run_backfill()
        return

    ensure_indexes()

    targets = resolve_target_roulettes()
    if not targets:
        log.error("Nenhuma roleta para monitorar. HIDRA_ROULETTE_IDS=%s", ROULETTE_IDS_RAW)
        return

    log.info(
        "Worker HIDRA iniciado. roletas=%d estrategias=%s poll=%ss",
        len(targets), ",".join(ACTIVE_STRATEGIES), POLL_SECONDS,
    )
    log.info("Roletas monitoradas: %s", ", ".join(targets))

    state: Dict[str, Dict[str, Any]] = {}
    for rid in targets:
        try:
            state[rid] = init_roulette_state(rid)
        except Exception as exc:
            log.exception("[%s] erro ao inicializar estado: %s", rid, exc)
            state[rid] = {"strats": {s: {"window": [], "active": None} for s in ACTIVE_STRATEGIES}, "last_ts": None}

    while True:
        for rid in targets:
            try:
                process_roulette(rid, state[rid])
            except Exception as exc:
                log.exception("[%s] erro: %s", rid, exc)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
