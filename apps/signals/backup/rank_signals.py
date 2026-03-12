#!/usr/bin/env python3
import argparse
import asyncio
import importlib.util
import inspect
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any

from core.api import RouletteAPI
from helpers.roulettes_list import roulettes
from patterns.registry import list_pattern_files


PATTERNS_DIR = Path(__file__).resolve().parent / "patterns"
STATUS_REQUIRED = "processing"
DEFAULT_LIMIT = 500
DEFAULT_TOP = 12

logger = logging.getLogger(__name__)


def _sanitize_module_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)


def _load_pattern_module(path: Path):
    module_name = f"rank_patterns.{_sanitize_module_name(path.stem)}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        logger.warning("Falha ao importar %s: %s", path.name, exc)
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


async def _fetch_numbers(slug: str, limit: int) -> list[int]:
    api = RouletteAPI()
    resp = await api.api(slug, num_results=limit, full_results=False)
    results = resp.get("results", [])
    numbers = [r["value"] if isinstance(r, dict) else r for r in results]
    return numbers[:limit]


def _find_roulette(slug: str) -> dict:
    for roulette in roulettes:
        if roulette.get("slug") == slug:
            return roulette
    raise ValueError(f"Roleta nao encontrada para slug: {slug}")


async def main_async(args: argparse.Namespace) -> int:
    roulette = _find_roulette(args.slug)
    numbers = await _fetch_numbers(args.slug, args.limit)

    if not numbers:
        logger.error("Nao foi possivel carregar numeros para %s", args.slug)
        return 1

    counts: Counter[int] = Counter()
    processed = 0
    with_signals = 0
    errors = 0

    for path in list_pattern_files(PATTERNS_DIR):
        module = _load_pattern_module(path)
        if module is None:
            errors += 1
            continue

        func = getattr(module, "process_roulette", None)
        if func is None:
            continue

        processed += 1
        try:
            signal = _call_process_roulette(func, roulette, numbers)
        except Exception as exc:
            logger.warning("Falha ao executar %s: %s", path.name, exc)
            errors += 1
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
    top_n = ranked[: args.top]

    print(f"Roleta: {roulette.get('name')} ({roulette.get('slug')})")
    print(f"Total de patterns processados: {processed}")
    print(f"Patterns com sinal processing: {with_signals}")
    print(f"Falhas/ignorados: {errors}")
    print("")
    print("Ranking (numero -> frequencia):")
    for number, freq in ranked:
        print(f"{number:>2} -> {freq}")

    print("")
    print(f"Sugestao (top {args.top}): {', '.join(str(n) for n, _ in top_n)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Ranking de bets por frequencia entre patterns.")
    parser.add_argument("slug", help="Slug da roleta (ex: pragmatic-auto-roulette)")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Quantidade de numeros (default: 500)")
    parser.add_argument("--top", type=int, default=DEFAULT_TOP, help="Quantidade de numeros sugeridos (default: 12)")
    parser.add_argument("--debug", action="store_true", help="Habilita logs de debug")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
