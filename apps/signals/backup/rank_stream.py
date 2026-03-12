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
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Callable

import redis.asyncio as redis
import requests

from core.api import RouletteAPI
from core.redis import save_signal
from helpers.roulettes_list import roulettes
from helpers.utils.get_neighbords import get_neighbords
from helpers.waiting_controller import waiting_controller
from patterns.registry import list_pattern_files




PATTERNS_DIR = Path(__file__).resolve().parent / "patterns_rank"
STATUS_REQUIRED = "processing"

BET_API_URL = "http://localhost:3000/api/bet"

logger = logging.getLogger(__name__)


def _sanitize_module_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)


def _place_bet_sync(signal: dict) -> dict:
    print("[BET API] Aguardando 5 segundos antes de enviar aposta...")
    time.sleep(5)

    payload = {
        "bets": signal["bets"],
        "attempts": 3,
        "gales": 3,
        "roulette_url": signal["roulette_url"],
        "signal_id": str(signal.get("id", "")),
    }

    print(
        "[BET API] Enviando aposta: %s - %d numeros"
        % (signal["roulette_name"], len(signal["bets"]))
    )

    try:
        response = requests.post(BET_API_URL, json=payload, timeout=300)
        response.raise_for_status()
        try:
            result = response.json()
        except ValueError:
            result = {
                "success": False,
                "status": response.status_code,
                "error": "Resposta nao-JSON da API de apostas",
                "body": response.text,
            }
        print("[BET API] Resposta: %s" % result)
        return result
    except requests.RequestException as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        body = getattr(getattr(e, "response", None), "text", None)
        print("[BET API] Erro ao chamar API de apostas: %s" % e)
        return {"success": False, "status": status, "error": str(e), "body": body}


def _fire_bet_async(signal: dict) -> None:
    def run_bet():
        try:
            
            _place_bet_sync(signal)
        except Exception as e:
            print("[BET THREAD] Erro na thread de aposta: %s" % e)

    thread = threading.Thread(target=run_bet, daemon=True)
    thread.start()
    print("[BET] Aposta disparada em background para %s" % signal["roulette_name"])


def _load_pattern_module(path: Path):
    module_name = f"rank_stream_patterns.{_sanitize_module_name(path.stem)}"
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


def _has_repeated_terminal(last_three: list[int]) -> bool:
    terminals = [n % 10 for n in last_three]
    return len(set(terminals)) != len(terminals)


def _is_consecutive_sequence(last_three: list[int]) -> bool:
    a, b, c = last_three
    return (b == a - 1 and c == b - 1) or (b == a + 1 and c == b + 1)


def _are_neighbors(a: int, b: int) -> bool:
    return b in get_neighbords(a, 1) or a in get_neighbords(b, 1)


def _has_adjacent_neighbors(last_three: list[int]) -> bool:
    a, b, c = last_three
    return _are_neighbors(a, b) or _are_neighbors(b, c)


def _is_alternating_sequence(last_three: list[int]) -> bool:
    a, b, c = last_three
    return abs(a - c) == 1 and b not in (a, c)


def _is_alternating_repeat(last_three: list[int]) -> bool:
    a, b, c = last_three
    return a == c and b != a


def _should_skip_suggestion(last_three: list[int]) -> str | None:
    if len(last_three) < 3:
        return None

    if _has_repeated_terminal(last_three):
        return "repeticao_terminal"
    if last_three[1] == 0:
        return "zero_atras"
    if _is_consecutive_sequence(last_three):
        return "sequencia_consecutiva"
    if _has_adjacent_neighbors(last_three):
        return "vizinhos_consecutivos"
    if _is_alternating_sequence(last_three):
        return "sequencia_alternada"
    if _is_alternating_repeat(last_three):
        return "repeticao_alternada"
    return None


def _find_roulette(slug: str) -> dict:
    for roulette in roulettes:
        if roulette.get("slug") == slug:
            return roulette
    raise ValueError(f"Roleta nao encontrada para slug: {slug}")


def _load_pattern_functions() -> list[Callable]:
    functions: list[Callable] = []
    for path in list_pattern_files(PATTERNS_DIR):
        module = _load_pattern_module(path)
        if module is None:
            continue
        func = getattr(module, "process_roulette", None)
        if func is None:
            continue
        functions.append(func)
    return functions


def _rank_from_patterns(
    roulette: dict, numbers: list[int], funcs: list[Callable], top: int
) -> tuple[list[int], int, dict[str, list[int]], dict[str, tuple[int, int]]]:
    counts: Counter[int] = Counter()
    with_signals = 0
    last_number = numbers[0] if numbers else None
    pattern_bets: dict[str, set[int]] = {}

    for func in funcs:
        try:
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                signal = _call_process_roulette(func, roulette, numbers)
        except Exception as exc:
            logger.debug("Falha ao executar pattern: %s", exc)
            continue

        if not isinstance(signal, dict):
            continue

        status = str(signal.get("status", "")).lower().strip()
        if status == "waiting":
            waiting_controller.register(signal)
            continue
        if status != STATUS_REQUIRED:
            continue

        bets = _normalize_bets(signal.get("bets"))
        if not bets:
            continue

        pattern_name = str(signal.get("pattern", "")).strip() or "UNKNOWN"
        pattern_bets.setdefault(pattern_name, set()).update(bets)
        with_signals += 1
        for number in set(bets):
            counts[number] += 1

    for signal in waiting_controller.consume_trigger(last_number):
        bets = _normalize_bets(signal.get("bets"))
        if not bets:
            continue
        pattern_name = str(signal.get("pattern", "")).strip() or "UNKNOWN"
        pattern_bets.setdefault(pattern_name, set()).update(bets)
        with_signals += 1
        for number in set(bets):
            counts[number] += 1

    ranked = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    top_numbers = [n for n, _ in ranked[:top]]
    pattern_numbers = {
        name: sorted(nums) for name, nums in sorted(pattern_bets.items())
    }
    total_results = len(numbers)
    pattern_scores: dict[str, tuple[int, int]] = {}
    for name, nums in pattern_numbers.items():
        bet_set = set(nums)
        hits = sum(1 for n in numbers if n in bet_set)
        pattern_scores[name] = (hits, total_results)
    return top_numbers, with_signals, pattern_numbers, pattern_scores


def _get_result_channel() -> str:
    mode_simulator = os.getenv("SIMULATOR", "false").lower() == "true"
    if mode_simulator:
        return "new_result_simulate"
    return os.getenv("RESULT_CHANNEL", "new_result")


async def _fetch_initial_history(slug: str, limit: int) -> list[int]:
    api = RouletteAPI()
    resp = await api.api(slug, num_results=limit, full_results=False)
    results = resp.get("results", [])
    numbers = [r["value"] if isinstance(r, dict) else r for r in results]
    return numbers[:limit]


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

    current_suggestion: list[int] = []
    since_last_rank = 0

    logger.debug("Escutando %s para %s", channel, args.slug)
    logger.debug("Atualizando sugestao a cada %d numeros", args.every)

    try:
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0
            )
            if message is None:
                await asyncio.sleep(0.05)
                continue

            try:
                data = json.loads(message["data"])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if data.get("slug") != args.slug:
                continue

            number = data.get("result")
            if number is None:
                continue

            try:
                number = int(number)
            except (TypeError, ValueError):
                continue

            print("inicio", number)
            history.insert(0, number)
            if len(history) > args.limit:
                history = history[: args.limit]

            since_last_rank += 1

            if since_last_rank >= args.every:
                current_suggestion, with_signals, pattern_numbers, pattern_scores = _rank_from_patterns(
                    roulette, history, funcs, args.top
                )
                since_last_rank = 0
                if not current_suggestion:
                    print(
                        "Sem sugestao | patterns processing: %d | ultimos 3: %s"
                        % (
                            with_signals,
                            ", ".join(str(n) for n in history[:3]),
                        )
                    )
                    continue
                last_three = history[:3]

                skip_reason = _should_skip_suggestion(last_three)
                if skip_reason:
                    print(
                        "Sugestao ignorada (%s) | ultimos 3: %s"
                        % (
                            skip_reason,
                            ", ".join(str(n) for n in last_three),
                        )
                    )
                    continue

            

                previous_ten = history[0:7]
                score_hits = len(set(current_suggestion) & set(previous_ten))

                recent_window = history[:400]
                recent_counts = Counter(recent_window)
                top_count = max(1, len(current_suggestion))
                top_numbers = [n for n, _ in recent_counts.most_common(top_count)]
                overlap = len(set(current_suggestion) & set(top_numbers))
                overlap_ratio = overlap / len(current_suggestion) if current_suggestion else 0.0
                if overlap_ratio < 0.5:
                    print(
                        "Sugestao ignorada (abaixo 60%% hot) | overlap %d/%d (%.1f%%) | ultimos 3: %s"
                        % (
                            overlap,
                            len(current_suggestion),
                            overlap_ratio * 100,
                            ", ".join(str(n) for n in last_three),
                        )
                    )
                    continue

                if score_hits <= 4 :
                    continue 

                created_at = int(time.time())
                signal_id = save_signal(
                    roulette_id=roulette["slug"],
                    roulette_name=roulette["name"],
                    roulette_url=roulette["url"],
                    triggers=last_three,
                    targets=current_suggestion,
                    bets=current_suggestion,
                    snapshot=history[:500],
                    status="processing",
                    pattern=f"RANK-{with_signals}",
                    passed_spins=0,
                    spins_required=0,
                    gales=4,
                    score=score_hits,
                    message="",
                    temp_state=None,
                    create_at=created_at,
                    timestamp=created_at,
                    tags=[],
                )
                _fire_bet_async(
                    {
                        "id": signal_id,
                        "bets": current_suggestion,
                        "roulette_url": roulette["url"],
                        "roulette_name": roulette["name"],
                    }
                ) 
                print(
                    "Sugestao (%d nums) | patterns processing: %d | ultimos 3: %s | %s"
                    % (
                        args.top,
                        with_signals,
                        ", ".join(str(n) for n in last_three),
                        ", ".join(str(n) for n in current_suggestion),
                    )
                )
                if pattern_numbers:
                    print("Patterns:")
                    for name, nums in pattern_numbers.items():
                        hits, total = pattern_scores.get(name, (0, 0))
                        pct = (hits / total * 100) if total else 0.0
                        print(
                            " - %s: %s | %d/%d (%.1f%%)"
                            % (name, ", ".join(str(n) for n in nums), hits, total, pct)
                        )
    finally:
        await pubsub.unsubscribe(channel)
        await client.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gera sugestao de 12 numeros a cada 3 resultados e valida hits."
    )
    parser.add_argument("slug", help="Slug da roleta (ex: pragmatic-auto-roulette)")
    parser.add_argument("--limit", type=int, default=500, help="Historico base (default: 500)")
    parser.add_argument("--top", type=int, default=12, help="Quantidade de numeros (default: 12)")
    parser.add_argument("--every", type=int, default=3, help="Atualiza sugestao a cada N numeros")
    parser.add_argument("--debug", action="store_true", help="Habilita logs de debug")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.ERROR)
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
