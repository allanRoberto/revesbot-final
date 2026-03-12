#!/usr/bin/env python3
import argparse
import asyncio
import importlib.util
import inspect
import io
import json
import logging
import os
import re
import threading
import time
from collections import Counter, defaultdict
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Callable

import redis.asyncio as redis
import requests

from core.api import RouletteAPI
from core.redis import save_signal
from helpers.roulettes_list import roulettes
from patterns.registry import list_pattern_files


PATTERNS_DIR = Path(__file__).resolve().parent / "patterns"
STATUS_REQUIRED = "processing"

DEFAULT_BASE_WEIGHT = 1.0
DEFAULT_HIT_BONUS = 0.3
DEFAULT_ATTEMPT_DECAY = 0.7
DEFAULT_MISS_PENALTY = 0.2
DEFAULT_MIN_WEIGHT = 0.2
DEFAULT_MAX_WEIGHT = 3.0
DEFAULT_MAX_ATTEMPTS = 4

BET_API_URL = "http://localhost:3000/api/bet"

logger = logging.getLogger(__name__)


class PatternState:
    def __init__(self, weight: float) -> None:
        self.weight = weight
        self.pending_bets: list[int] = []
        self.pending_attempts = 0
        self.hits = 0
        self.misses = 0


def _place_bet_sync(signal: dict) -> dict:
    print("[BET API] Aguardando 5 segundos antes de enviar aposta...")
    time.sleep(5)

    payload = {
        "bets": signal["bets"],
        "attempts": 1,
        "gales": 1,
        "roulette_url": signal["roulette_url"],
        "signal_id": str(signal.get("id", "")),
        "valor": 0.5,
    }

    print(
        "[BET API] Enviando aposta: %s - %d numeros"
        % (signal["roulette_name"], len(signal["bets"]))
    )

    try:
        response = requests.post(BET_API_URL, json=payload, timeout=300)
        result = response.json()
        print("[BET API] Resposta: %s" % result)
        return result
    except Exception as e:
        print("[BET API] Erro ao chamar API de apostas: %s" % e)
        return {"success": False, "error": str(e)}


def _fire_bet_async(signal: dict) -> None:
    def run_bet():
        try:
            _place_bet_sync(signal)
        except Exception as e:
            print("[BET THREAD] Erro na thread de aposta: %s" % e)

    thread = threading.Thread(target=run_bet, daemon=True)
    thread.start()
    print("[BET] Aposta disparada em background para %s" % signal["roulette_name"])


def _sanitize_module_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)


def _load_pattern_module(path: Path):
    module_name = f"rank_stream_weighted_patterns.{_sanitize_module_name(path.stem)}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            spec.loader.exec_module(module)
    except Exception as exc:
        logger.debug("Falha ao importar %s: %s", path.name, exc)
        return None
    return module


def _call_process_roulette(func, roulette: dict, numbers: list[int]) -> Any:
    sig = inspect.signature(func)
    num_params = len(sig.parameters)
    if num_params < 2:
        raise TypeError("process_roulette precisa de ao menos 2 parametros")

    args = [roulette, numbers]
    if num_params >= 3:
        args.append(None)
    if num_params >= 4:
        args.append(None)
    return func(*args)


def _normalize_bets(bets: Any) -> list[int]:
    if bets is None:
        return []
    if isinstance(bets, list):
        return [int(b) for b in bets]
    return [int(bets)]


def _find_roulette(slug: str) -> dict:
    for roulette in roulettes:
        if roulette.get("slug") == slug:
            return roulette
    raise ValueError(f"Roleta nao encontrada para slug: {slug}")


def _load_pattern_functions() -> list[tuple[str, Callable]]:
    functions: list[tuple[str, Callable]] = []
    for path in list_pattern_files(PATTERNS_DIR):
        module = _load_pattern_module(path)
        if module is None:
            continue
        func = getattr(module, "process_roulette", None)
        if func is None:
            continue
        functions.append((path.stem, func))
    return functions


def _get_result_channel() -> str:
    mode_simulator = os.getenv("SIMULATOR", "false").lower() == "true"
    if mode_simulator:
        return os.getenv("RESULT_CHANNEL", "new_result")
    return os.getenv("RESULT_CHANNEL", "new_result")


async def _fetch_initial_history(slug: str, limit: int) -> list[int]:
    api = RouletteAPI()
    resp = await api.api(slug, num_results=limit, full_results=False)
    results = resp.get("results", [])
    numbers = [r["value"] if isinstance(r, dict) else r for r in results]
    return numbers[:limit]


def _update_pattern_weights(
    number: int,
    states: dict[str, PatternState],
    max_attempts: int,
    hit_bonus: float,
    attempt_decay: float,
    miss_penalty: float,
    min_weight: float,
    max_weight: float,
) -> None:
    for state in states.values():
        if not state.pending_bets:
            continue

        state.pending_attempts += 1
        if number in state.pending_bets:
            bonus = hit_bonus * (attempt_decay ** max(0, state.pending_attempts - 1))
            state.weight = min(max_weight, state.weight + bonus)
            state.hits += 1
            state.pending_bets = []
            state.pending_attempts = 0
            continue

        if state.pending_attempts >= max_attempts:
            state.weight = max(min_weight, state.weight - miss_penalty)
            state.misses += 1
            state.pending_bets = []
            state.pending_attempts = 0


def _rank_from_patterns(
    roulette: dict,
    numbers: list[int],
    funcs: list[tuple[str, Callable]],
    states: dict[str, PatternState],
    base_weight: float,
    top: int,
) -> tuple[list[int], int]:
    counts: defaultdict[int, float] = defaultdict(float)
    with_signals = 0

    for pattern_id, func in funcs:
        try:
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                signal = _call_process_roulette(func, roulette, numbers)
        except Exception as exc:
            logger.debug("Falha ao executar pattern: %s", exc)
            continue

        if not isinstance(signal, dict):
            continue

        status = str(signal.get("status", "")).lower().strip()
        if status != STATUS_REQUIRED:
            continue

        bets = _normalize_bets(signal.get("bets"))
        if not bets:
            continue

        with_signals += 1
        state = states.setdefault(pattern_id, PatternState(base_weight))
        weight = state.weight
        for number in set(bets):
            counts[number] += weight

        # Atualiza a tentativa ativa para medir acertos por pattern.
        state.pending_bets = list(set(bets))
        state.pending_attempts = 0

    ranked = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    top_numbers = [n for n, _ in ranked[:top]]
    return top_numbers, with_signals


def _log_pattern_weights(states: dict[str, PatternState]) -> None:
    if not states:
        return
    ranked = sorted(states.items(), key=lambda item: (-item[1].weight, item[0]))
    weights_info = ", ".join(
        f"{pattern}:{state.weight:.2f}" for pattern, state in ranked
    )
    print(f"Pesos por pattern: {weights_info}")


def _build_bet_signal(signal_id: str, roulette: dict, bets: list[int]) -> dict:
    return {
        "id": signal_id,
        "bets": bets,
        "roulette_url": roulette["url"],
        "roulette_name": roulette["name"],
    }


async def main_async(args: argparse.Namespace) -> int:
    roulette = _find_roulette(args.slug)
    history = await _fetch_initial_history(args.slug, args.limit)
    if not history:
        logger.error("Nao foi possivel carregar historico para %s", args.slug)
        return 1

    funcs = _load_pattern_functions()
    if not funcs:
        logger.error("Nenhum pattern valido encontrado")
        return 1

    redis_url = os.getenv("REDIS_CONNECT")
    if not redis_url:
        logger.error("REDIS_CONNECT nao configurado")
        return 1

    channel = _get_result_channel()
    client = redis.from_url(redis_url, decode_responses=True)
    pubsub = client.pubsub()
    await pubsub.subscribe(channel)

    pattern_states: dict[str, PatternState] = {}
    current_suggestion: list[int] = []
    since_last_rank = 0
    pending_suggestion: list[int] = []
    pending_attempts = 0

    logger.debug("Escutando %s para %s", channel, args.slug)
    logger.debug("Atualizando sugestao a cada %d numeros", args.every)

    current_suggestion, with_signals = _rank_from_patterns(
        roulette, history, funcs, pattern_states, args.base_weight, args.top
    )
    created_at = int(time.time())
    signal_id = save_signal(
        roulette_id=roulette["slug"],
        roulette_name=roulette["name"],
        roulette_url=roulette["url"],
        triggers=history[:3],
        targets=current_suggestion,
        bets=current_suggestion,
        snapshot=history[:50],
        status="processing",
        pattern="RANK",
        passed_spins=0,
        spins_required=0,
        gales=4,
        score=0,
        message="",
        temp_state=None,
        create_at=created_at,
        timestamp=created_at,
        tags=[],
    )
    if args.send_bet:
        _fire_bet_async(_build_bet_signal(signal_id, roulette, current_suggestion))
    pending_suggestion = current_suggestion[:]
    pending_attempts = 0
    print(
        "Sugestao (%d nums) | patterns processing: %d | ultimos 3: %s | %s"
        % (
            args.top,
            with_signals,
            ", ".join(str(n) for n in history[:3]),
            ", ".join(str(n) for n in current_suggestion),
        )
    )
    _log_pattern_weights(pattern_states)
    print("Monitorando os resultados...")

    try:
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0
            )
            if message is None:
                await asyncio.sleep(0.05)
                continue

            data = json.loads(message["data"])
            if data.get("slug") != args.slug:
                continue

            number = data.get("result")
            if number is None:
                continue

            try:
                number = int(number)
            except (TypeError, ValueError):
                continue

            history.insert(0, number)
            if len(history) > args.limit:
                history = history[: args.limit]

            if pending_suggestion:
                pending_attempts += 1
                if number in pending_suggestion:
                    print(f"Acertou na {pending_attempts} tentativa.")
                    pending_suggestion = []
                    pending_attempts = 0

            _update_pattern_weights(
                number=number,
                states=pattern_states,
                max_attempts=args.max_attempts,
                hit_bonus=args.hit_bonus,
                attempt_decay=args.attempt_decay,
                miss_penalty=args.miss_penalty,
                min_weight=args.min_weight,
                max_weight=args.max_weight,
            )

            since_last_rank += 1

            if since_last_rank >= args.every:
                current_suggestion, with_signals = _rank_from_patterns(
                    roulette, history, funcs, pattern_states, args.base_weight, args.top
                )
                since_last_rank = 0
                last_three = history[:3]
                created_at = int(time.time())
                signal_id = save_signal(
                    roulette_id=roulette["slug"],
                    roulette_name=roulette["name"],
                    roulette_url=roulette["url"],
                    triggers=last_three,
                    targets=current_suggestion,
                    bets=current_suggestion,
                    snapshot=history[:50],
                    status="processing",
                    pattern="RANK",
                    passed_spins=0,
                    spins_required=0,
                    gales=3,
                    score=0,
                    message="",
                    temp_state=None,
                    create_at=created_at,
                    timestamp=created_at,
                    tags=[],
                )
                if args.send_bet:
                    _fire_bet_async(_build_bet_signal(signal_id, roulette, current_suggestion))
                print(
                    "Sugestao (%d nums) | patterns processing: %d | ultimos 3: %s | %s"
                    % (
                        args.top,
                        with_signals,
                        ", ".join(str(n) for n in last_three),
                        ", ".join(str(n) for n in current_suggestion),
                    )
                )
                _log_pattern_weights(pattern_states)
                print("Monitorando os resultados...")
                pending_suggestion = current_suggestion[:]
                pending_attempts = 0
    finally:
        await pubsub.unsubscribe(channel)
        await client.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sugestao com pesos por performance (acerto x tentativas)."
    )
    parser.add_argument("slug", help="Slug da roleta (ex: pragmatic-auto-roulette)")
    parser.add_argument("--limit", type=int, default=500, help="Historico base (default: 500)")
    parser.add_argument("--top", type=int, default=12, help="Quantidade de numeros (default: 12)")
    parser.add_argument("--every", type=int, default=3, help="Atualiza sugestao a cada N numeros")
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS, help="Tentativas por pattern")
    parser.add_argument("--base-weight", type=float, default=DEFAULT_BASE_WEIGHT, help="Peso inicial por pattern")
    parser.add_argument("--hit-bonus", type=float, default=DEFAULT_HIT_BONUS, help="Bonus por acerto")
    parser.add_argument(
        "--attempt-decay",
        type=float,
        default=DEFAULT_ATTEMPT_DECAY,
        help="Decaimento do bonus por tentativa",
    )
    parser.add_argument("--miss-penalty", type=float, default=DEFAULT_MISS_PENALTY, help="Penalidade por erro")
    parser.add_argument("--min-weight", type=float, default=DEFAULT_MIN_WEIGHT, help="Peso minimo")
    parser.add_argument("--max-weight", type=float, default=DEFAULT_MAX_WEIGHT, help="Peso maximo")
    parser.add_argument("--send-bet", action="store_true", help="Envia aposta para a API")
    parser.add_argument("--debug", action="store_true", help="Habilita logs de debug")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.ERROR)
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
