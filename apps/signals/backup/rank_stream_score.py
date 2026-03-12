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
from collections import Counter, deque
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Callable

import redis.asyncio as redis

from core.api import RouletteAPI
from helpers.roulettes_list import roulettes
from patterns.registry import list_pattern_files


PATTERNS_DIR = Path(__file__).resolve().parent / "patterns"
STATUS_REQUIRED = "processing"

logger = logging.getLogger(__name__)


def _sanitize_module_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)


def _load_pattern_module(path: Path):
    module_name = f"rank_stream_score_patterns.{_sanitize_module_name(path.stem)}"
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


def _evaluate_patterns(
    roulette: dict, numbers: list[int], funcs: list[tuple[str, Callable]]
) -> tuple[Counter[int], int]:
    counts: Counter[int] = Counter()
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
        for number in set(bets):
            counts[number] += 1

    return counts, with_signals


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

    last_numbers: deque[int] = deque(maxlen=args.every)
    prev_blended: list[int] = []
    suggestion_window: deque[list[int]] = deque(maxlen=args.blend_window)
    wins = 0
    losses = 0
    total_hits = 0

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

            last_numbers.append(number)
            if len(last_numbers) < args.every:
                continue

            hits = 0
            if prev_blended:
                hits = sum(1 for n in last_numbers if n in prev_blended)
                total_hits += hits
                if hits > 0:
                    wins += 1
                else:
                    losses += 1

            counts, with_signals = _evaluate_patterns(roulette, history, funcs)

            ranked = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
            current_suggestion = [n for n, _ in ranked[: args.top]]

            suggestion_window.append(current_suggestion)
            blend_counts: Counter[int] = Counter()
            for sugg in suggestion_window:
                for number in sugg:
                    blend_counts[number] += 1
            blended = [
                n
                for n, _ in sorted(blend_counts.items(), key=lambda x: (-x[1], x[0]))[
                    : args.top
                ]
            ]

            last_three = list(last_numbers)
            print(
                "Ultimos %d: %s | hits: %d | placar W/L: %d/%d | total hits: %d | "
                "Sugestao mesclada (%d nums, ultimas %d) | patterns processing: %d | %s"
                % (
                    args.every,
                    ", ".join(str(n) for n in last_three),
                    hits,
                    wins,
                    losses,
                    total_hits,
                    args.top,
                    args.blend_window,
                    with_signals,
                    ", ".join(str(n) for n in blended),
                )
            )

            prev_blended = blended
            last_numbers.clear()
    finally:
        await pubsub.unsubscribe(channel)
        await client.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sugestao a cada 3 numeros com placar de acertos/erros."
    )
    parser.add_argument("slug", help="Slug da roleta (ex: pragmatic-auto-roulette)")
    parser.add_argument("--limit", type=int, default=500, help="Historico base (default: 500)")
    parser.add_argument("--top", type=int, default=12, help="Quantidade de numeros (default: 12)")
    parser.add_argument("--every", type=int, default=3, help="Avalia a cada N numeros")
    parser.add_argument("--blend-window", type=int, default=4, help="Quantidade de sugestoes mescladas")
    parser.add_argument("--debug", action="store_true", help="Habilita logs de debug")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.ERROR)
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
