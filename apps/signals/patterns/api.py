from __future__ import annotations

import os
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx
from dotenv import load_dotenv

load_dotenv()

URL_API = os.environ.get("BASE_URL_API", "http://localhost:8000")
MAX_BETS = max(1, min(37, int(os.environ.get("PATTERNS_API_MAX_NUMBERS", "14"))))
REQUEST_CONNECT_TIMEOUT_SECONDS = float(os.environ.get("PATTERNS_API_CONNECT_TIMEOUT_SECONDS", "5.0"))
REQUEST_READ_TIMEOUT_SECONDS = float(os.environ.get("PATTERNS_API_READ_TIMEOUT_SECONDS", "25.0"))
REQUEST_WRITE_TIMEOUT_SECONDS = float(os.environ.get("PATTERNS_API_WRITE_TIMEOUT_SECONDS", "10.0"))
REQUEST_POOL_TIMEOUT_SECONDS = float(os.environ.get("PATTERNS_API_POOL_TIMEOUT_SECONDS", "5.0"))
REQUEST_RETRIES = max(1, int(os.environ.get("PATTERNS_API_RETRIES", "3")))
REQUEST_RETRY_BACKOFF_SECONDS = max(0.0, float(os.environ.get("PATTERNS_API_RETRY_BACKOFF_SECONDS", "0.5")))
OPTIMIZED_MAX_NUMBERS = max(1, min(37, int(os.environ.get("PATTERNS_API_OPTIMIZED_MAX_NUMBERS", "37"))))
FINAL_BASE_WEIGHT = float(os.environ.get("PATTERNS_API_BASE_WEIGHT", "0.5"))
FINAL_OPTIMIZED_WEIGHT = float(os.environ.get("PATTERNS_API_OPTIMIZED_WEIGHT", "0.5"))
SIEGE_WINDOW = max(2, min(20, int(os.environ.get("PATTERNS_API_SIEGE_WINDOW", "6"))))
SIEGE_MIN_OCCURRENCES = max(1, min(10, int(os.environ.get("PATTERNS_API_SIEGE_MIN_OCCURRENCES", "3"))))
SIEGE_MIN_STREAK = max(1, min(10, int(os.environ.get("PATTERNS_API_SIEGE_MIN_STREAK", "2"))))
SIEGE_VETO_RELIEF = max(0.0, min(1.0, float(os.environ.get("PATTERNS_API_SIEGE_VETO_RELIEF", "0.4"))))
INVERSION_ENABLED = str(os.environ.get("PATTERNS_API_INVERSION_ENABLED", "false")).strip().lower() in {"1", "true", "yes", "on"}
INVERSION_CONTEXT_WINDOW = max(5, min(50, int(os.environ.get("PATTERNS_API_INVERSION_CONTEXT_WINDOW", "5"))))
INVERSION_PENALTY_FACTOR = max(0.0, min(1.0, float(os.environ.get("PATTERNS_API_INVERSION_PENALTY_FACTOR", "0.3"))))
OVERLAP_LOOKBACK = max(1, min(10, int(os.environ.get("PATTERNS_API_OVERLAP_LOOKBACK", "3"))))
OVERLAP_CONFIDENCE_HIGH = max(0, min(100, int(os.environ.get("PATTERNS_API_OVERLAP_CONFIDENCE_HIGH", "60"))))
OVERLAP_WAIT_ONE_THRESHOLD = max(1, min(14, int(os.environ.get("PATTERNS_API_OVERLAP_WAIT_ONE_THRESHOLD", "2"))))
OVERLAP_CANCEL_THRESHOLD = max(1, min(14, int(os.environ.get("PATTERNS_API_OVERLAP_CANCEL_THRESHOLD", "3"))))
WAIT_SPINS_ON_MEDIUM_OVERLAP = max(0, min(4, int(os.environ.get("PATTERNS_API_WAIT_SPINS_ON_MEDIUM_OVERLAP", "1"))))
RECENT_BETS_LOOKBACK = max(1, min(20, int(os.environ.get("PATTERNS_API_RECENT_BETS_LOOKBACK", "5"))))
RECENT_BETS_WAIT_THRESHOLD = max(0, min(RECENT_BETS_LOOKBACK, int(os.environ.get("PATTERNS_API_RECENT_BETS_WAIT_THRESHOLD", "2"))))
RECENT_BETS_WAIT_SPINS = max(0, min(6, int(os.environ.get("PATTERNS_API_RECENT_BETS_WAIT_SPINS", "2"))))
MIN_HISTORY = 10
PATTERN_NAME = "API_FINAL_SUGGESTION_10"
SIGNAL_GALES = max(1, int(os.environ.get("PATTERNS_API_GALES", "4")))
MIN_CONFIDENCE_TO_PLAY = max(0, min(100, int(os.environ.get("PATTERNS_API_MIN_CONFIDENCE", "80"))))
ACTIVE_SIGNAL_MEMORY: Dict[str, Dict[str, object]] = {}
ACTIVE_SIGNAL_LOCK = threading.Lock()


def _history_signature(numbers: List[int]) -> Tuple[int, ...]:
    return tuple(int(n) for n in numbers[:6])


def _consume_active_signal_memory(roulette_slug: str, latest_number: int, numbers: List[int]) -> bool:
    """
    Controle em memória por roleta:
    - se houver sinal ativo, consome tentativa no novo spin
    - mantém bloqueio enquanto não bater e não esgotar gales
    - libera (remove) quando bate ou quando esgota tentativas
    """
    signature = _history_signature(numbers)

    with ACTIVE_SIGNAL_LOCK:
        state = ACTIVE_SIGNAL_MEMORY.get(roulette_slug)
        if not state:
            return False

        # Evita consumo duplicado do mesmo snapshot em cenários de reprocessamento.
        if state.get("last_signature") == signature:
            return True

        bets = state.get("bets", [])
        if isinstance(bets, list) and latest_number in bets:
            ACTIVE_SIGNAL_MEMORY.pop(roulette_slug, None)
            return False

        attempts = int(state.get("attempts", 0) or 0) + 1
        gales = int(state.get("gales", SIGNAL_GALES) or SIGNAL_GALES)

        if attempts >= gales:
            ACTIVE_SIGNAL_MEMORY.pop(roulette_slug, None)
            return False

        state["attempts"] = attempts
        state["last_signature"] = signature
        ACTIVE_SIGNAL_MEMORY[roulette_slug] = state
        return True


def _register_active_signal_memory(roulette_slug: str, bets: List[int], numbers: List[int]) -> None:
    with ACTIVE_SIGNAL_LOCK:
        ACTIVE_SIGNAL_MEMORY[roulette_slug] = {
            "bets": list(bets),
            "attempts": 0,
            "gales": SIGNAL_GALES,
            "last_signature": _history_signature(numbers),
        }


def _normalize_bets(payload: Dict[str, Any], max_numbers: int) -> List[int]:
    raw = payload.get("suggestion")
    if not isinstance(raw, list):
        raw = payload.get("list")
    if not isinstance(raw, list):
        return []

    bets: List[int] = []
    for item in raw:
        try:
            n = int(item)
        except (TypeError, ValueError):
            continue
        if n < 0 or n > 36:
            continue
        bets.append(n)
    bets = sorted(bets)
    return bets[:max_numbers]


def _runtime_overrides_payload() -> Dict[str, Dict[str, int]]:
    return {
        "siege_number_boost": {
            "window": SIEGE_WINDOW,
            "min_occurrences": SIEGE_MIN_OCCURRENCES,
            "min_streak": SIEGE_MIN_STREAK,
        }
    }


def _compute_pre_trigger_policy(numbers: List[int], bets: List[int], confidence_score: int) -> Dict[str, Any]:
    """
    Regras operacionais derivadas da análise histórica:
    - olhar OVERLAP_LOOKBACK casas antes do gatilho
    - overlap 0/1: entrar
    - overlap 2: esperar 1 spin quando confidence < limiar alto
    - overlap >= 3: cancelar
    """
    previous_window = [int(n) for n in numbers[1 : 1 + OVERLAP_LOOKBACK]]
    bets_set = set(int(n) for n in bets)
    overlap_hits = sum(1 for n in previous_window if n in bets_set)
    overlap_unique = len(bets_set.intersection(previous_window))
    overlap_ratio = overlap_unique / max(1, len(bets))
    recent_window = [int(n) for n in numbers[:RECENT_BETS_LOOKBACK]]  # inclui número atual em numbers[0]
    recent_bets_hits = sum(1 for n in recent_window if n in bets_set)
    recent_bets_unique = len(bets_set.intersection(recent_window))
    force_wait_recent = recent_bets_hits > RECENT_BETS_WAIT_THRESHOLD

    should_cancel = overlap_unique >= OVERLAP_CANCEL_THRESHOLD
    wait_spins = 0
    action = "enter"

    if force_wait_recent:
        # Nova regra: se nos últimos 5 (incluindo atual) houver mais de 2 ocorrências dos números da aposta,
        # prioriza espera de 2 rodadas.
        should_cancel = False
        wait_spins = RECENT_BETS_WAIT_SPINS
        action = "wait" if wait_spins > 0 else "enter"
    elif should_cancel:
        action = "cancel"
    elif overlap_unique >= OVERLAP_WAIT_ONE_THRESHOLD and confidence_score < OVERLAP_CONFIDENCE_HIGH:
        wait_spins = WAIT_SPINS_ON_MEDIUM_OVERLAP
        action = "wait" if wait_spins > 0 else "enter"

    return {
        "action": action,
        "wait_spins": wait_spins,
        "should_cancel": should_cancel,
        "lookback": OVERLAP_LOOKBACK,
        "overlap_unique": overlap_unique,
        "overlap_hits": overlap_hits,
        "overlap_ratio": overlap_ratio,
        "previous_window": previous_window,
        "confidence_threshold": OVERLAP_CONFIDENCE_HIGH,
        "recent_bets_window": recent_window,
        "recent_bets_hits": recent_bets_hits,
        "recent_bets_unique": recent_bets_unique,
        "recent_bets_wait_threshold": RECENT_BETS_WAIT_THRESHOLD,
        "recent_bets_wait_spins": RECENT_BETS_WAIT_SPINS,
        "recent_bets_forced_wait": force_wait_recent,
    }


def _call_final_suggestion(history: List[int], focus_number: int, max_numbers: int) -> Optional[Dict[str, Any]]:
    url = f"{URL_API.rstrip('/')}/api/patterns/final-suggestion"
    payload: Dict[str, Any] = {
        "history": history,
        "focus_number": focus_number,
        "from_index": 0,
        "max_numbers": max_numbers,
        "optimized_max_numbers": OPTIMIZED_MAX_NUMBERS,
        "base_weight": FINAL_BASE_WEIGHT,
        "optimized_weight": FINAL_OPTIMIZED_WEIGHT,
        "runtime_overrides": _runtime_overrides_payload(),
        "siege_window": SIEGE_WINDOW,
        "siege_min_occurrences": SIEGE_MIN_OCCURRENCES,
        "siege_min_streak": SIEGE_MIN_STREAK,
        "siege_veto_relief": SIEGE_VETO_RELIEF,
        "inversion_enabled": INVERSION_ENABLED,
        "inversion_context_window": INVERSION_CONTEXT_WINDOW,
        "inversion_penalty_factor": INVERSION_PENALTY_FACTOR,
    }
    timeout = httpx.Timeout(
        connect=REQUEST_CONNECT_TIMEOUT_SECONDS,
        read=REQUEST_READ_TIMEOUT_SECONDS,
        write=REQUEST_WRITE_TIMEOUT_SECONDS,
        pool=REQUEST_POOL_TIMEOUT_SECONDS,
    )

    for attempt in range(1, REQUEST_RETRIES + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, dict):
                    return None
                return data
        except Exception as exc:
            if attempt >= REQUEST_RETRIES:
                print(
                    "[patterns.api] erro ao chamar final-suggestion "
                    f"(tentativas={REQUEST_RETRIES}, url={url}): {exc}"
                )
                return None
            time.sleep(REQUEST_RETRY_BACKOFF_SECONDS * attempt)

    return None


def _build_signal(
    *,
    roulette: Dict[str, Any],
    numbers: List[int],
    focus_number: int,
    bets: List[int],
    confidence_score: int,
    confidence_label: str,
    overlap_policy: Dict[str, Any],
) -> Dict[str, Any]:
    created_at = int(datetime.now().timestamp())
    initial_wait_spins = int(overlap_policy.get("wait_spins", 0) or 0)
    overlap_unique = int(overlap_policy.get("overlap_unique", 0) or 0)
    overlap_hits = int(overlap_policy.get("overlap_hits", 0) or 0)
    overlap_ratio = float(overlap_policy.get("overlap_ratio", 0.0) or 0.0)
    previous_window = list(overlap_policy.get("previous_window", []))
    confidence_threshold = int(overlap_policy.get("confidence_threshold", OVERLAP_CONFIDENCE_HIGH) or OVERLAP_CONFIDENCE_HIGH)
    recent_bets_window = list(overlap_policy.get("recent_bets_window", []))
    recent_bets_hits = int(overlap_policy.get("recent_bets_hits", 0) or 0)
    recent_bets_unique = int(overlap_policy.get("recent_bets_unique", 0) or 0)
    recent_bets_forced_wait = bool(overlap_policy.get("recent_bets_forced_wait", False))

    message = (
        f"API Final Suggestion ({MAX_BETS}): confianca {confidence_label} "
        f"({confidence_score}%) [min={MIN_CONFIDENCE_TO_PLAY}%]"
    )
    if initial_wait_spins > 0:
        if recent_bets_forced_wait:
            message = (
                f"⏳ ESPERA {initial_wait_spins} spin(s) (regra últimos {RECENT_BETS_LOOKBACK}: "
                f"hits={recent_bets_hits} > {RECENT_BETS_WAIT_THRESHOLD}) - {message}"
            )
        else:
            message = (
                f"⏳ ESPERA {initial_wait_spins} spin(s) antes da entrada "
                f"(overlap={overlap_unique}, janela={OVERLAP_LOOKBACK}, corte_conf={confidence_threshold}) - {message}"
            )

    return {
        "roulette_id": roulette["slug"],
        "roulette_name": roulette["name"],
        "roulette_url": roulette["url"],
        "pattern": PATTERN_NAME,
        "triggers": [focus_number],
        "targets": [focus_number],
        "bets": bets,
        "passed_spins": 0,
        "spins_required": initial_wait_spins,
        "spins_count": 0,
        "gales": SIGNAL_GALES,
        "score": confidence_score,
        "snapshot": numbers[:500],
        "status": "processing",
        "message": message,
        "tags": ["api", "final_suggestion", "top10"],
        "temp_state": {
            "focus_number": focus_number,
            "confidence_label": confidence_label,
            "confidence_score": confidence_score,
            "bets_size": len(bets),
            "initial_wait_spins": initial_wait_spins,
            "overlap_lookback": OVERLAP_LOOKBACK,
            "overlap_unique": overlap_unique,
            "overlap_hits": overlap_hits,
            "overlap_ratio": overlap_ratio,
            "overlap_previous_window": previous_window,
            "confidence_threshold_for_wait": confidence_threshold,
            "pre_trigger_action": str(overlap_policy.get("action", "enter")),
            "recent_bets_window": recent_bets_window,
            "recent_bets_hits": recent_bets_hits,
            "recent_bets_unique": recent_bets_unique,
            "recent_bets_forced_wait": recent_bets_forced_wait,
            "recent_bets_wait_threshold": RECENT_BETS_WAIT_THRESHOLD,
        },
        "created_at": created_at,
        "timestamp": created_at,
    }


def process_roulette(
    roulette: Dict[str, Any],
    numbers: List[int],
    full_results: List[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    if not numbers or len(numbers) < MIN_HISTORY:
        return None

    roulette_slug = str(roulette.get("slug", "")).strip()
    focus_number = int(numbers[0])

    if roulette_slug and _consume_active_signal_memory(roulette_slug, focus_number, numbers):
        return None

    data = _call_final_suggestion(history=numbers, focus_number=focus_number, max_numbers=MAX_BETS)
    if not data:
        return None

    if not bool(data.get("available", False)):
        return None

    bets = _normalize_bets(data, MAX_BETS)
    if len(bets) < MAX_BETS:
        return None

    confidence = data.get("confidence", {}) if isinstance(data.get("confidence"), dict) else {}
    confidence_score = int(confidence.get("score", 0) or 0)
    confidence_label = str(confidence.get("label", "Baixa"))
    if confidence_score < MIN_CONFIDENCE_TO_PLAY:
        return None

    overlap_policy = _compute_pre_trigger_policy(numbers, bets, confidence_score)
    if bool(overlap_policy.get("should_cancel", False)):
        return None

    if roulette_slug:
        _register_active_signal_memory(roulette_slug, bets, numbers)

    return _build_signal(
        roulette=roulette,
        numbers=numbers,
        focus_number=focus_number,
        bets=bets,
        confidence_score=confidence_score,
        confidence_label=confidence_label,
        overlap_policy=overlap_policy,
    )
