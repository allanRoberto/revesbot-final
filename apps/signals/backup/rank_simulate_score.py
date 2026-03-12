#!/usr/bin/env python3
import argparse
import asyncio
import importlib.util
import inspect
import io
import logging
import os
import re
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Callable

from core.api import RouletteAPI
from helpers.roulettes_list import roulettes
from patterns.registry import list_pattern_files


PATTERNS_DIR = Path(__file__).resolve().parent / "patterns"
STATUS_REQUIRED = "processing"

logger = logging.getLogger(__name__)


def _sanitize_module_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)


def _load_pattern_module(path: Path):
    module_name = f"rank_simulate_patterns.{_sanitize_module_name(path.stem)}"
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


def _rank_from_patterns(
    roulette: dict, numbers: list[int], funcs: list[tuple[str, Callable]], top: int
) -> tuple[list[int], int]:
    counts: Counter[int] = Counter()
    with_signals = 0

    for _, func in funcs:
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

    ranked = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    top_numbers = [n for n, _ in ranked[:top]]
    return top_numbers, with_signals


async def _fetch_numbers(slug: str, total: int) -> list[int]:
    api = RouletteAPI()
    resp = await api.api(slug, num_results=total, full_results=False)
    results = resp.get("results", [])
    numbers = [r["value"] if isinstance(r, dict) else r for r in results]
    return numbers[:total]


async def main_async(args: argparse.Namespace) -> int:
    roulette = _find_roulette(args.slug)
    numbers = await _fetch_numbers(args.slug, args.fetch)
    if len(numbers) < args.history + args.step:
        logger.error("Historico insuficiente: %d", len(numbers))
        return 1

    funcs = _load_pattern_functions()
    if not funcs:
        logger.error("Nenhum pattern valido encontrado")
        return 1

    # numbers vem do mais recente -> antigo; inverter para simular cronologico
    numbers_chrono = list(reversed(numbers))

    history = list(reversed(numbers_chrono[: args.history]))
    index = args.history

    wins = 0
    losses = 0
    total_hits = 0
    total_windows = 0

    while index + args.step <= len(numbers_chrono):
        suggestion, with_signals = _rank_from_patterns(
            roulette, history, funcs, args.top
        )

        window = numbers_chrono[index : index + args.step]
        hits = sum(1 for n in window if n in suggestion)
        total_hits += hits
        total_windows += 1
        if hits > 0:
            wins += 1
        else:
            losses += 1

        # Atualiza historico com os numeros novos (mais recente primeiro)
        for n in window:
            history.insert(0, n)
        if len(history) > args.history:
            history = history[: args.history]

        index += args.step

        if args.print_each:
            print(
                "Ultimos %d: %s | hits: %d | W/L: %d/%d | patterns: %d | sugestao: %s"
                % (
                    args.step,
                    ", ".join(str(n) for n in window),
                    hits,
                    wins,
                    losses,
                    with_signals,
                    ", ".join(str(n) for n in suggestion),
                )
            )

    hit_rate = (wins / total_windows * 100.0) if total_windows else 0.0
    print("Placar final")
    print(f"Janelas: {total_windows}")
    print(f"Win/Loss: {wins}/{losses}")
    print(f"Total hits: {total_hits}")
    print(f"Win rate: {hit_rate:.2f}%")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Simulacao offline com sugestao atual (processing) e placar."
    )
    parser.add_argument("slug", help="Slug da roleta (ex: pragmatic-auto-roulette)")
    parser.add_argument("--fetch", type=int, default=1500, help="Qtd de numeros buscados")
    parser.add_argument("--history", type=int, default=500, help="Tamanho do historico")
    parser.add_argument("--top", type=int, default=12, help="Quantidade de numeros")
    parser.add_argument("--step", type=int, default=3, help="Janela de avaliacao")
    parser.add_argument("--print-each", action="store_true", help="Imprime cada janela")
    parser.add_argument("--debug", action="store_true", help="Habilita logs de debug")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.ERROR)
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
