#!/usr/bin/env python3
import asyncio
import logging
import signal
import json
import os

from dotenv import load_dotenv

from core.api import RouletteAPI
from core.redis_connections import (
    get_async_results_redis_client,
    get_results_redis_url,
    get_signals_redis_url,
)
from helpers.roulettes_list import roulettes

roulette_lookup = {r["slug"]: r for r in roulettes} 

from patterns.run_all_patterns import run_all_patterns

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    filename="error-main.log",
    filemode="a"
)

signal.signal(signal.SIGPIPE, signal.SIG_DFL)

load_dotenv()

mode_simulator = os.getenv("SIMULATOR", "false").lower() == "true"

r = get_async_results_redis_client(decode_responses=True)

if mode_simulator:
    channel = os.getenv("RESULT_CHANNEL", "new_result_simulate")
else:
    channel = os.getenv("RESULT_CHANNEL", "new_result")


def _safe_redis_url(url: str) -> str:
    if "@" not in url:
        return url
    _head, tail = url.split("@", 1)
    return "***@" + tail

# Armazenamento temporário de histórico por roleta
results_by_slug = {}
active_pattern_tasks = 0
_invalid_event_counts: dict[str, int] = {}


def _warn_invalid_event(reason: str) -> None:
    count = _invalid_event_counts.get(reason, 0) + 1
    _invalid_event_counts[reason] = count
    # Loga sempre nas primeiras ocorrências e depois de forma amostrada.
    if count <= 5 or count % 100 == 0:
        logging.warning("[redis:%s] evento descartado (%s)", channel, reason)


def _coerce_int_safe(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text and (text.isdigit() or (text.startswith("-") and text[1:].isdigit())):
            try:
                return int(text)
            except ValueError:
                return None
    return None


def _normalize_result_event(raw_data):
    if isinstance(raw_data, (bytes, bytearray)):
        try:
            raw_data = raw_data.decode("utf-8")
        except Exception:
            _warn_invalid_event("payload_bytes_invalido")
            return None

    try:
        data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
    except json.JSONDecodeError:
        _warn_invalid_event("json_invalido")
        return None

    if not isinstance(data, dict):
        _warn_invalid_event("payload_nao_dict")
        return None

    slug = data.get("slug") or data.get("roulette_id")
    if not isinstance(slug, str) or not slug.strip():
        _warn_invalid_event("slug_ausente")
        return None
    slug = slug.strip()

    raw_result = data.get("result")
    if raw_result is None:
        raw_result = data.get("value", data.get("number"))

    result = _coerce_int_safe(raw_result)
    if result is None:
        _warn_invalid_event("result_invalido")
        return None

    return {
        "slug": slug,
        "result": result,
        "full_result": data.get("full_result"),
    }

async def _run_patterns_task(roulette, numbers, full_results):
    global active_pattern_tasks
    loop = asyncio.get_running_loop()
    active_pattern_tasks += 1
    t0 = loop.time()
    try:
        await loop.run_in_executor(None, run_all_patterns, roulette, numbers, full_results)
    finally:
        t1 = loop.time()
        if t1 - t0 > 0.2:
            logging.warning("[%s] run_all_patterns demorou %.3fs", roulette["slug"], t1 - t0)
        active_pattern_tasks -= 1


def _log_backlog(slug: str, count: int) -> None:
    if count % 50 == 0:
        logging.info("[%s] backlog tasks ativas: %d", slug, active_pattern_tasks)

async def process_roulette(slug: str, api: RouletteAPI):
    try:
        if mode_simulator:
            num_results = 500
            results_by_slug[slug] = {"numbers": [], "full": []}
            return
        else:
            num_results = 500

        resp = await api.api(slug, num_results)
        if resp and "results" in resp:
            # Extrair apenas os números
            numbers = [r["value"] if isinstance(r, dict) else r for r in resp["results"]]
            
            # Guardar ambos
            results_by_slug[slug] = {
                "numbers": numbers,
                "full": resp["results"]
            }
            
            roulette = roulette_lookup.get(slug)
            if roulette:
                asyncio.create_task(_run_patterns_task(roulette, numbers, resp["results"]))

    except Exception as e:
        print(f"Erro ao inicializar histórico da roleta {slug}: {e}")
        logging.exception(f"Erro inicial: {slug}")

async def listen_results(api: RouletteAPI):
    pubsub = r.pubsub()
    await pubsub.subscribe(channel)
    print("Aguardando novos resultados de roletas via WebSocket...")
    processed_count = 0
    
    while True:
        try:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)

            if message is None:
                await asyncio.sleep(0.1)
                continue
            
            normalized = _normalize_result_event(message.get("data"))
            if not normalized:
                continue
            slug = normalized["slug"]
            
            # Extrair número e objeto completo
            new_result_obj = normalized["full_result"]  # Objeto completo
            new_result_num = normalized["result"]       # Apenas número
            
            if slug in results_by_slug:
                # Atualizar números
                current_numbers = results_by_slug[slug]["numbers"]
                current_numbers = [new_result_num] + current_numbers
                current_numbers = current_numbers[:500]
                
                # Atualizar objetos completos
                current_full = results_by_slug[slug]["full"]
                if new_result_obj is not None:
                    current_full = [new_result_obj] + current_full
                    current_full = current_full[:500]
                
                results_by_slug[slug] = {
                    "numbers": current_numbers,
                    "full": current_full
                }

                roulette = roulette_lookup.get(slug)
                if roulette:
                    if len(current_numbers) < 1:
                        continue
                    else:
                        processed_count += 1
                        _log_backlog(slug, processed_count)
                        asyncio.create_task(
                            _run_patterns_task(roulette, current_numbers, current_full)
                        )

            else:
                # Se ainda não temos histórico, inicializar agora
                await process_roulette(slug, api)
                # Reaplica o resultado atual para nao perder o spin
                current_numbers = results_by_slug.get(slug, {}).get("numbers", [])
                current_full = results_by_slug.get(slug, {}).get("full", [])

                current_numbers = [new_result_num] + current_numbers
                current_numbers = current_numbers[:500]

                if new_result_obj is not None:
                    current_full = [new_result_obj] + current_full
                    current_full = current_full[:500]

                results_by_slug[slug] = {
                    "numbers": current_numbers,
                    "full": current_full,
                }

                roulette = roulette_lookup.get(slug)
                if roulette and current_numbers:
                    processed_count += 1
                    _log_backlog(slug, processed_count)
                    asyncio.create_task(
                        _run_patterns_task(roulette, current_numbers, current_full)
                    )

        except Exception as e:
            print(f"Erro durante processamento do resultado novo: {e}")
            logging.exception("Erro no listener")

async def main():
    print(
        "Iniciando bot com histórico + WebSocket "
        f"MODO SIMULADOR ATIVADO: {mode_simulator} "
        f"canal={channel} "
        f"redis_sinais={_safe_redis_url(get_signals_redis_url())} "
        f"redis_resultados={_safe_redis_url(get_results_redis_url())}"
    )

    api = RouletteAPI()
    await asyncio.gather(*[process_roulette(r["slug"], api) for r in roulettes])
    await listen_results(api)

if __name__ == "__main__":
    asyncio.run(main())
