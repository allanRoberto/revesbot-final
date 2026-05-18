from __future__ import annotations

import datetime
import json
import logging
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import redis as redis_lib
from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection

REPO_ROOT = Path(__file__).resolve().parents[3]
APPS_ROOT = REPO_ROOT / "apps"
if str(APPS_ROOT) not in sys.path:
    sys.path.insert(0, str(APPS_ROOT))

from api.services.triplet_strategy_constants import EUROPEAN_WHEEL, WHEEL_INDEX, WHEEL_LEN

MONGO_URL = os.getenv(
    "MONGO_URL",
    "mongodb://revesbot:DlBnGmlimRZpIblr@127.0.0.1:27017/roleta_db?authSource=admin",
)
REDIS_URL = os.getenv("REDIS_CONNECT", "redis://localhost:6379")
RESULT_CHANNEL = os.getenv("RESULT_CHANNEL", "new_result")
MAX_ATTEMPTS = int(os.getenv("SINAL_MAX_ATTEMPTS", "4"))
EXPIRE_MINUTES = int(os.getenv("SINAL_EXPIRE_MINUTES", "60"))
MIN_ASSERTIVENESS = float(os.getenv("SINAL_MIN_ASSERTIVENESS", "0.85"))
GATE_MIN_FINALIZED = int(os.getenv("SINAL_GATE_MIN_FINALIZED", "5"))
CONFIRMATION_WINDOW = int(os.getenv("SINAL_CONFIRMATION_WINDOW", "5"))

# Top-4 pares de espelho selecionados por assertividade (~75%)
# 1↔10, 2↔20, 12↔21, 13↔31
_MIRROR_MAP: Dict[int, int] = {
    1: 10, 10: 1,
    2: 20, 20: 2,
    12: 21, 21: 12,
    13: 31, 31: 13,
}
_MIRROR_CENTERS: frozenset = frozenset(_MIRROR_MAP.keys())

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("sinal-worker")

_mongo = MongoClient(MONGO_URL)
_db = _mongo["roleta_db"]
history_coll: Collection = _db["history"]
gatilhos_coll: Collection = _db["gatilhos"]
sinais_coll: Collection = _db["sinais"]
roulettes_config_coll: Collection = _db["roulettes_config"]
app_settings_coll: Collection = _db["app_settings"]
history_triplets_coll: Collection = _db["history_triplets"]

CONFIG_CACHE_TTL = 120
AUTO_EXCLUDE_SWEEP_INTERVAL = 300  # 5 minutes

_config: Dict[str, Any] = {
    "slugs": set(),
    "monitored_sources": set(),
    "auto_exclude_enabled": False,
    "auto_exclude_min_pct": 70.0,
    "auto_exclude_min_sinais": 5,
    "auto_exclude_hot_zone_only": False,
    "loaded_at": 0.0,
}


def refresh_config() -> None:
    all_cfg = list(roulettes_config_coll.find({}, {"_id": 1, "activate_sinais": 1, "monitor_gatilhos": 1}))
    _config["slugs"]             = {d["_id"] for d in all_cfg if d.get("activate_sinais")}
    _config["monitored_sources"] = {d["_id"] for d in all_cfg if d.get("monitor_gatilhos")}
    settings = app_settings_coll.find_one({"_id": "global"}) or {}
    _config["auto_exclude_enabled"]      = bool(settings.get("auto_exclude_enabled", False))
    _config["auto_exclude_min_pct"]      = float(settings.get("auto_exclude_min_pct", 70.0))
    _config["auto_exclude_min_sinais"]   = int(settings.get("auto_exclude_min_sinais", 5))
    _config["auto_exclude_hot_zone_only"] = bool(settings.get("auto_exclude_hot_zone_only", False))
    _config["loaded_at"] = time.time()
    log.info("Config recarregada. roletas_ativas=%d fontes_monitoradas=%d auto_exclude=%s min_pct=%.1f%%",
             len(_config["slugs"]), len(_config["monitored_sources"]),
             _config["auto_exclude_enabled"], _config["auto_exclude_min_pct"])


def get_config() -> Dict[str, Any]:
    if time.time() - _config["loaded_at"] > CONFIG_CACHE_TTL:
        refresh_config()
    return _config


def ensure_indexes() -> None:
    sinais_coll.create_index(
        [("fired_roulette_id", ASCENDING), ("status", ASCENDING)],
        name="s_fired_status",
    )
    sinais_coll.create_index(
        [("gatilho_id", ASCENDING), ("created_at", DESCENDING)],
        name="s_gatilho_created",
    )
    sinais_coll.create_index(
        [("trigger_number", ASCENDING), ("status", ASCENDING), ("created_at", DESCENDING)],
        name="s_trigger_status_created",
    )
    sinais_coll.create_index([("created_at", DESCENDING)], name="s_created_desc")
    sinais_coll.create_index(
        [("status", ASCENDING), ("created_at", ASCENDING)],
        name="s_status_expiry",
    )
    log.info("Indexes prontos.")


# ─── Detecção de sequência na roda ───────────────────────────────────────────

def detect_sequence(history_at_fire: List[int]) -> Tuple[bool, List[Dict[str, Any]]]:
    """Returns (has_sequence, sequence_details).
    sequence_details is a deduplicated list of {"numbers": [...], "direction": "→"|"←"}.
    """
    before = history_at_fire[:-1]  # exclui o trigger (último elemento)
    window = before[-8:]
    if len(window) < 3:
        return False, []
    idxs = [WHEEL_INDEX[n] for n in window]
    found: List[Dict[str, Any]] = []
    seen: set = set()
    for i in range(len(idxs) - 2):
        d1 = (idxs[i + 1] - idxs[i]) % WHEEL_LEN
        d2 = (idxs[i + 2] - idxs[i + 1]) % WHEEL_LEN
        if 2 <= d1 <= 3 and 2 <= d2 <= 3:
            key = (window[i], window[i + 1], window[i + 2], "→")
            if key not in seen:
                seen.add(key)
                found.append({"numbers": [window[i], window[i + 1], window[i + 2]], "direction": "→"})
        rd1 = (idxs[i] - idxs[i + 1]) % WHEEL_LEN
        rd2 = (idxs[i + 1] - idxs[i + 2]) % WHEEL_LEN
        if 2 <= rd1 <= 3 and 2 <= rd2 <= 3:
            key = (window[i], window[i + 1], window[i + 2], "←")
            if key not in seen:
                seen.add(key)
                found.append({"numbers": [window[i], window[i + 1], window[i + 2]], "direction": "←"})
    return len(found) > 0, found


# ─── Captura de histórico ─────────────────────────────────────────────────────

def get_history_at_fire(roulette_id: str, limit: int = 21) -> List[int]:
    spins = list(history_coll.find(
        {"roulette_id": roulette_id},
        projection={"value": 1},
        sort=[("_id", DESCENDING)],
        limit=limit,
    ))
    spins.reverse()
    return [int(s["value"]) for s in spins]


# ─── Confirmação de gatilhos ──────────────────────────────────────────────────

def check_confirmations(number: int, roulette_id: str) -> None:
    now = datetime.datetime.utcnow()
    pending = list(gatilhos_coll.find({
        "roulette_id": roulette_id,
        "status": "pending_confirmation",
    }))
    for g in pending:
        conf_nums = set(g.get("confirmation_numbers") or [])
        if number in conf_nums:
            top_ranking = g.get("ranking_snapshot") or []
            pct = next(
                (r["percentage"] for r in top_ranking if r["number"] == number),
                g.get("trigger_pct"),
            )
            gatilhos_coll.update_one({"_id": g["_id"]}, {"$set": {
                "trigger_number": number,
                "trigger_pct": pct,
                "status": "pending",
                "confirmed_at": now,
            }})
            log.info("[CONFIRM] gatilho=%s triplet=%s confirmed=%d", g["_id"], g.get("triplet"), number)
        else:
            spins_seen = g.get("confirmation_spins_seen", 0) + 1
            if spins_seen >= CONFIRMATION_WINDOW:
                gatilhos_coll.update_one({"_id": g["_id"]}, {"$set": {
                    "status": "confirmation_failed",
                    "confirmation_spins_seen": spins_seen,
                    "expired_at": now,
                }})
                log.info("[CONFIRM-FAIL] gatilho=%s no top-3 in %d spins", g["_id"], CONFIRMATION_WINDOW)
            else:
                gatilhos_coll.update_one({"_id": g["_id"]}, {"$set": {"confirmation_spins_seen": spins_seen}})


# ─── Contexto trio ───────────────────────────────────────────────────────────

def wheel_distance(a: int, b: int) -> int:
    ia, ib = WHEEL_INDEX[a], WHEEL_INDEX[b]
    diff = abs(ia - ib)
    return min(diff, WHEEL_LEN - diff)


def compute_ctx_ranking(history_at_fire: List[int]) -> Tuple[List[int], List[int]]:
    """Returns (top3, top5) from context trio frequency. Empty lists if no data."""
    if len(history_at_fire) < 3:
        return [], []
    a, b, c = history_at_fire[-3], history_at_fire[-2], history_at_fire[-1]
    docs = list(history_triplets_coll.find({"a": a, "b": b, "c": c}, {"next1": 1}))
    if not docs:
        return [], []
    freq: Counter = Counter(d["next1"] for d in docs if d.get("next1") is not None)
    top = [n for n, _ in freq.most_common(5)]
    return top[:3], top[:5]


# ─── Criação de sinais ────────────────────────────────────────────────────────

def create_sinais_for_number(number: int, fired_roulette_id: str) -> List[ObjectId]:
    now = datetime.datetime.utcnow()
    gatilhos = list(gatilhos_coll.find({"trigger_number": number, "status": "pending"}))
    if not gatilhos:
        return []

    history_at_fire = get_history_at_fire(fired_roulette_id)
    has_sequence, sequence_details = detect_sequence(history_at_fire)
    created_ids: List[ObjectId] = []

    # Segunda validação: pré-computa ranking do contexto trio uma vez por evento
    ctx_top3, ctx_top5 = compute_ctx_ranking(history_at_fire)

    for g in gatilhos:
        # Bloqueia gatilhos originados de roletas com monitor_gatilhos=False
        if g.get("roulette_id") not in get_config()["monitored_sources"]:
            log.info("[SRC] gatilho=%s roulette=%s — fonte bloqueada, sinal ignorado",
                     g["_id"], g.get("roulette_id"))
            continue

        # Gate: gatilhos com dados suficientes mas assertividade abaixo do mínimo não ativam
        g_won  = int(g.get("signals_won",  0))
        g_lost = int(g.get("signals_lost", 0))
        g_fin  = g_won + g_lost
        if g_fin >= GATE_MIN_FINALIZED and (g_won / g_fin) < MIN_ASSERTIVENESS:
            log.info("[GATE] gatilho=%s triplet=%s assertividade=%.1f%% < %.0f%% — sinal bloqueado",
                     g["_id"], g.get("triplet"), g_won / g_fin * 100, MIN_ASSERTIVENESS * 100)
            continue

        # Segunda validação: filtra pelos números do triplet compatíveis com o contexto
        triplet = g.get("triplet") or []
        original_bet_numbers = g.get("bet_numbers") or []

        if not ctx_top3:
            # Sem histórico para o contexto → não cria sinal
            log.info("[CTX2] gatilho=%s triplet=%s — sem histórico de contexto, sinal ignorado",
                     g["_id"], triplet)
            continue

        ctx_overlap_top5 = len(set(original_bet_numbers) & set(ctx_top5))

        # F1: aposta original precisa ter ≥ 2 números no top-5 do contexto
        if ctx_overlap_top5 < 2:
            log.info("[F1] gatilho=%s triplet=%s overlap=%d < 2 — sinal ignorado",
                     g["_id"], triplet, ctx_overlap_top5)
            continue

        # F2: trigger não deve ter saído nos últimos 10 giros
        if len(history_at_fire) >= 11 and number in history_at_fire[-11:-1]:
            log.info("[F2] gatilho=%s triplet=%s trigger=%d repetiu nos últimos 10 giros — sinal ignorado",
                     g["_id"], triplet, number)
            continue

        # Quais números do triplet têm distância ≤ 2 na roda de algum dos top-3?
        compatible = [
            t for t in triplet
            if t in WHEEL_INDEX and any(
                wheel_distance(t, r) <= 2 for r in ctx_top3 if r in WHEEL_INDEX
            )
        ]
        ctx_triplet_matches = len(compatible)

        if len(compatible) != 1:
            log.info("[CTX2] gatilho=%s triplet=%s ctx_top3=%s matches=%d/3 — sinal ignorado (esperado 1)",
                     g["_id"], triplet, ctx_top3, len(compatible))
            continue

        # Bet filtrado: números compatíveis do triplet + 2 vizinhos de cada lado na roda
        zone: set = set()
        for t in compatible:
            idx = WHEEL_INDEX[t]
            for delta in range(-2, 3):
                zone.add(EUROPEAN_WHEEL[(idx + delta) % WHEEL_LEN])
        effective_bet_numbers = sorted(zone)

        # [F3] Centro deve ser um dos 4 pares de espelho selecionados (1↔10, 2↔20, 12↔21, 13↔31)
        center_number = compatible[0]
        if center_number not in _MIRROR_CENTERS:
            log.info("[F3] gatilho=%s triplet=%s center=%d — não é par top4, sinal ignorado",
                     g["_id"], triplet, center_number)
            continue

        # Expande aposta: zona ±2 original + espelho do centro + zero
        mirror_number = _MIRROR_MAP[center_number]
        bet_numbers_zone = effective_bet_numbers  # zona ±2 base (5 números)
        effective_bet_numbers = sorted(set(effective_bet_numbers) | {mirror_number, 0})

        # Filtro de inversão: se qualquer bet_number apareceu na janela antes do trigger → ignora
        confirmation_spin = g.get("confirmation_spins_seen", 0) + 1
        if confirmation_spin > 1 and len(history_at_fire) >= confirmation_spin:
            window_before = history_at_fire[-(confirmation_spin):-1]
            if any(n in set(effective_bet_numbers) for n in window_before):
                log.info("[INV] gatilho=%s triplet=%s — inversão detectada, sinal ignorado", g["_id"], triplet)
                continue

        sinal_id = ObjectId()
        minutes_since = None
        if g.get("created_at"):
            minutes_since = round((now - g["created_at"]).total_seconds() / 60.0, 2)

        sinais_coll.insert_one({
            "_id": sinal_id,
            "gatilho_id": g["_id"],
            "trigger_number": number,
            "source_roulette_id": g["roulette_id"],
            "fired_roulette_id": fired_roulette_id,
            "generation": g.get("generation"),
            "triplet": triplet,
            "trigger_pct": g.get("trigger_pct"),
            "ranking_snapshot": g.get("ranking_snapshot", []),
            "bet_numbers": effective_bet_numbers,
            "bet_numbers_zone": bet_numbers_zone,
            "center_number": center_number,
            "mirror_number": mirror_number,
            "original_bet_numbers": original_bet_numbers,
            "history_at_fire": history_at_fire,
            "has_sequence": has_sequence,
            "sequence_details": sequence_details,
            "attempts": [],
            "status": "active",
            "won_at_attempt": None,
            "resolved_at": None,
            "competing_signal_ids": [],
            "minutes_since_gatilho": minutes_since,
            "confirmation_spin": g.get("confirmation_spins_seen", 0) + 1,
            "ctx_overlap_top5": ctx_overlap_top5,
            "ctx_triplet_matches": ctx_triplet_matches,
            "created_at": now,
        })

        # Atualiza o gatilho com referência ao sinal e first_signal_at
        update_g: Dict[str, Any] = {"$push": {"signal_ids": sinal_id}}
        if not g.get("first_signal_at"):
            update_g["$set"] = {"first_signal_at": now}
        gatilhos_coll.update_one({"_id": g["_id"]}, update_g)

        created_ids.append(sinal_id)
        log.info("[SINAL] n=%d fired=%s from=%s (%.1fmin)",
                 number, fired_roulette_id, g["roulette_id"], minutes_since or 0)

    # Linka sinais concorrentes gerados neste mesmo evento
    if len(created_ids) > 1:
        for sid in created_ids:
            others = [oid for oid in created_ids if oid != sid]
            sinais_coll.update_one({"_id": sid}, {"$set": {"competing_signal_ids": others}})
        log.info("[CONCORRENTES] %d sinais para n=%d em %s", len(created_ids), number, fired_roulette_id)

    return created_ids


# ─── Rastreamento de tentativas ───────────────────────────────────────────────

def track_attempts(number: int, fired_roulette_id: str) -> None:
    now = datetime.datetime.utcnow()
    sinais = list(sinais_coll.find({"fired_roulette_id": fired_roulette_id, "status": "active"}))

    for sinal in sinais:
        attempts = sinal.get("attempts") or []
        attempt_num = len(attempts) + 1
        bet_numbers = sinal.get("bet_numbers") or []
        hit = number in bet_numbers

        update: Dict[str, Any] = {"$push": {"attempts": {
            "attempt": attempt_num,
            "value": number,
            "hit": hit,
            "timestamp": now,
        }}}
        set_fields: Dict[str, Any] = {}

        resolved = False
        if hit:
            set_fields = {"status": "won", "won_at_attempt": attempt_num, "resolved_at": now}
            log.info("[WON] sinal=%s tentativa=%d valor=%d", sinal["_id"], attempt_num, number)
            gatilhos_coll.update_one(
                {"_id": sinal["gatilho_id"]},
                {"$inc": {"signals_won": 1}, "$set": {"last_won_at": now}},
            )
            resolved = True
        elif attempt_num >= MAX_ATTEMPTS:
            set_fields = {"status": "lost", "resolved_at": now}
            log.info("[LOST] sinal=%s após %d tentativas", sinal["_id"], MAX_ATTEMPTS)
            gatilhos_coll.update_one(
                {"_id": sinal["gatilho_id"]},
                {"$inc": {"signals_lost": 1}},
            )
            resolved = True

        if set_fields:
            update["$set"] = set_fields
        sinais_coll.update_one({"_id": sinal["_id"]}, update)

        if resolved:
            maybe_auto_exclude(sinal["gatilho_id"])


# ─── Expiração ────────────────────────────────────────────────────────────────

def expire_old_sinais() -> None:
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(minutes=EXPIRE_MINUTES)
    result = sinais_coll.update_many(
        {"status": "active", "created_at": {"$lt": cutoff}},
        {"$set": {"status": "expired", "resolved_at": datetime.datetime.utcnow()}},
    )
    if result.modified_count > 0:
        log.info("Expirados %d sinais", result.modified_count)


# ─── Processamento de evento ──────────────────────────────────────────────────

def _is_hot_zone(minutes: Any) -> bool:
    if minutes is None:
        return False
    m = float(minutes)
    return m < 5 or (30 <= m < 45)


def _get_hot_zone_counts(gatilho_id: ObjectId) -> tuple:
    """Return (won, lost) counting only hot-zone sinais for this gatilho."""
    docs = list(sinais_coll.find(
        {"gatilho_id": gatilho_id, "status": {"$in": ["won", "lost"]}},
        {"status": 1, "minutes_since_gatilho": 1},
    ))
    hot = [d for d in docs if _is_hot_zone(d.get("minutes_since_gatilho"))]
    won  = sum(1 for d in hot if d["status"] == "won")
    lost = sum(1 for d in hot if d["status"] == "lost")
    return won, lost


def _resolve_counts(g: Dict[str, Any], hot_zone_only: bool) -> tuple:
    """Return (won, lost) based on mode."""
    if hot_zone_only:
        return _get_hot_zone_counts(g["_id"])
    return int(g.get("signals_won", 0)), int(g.get("signals_lost", 0))


def maybe_auto_exclude(gatilho_id: ObjectId) -> None:
    cfg = get_config()
    if not cfg["auto_exclude_enabled"]:
        return
    g = gatilhos_coll.find_one({"_id": gatilho_id}, {"signals_won": 1, "signals_lost": 1, "triplet": 1})
    if not g:
        return
    hot_only = cfg["auto_exclude_hot_zone_only"]
    won, lost = _resolve_counts(g, hot_only)
    fin = won + lost
    if fin < cfg["auto_exclude_min_sinais"]:
        return
    pct = won / fin * 100
    if pct < cfg["auto_exclude_min_pct"]:
        sinais_coll.delete_many({"gatilho_id": gatilho_id})
        gatilhos_coll.delete_one({"_id": gatilho_id})
        mode = "hot-zone" if hot_only else "all"
        log.info("[AUTO-EXCLUDE] gatilho=%s triplet=%s %.1f%% < %.1f%% (%s, %d sinais) — excluído",
                 gatilho_id, g.get("triplet"), pct, cfg["auto_exclude_min_pct"], mode, fin)


def auto_exclude_sweep() -> None:
    cfg = get_config()
    if not cfg["auto_exclude_enabled"]:
        return
    min_pct    = cfg["auto_exclude_min_pct"]
    min_sinais = cfg["auto_exclude_min_sinais"]
    hot_only   = cfg["auto_exclude_hot_zone_only"]
    candidates = list(gatilhos_coll.find(
        {"status": "pending"},
        {"signals_won": 1, "signals_lost": 1, "triplet": 1},
    ))
    excluded = 0
    for g in candidates:
        won, lost = _resolve_counts(g, hot_only)
        fin = won + lost
        if fin < min_sinais:
            continue
        pct = won / fin * 100
        if pct < min_pct:
            sinais_coll.delete_many({"gatilho_id": g["_id"]})
            gatilhos_coll.delete_one({"_id": g["_id"]})
            mode = "hot-zone" if hot_only else "all"
            log.info("[AUTO-EXCLUDE-SWEEP] gatilho=%s triplet=%s %.1f%% < %.1f%% (%s) — excluído",
                     g["_id"], g.get("triplet"), pct, min_pct, mode)
            excluded += 1
    if excluded:
        log.info("[AUTO-EXCLUDE-SWEEP] %d gatilhos excluídos neste ciclo", excluded)


def process_result(number: int, fired_roulette_id: str) -> None:
    check_confirmations(number, fired_roulette_id)
    track_attempts(number, fired_roulette_id)
    if fired_roulette_id not in get_config()["slugs"]:
        return
    create_sinais_for_number(number, fired_roulette_id)


# ─── Loop Redis ───────────────────────────────────────────────────────────────

def run() -> None:
    ensure_indexes()
    log.info("Sinal worker iniciado. canal=%s max_tentativas=%d expire=%dmin",
             RESULT_CHANNEL, MAX_ATTEMPTS, EXPIRE_MINUTES)
    last_expire = 0.0
    last_sweep = 0.0
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
                    expire_old_sinais()
                    last_expire = now
                if now - last_sweep > AUTO_EXCLUDE_SWEEP_INTERVAL:
                    auto_exclude_sweep()
                    last_sweep = now
                try:
                    data = json.loads(message.get("data") or "{}")
                    slug = data.get("slug") or ""
                    result = data.get("result")
                    if slug and result is not None:
                        process_result(int(result), slug)
                except Exception:
                    log.exception("Erro processando mensagem")
        except Exception:
            log.exception("Redis erro — reconectando em 5s")
            time.sleep(5)


if __name__ == "__main__":
    run()
