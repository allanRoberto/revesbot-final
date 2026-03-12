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
from helpers.utils.get_neighbords import get_neighbords
from helpers.waiting_controller import waiting_controller
from patterns.registry import list_pattern_files


PATTERNS_DIR = Path(__file__).resolve().parent / "patterns_rank"
STATUS_REQUIRED = "processing"

BET_API_URL = "http://localhost:3000/api/bet"

logger = logging.getLogger(__name__)


def _log_info(message: str) -> None:
    print(f"[RANKED] {message}", flush=True)


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
    module_name = f"rank_stream_ranked_patterns.{_sanitize_module_name(path.stem)}"
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


def _penalty_reasons(last_three: list[int]) -> list[str]:
    if len(last_three) < 3:
        return []

    reasons: list[str] = []
    if _has_repeated_terminal(last_three):
        reasons.append("repeticao_terminal")
    if last_three[1] == 0:
        reasons.append("zero_atras")
    if _is_consecutive_sequence(last_three):
        reasons.append("sequencia_consecutiva")
    if _has_adjacent_neighbors(last_three):
        reasons.append("vizinhos_consecutivos")
    if _is_alternating_sequence(last_three):
        reasons.append("sequencia_alternada")
    if _is_alternating_repeat(last_three):
        reasons.append("repeticao_alternada")
    return reasons


def _penalty_factor(reasons: list[str]) -> float:
    penalties = {
        "repeticao_terminal": 0.8,
        "zero_atras": 0.8,
        "sequencia_consecutiva": 0.7,
        "vizinhos_consecutivos": 0.8,
        "sequencia_alternada": 0.9,
        "repeticao_alternada": 0.9,
    }
    factor = 1.0
    for reason in reasons:
        factor *= penalties.get(reason, 1.0)
    return factor


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


def _compute_pattern_scores(
    pattern_numbers: dict[str, list[int]],
    numbers: list[int],
    short_window: int,
    long_window: int,
) -> dict[str, dict[str, float]]:
    scores: dict[str, dict[str, float]] = {}
    short_slice = numbers[:short_window]
    long_slice = numbers[:long_window]
    for name, nums in pattern_numbers.items():
        bet_set = set(nums)
        short_hits = sum(1 for n in short_slice if n in bet_set)
        long_hits = sum(1 for n in long_slice if n in bet_set)
        short_total = len(short_slice)
        long_total = len(long_slice)
        short_rate = (short_hits / short_total) if short_total else 0.0
        long_rate = (long_hits / long_total) if long_total else 0.0
        weight = max(0.05, (short_rate * 0.7) + (long_rate * 0.3))
        scores[name] = {
            "short_hits": short_hits,
            "short_total": short_total,
            "short_rate": short_rate,
            "long_hits": long_hits,
            "long_total": long_total,
            "long_rate": long_rate,
            "weight": weight,
        }
    return scores


def _rank_from_patterns(
    roulette: dict,
    numbers: list[int],
    funcs: list[Callable],
    top: int,
    short_window: int,
    long_window: int,
) -> tuple[list[int], int, dict[str, list[int]], dict[str, dict[str, float]], dict[int, float]]:
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

    for signal in waiting_controller.consume_trigger(last_number):
        bets = _normalize_bets(signal.get("bets"))
        if not bets:
            continue
        pattern_name = str(signal.get("pattern", "")).strip() or "UNKNOWN"
        pattern_bets.setdefault(pattern_name, set()).update(bets)
        with_signals += 1

    pattern_numbers = {
        name: sorted(nums) for name, nums in sorted(pattern_bets.items())
    }

    pattern_scores = _compute_pattern_scores(
        pattern_numbers=pattern_numbers,
        numbers=numbers,
        short_window=short_window,
        long_window=long_window,
    )

    weighted_counts: dict[int, float] = defaultdict(float)
    for name, nums in pattern_numbers.items():
        weight = pattern_scores.get(name, {}).get("weight", 0.0)
        for number in set(nums):
            weighted_counts[number] += weight

    ranked = sorted(weighted_counts.items(), key=lambda x: (-x[1], x[0]))
    top_numbers = [n for n, _ in ranked[:top]]

    return top_numbers, with_signals, pattern_numbers, pattern_scores, weighted_counts


def _get_result_channel() -> str:
    mode_simulator = os.getenv("SIMULATOR", "false").lower() == "true"
    if mode_simulator:
        return "new_result_simulate"
    return os.getenv("RESULT_CHANNEL", "new_result")


def _recent_hot_overlap(
    suggestion: list[int],
    numbers: list[int],
    hot_window: int,
    hot_top: int,
) -> tuple[int, int, float, list[int]]:
    if not suggestion:
        return 0, 0, 0.0, []
    recent_window = numbers[:hot_window]
    recent_counts = Counter(recent_window)
    top_numbers = [n for n, _ in recent_counts.most_common(hot_top)]
    overlap = len(set(suggestion) & set(top_numbers))
    ratio = overlap / len(suggestion) if suggestion else 0.0
    return overlap, len(suggestion), ratio, top_numbers


async def _persist_pattern_stats(client, slug: str, pattern_scores: dict[str, dict[str, float]]) -> None:
    if not pattern_scores:
        return
    key = f"ranked:pattern_stats:{slug}"
    mapping = {}
    for name, stats in pattern_scores.items():
        payload = {
            "short_hits": stats["short_hits"],
            "short_total": stats["short_total"],
            "short_rate": stats["short_rate"],
            "long_hits": stats["long_hits"],
            "long_total": stats["long_total"],
            "long_rate": stats["long_rate"],
            "weight": stats["weight"],
        }
        mapping[name] = json.dumps(payload)
    await client.hset(key, mapping=mapping)


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
    idle_ticks = 0

    _log_info(f"Iniciado para {args.slug}")
    _log_info(f"Canal: {channel} | patterns: {len(funcs)} | every: {args.every}")
    _log_info(f"History inicial: {len(history)}")

    try:
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0
            )
            if message is None:
                await asyncio.sleep(0.05)
                idle_ticks += 1
                if idle_ticks % 200 == 0:
                    _log_info("Aguardando resultados...")
                continue
            idle_ticks = 0

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

            _log_info(f"Recebido numero: {number}")
            history.insert(0, number)
            if len(history) > args.limit:
                history = history[: args.limit]

            since_last_rank += 1

            if since_last_rank >= args.every:
                (
                    current_suggestion,
                    with_signals,
                    pattern_numbers,
                    pattern_scores,
                    weighted_counts,
                ) = _rank_from_patterns(
                    roulette,
                    history,
                    funcs,
                    args.top,
                    args.short_window,
                    args.long_window,
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
                penalty_reasons = _penalty_reasons(last_three)
                penalty = _penalty_factor(penalty_reasons)

                previous_ten = history[1:11]
                score_hits = len(set(current_suggestion) & set(previous_ten))
                if score_hits < args.min_score_hits:
                    continue

                overlap, total, overlap_ratio, _ = _recent_hot_overlap(
                    current_suggestion,
                    history,
                    args.hot_window,
                    args.hot_top,
                )
                quality = overlap_ratio * penalty
                if quality < args.hot_threshold:
                    print(
                        "Sugestao ignorada (hot abaixo do minimo) | overlap %d/%d (%.1f%%) | penalty %.2f | ultimos 3: %s"
                        % (
                            overlap,
                            total,
                            overlap_ratio * 100,
                            penalty,
                            ", ".join(str(n) for n in last_three),
                        )
                    )
                    continue

                if with_signals < args.min_patterns:
                    continue

                await _persist_pattern_stats(client, args.slug, pattern_scores)

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

                if penalty_reasons:
                    print("Penalidades: %s" % ", ".join(penalty_reasons))

                if pattern_numbers:
                    print("Patterns:")
                    for name, nums in pattern_numbers.items():
                        stats = pattern_scores.get(name, {})
                        short_hits = stats.get("short_hits", 0)
                        short_total = stats.get("short_total", 0)
                        short_rate = stats.get("short_rate", 0.0)
                        long_hits = stats.get("long_hits", 0)
                        long_total = stats.get("long_total", 0)
                        long_rate = stats.get("long_rate", 0.0)
                        weight = stats.get("weight", 0.0)
                        print(
                            " - %s: %s | short %d/%d (%.1f%%) | long %d/%d (%.1f%%) | w=%.2f"
                            % (
                                name,
                                ", ".join(str(n) for n in nums),
                                short_hits,
                                short_total,
                                short_rate * 100,
                                long_hits,
                                long_total,
                                long_rate * 100,
                                weight,
                            )
                        )
    finally:
        await pubsub.unsubscribe(channel)
        await client.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gera sugestao com pesos por pattern e filtros de qualidade."
    )
    parser.add_argument("slug", help="Slug da roleta (ex: pragmatic-auto-roulette)")
    parser.add_argument("--limit", type=int, default=500, help="Historico base (default: 500)")
    parser.add_argument("--top", type=int, default=12, help="Quantidade de numeros (default: 12)")
    parser.add_argument("--every", type=int, default=3, help="Atualiza sugestao a cada N numeros")
    parser.add_argument("--debug", action="store_true", help="Habilita logs de debug")
    parser.add_argument("--hot-window", type=int, default=200, help="Janela de hot numbers")
    parser.add_argument("--hot-top", type=int, default=15, help="Top hot numbers fixo")
    parser.add_argument("--hot-threshold", type=float, default=0.6, help="Minimo de overlap com hot")
    parser.add_argument("--short-window", type=int, default=50, help="Janela curta para score do pattern")
    parser.add_argument("--long-window", type=int, default=200, help="Janela longa para score do pattern")
    parser.add_argument("--min-score-hits", type=int, default=4, help="Minimo de acertos nos ultimos 10")
    parser.add_argument("--min-patterns", type=int, default=1, help="Minimo de patterns ativos")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.ERROR)
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
