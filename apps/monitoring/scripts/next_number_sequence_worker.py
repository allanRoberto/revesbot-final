from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
APPS_ROOT = REPO_ROOT / "apps"
if str(APPS_ROOT) not in sys.path:
    sys.path.insert(0, str(APPS_ROOT))

from api.services.next_number_ranking_service import DEFAULT_ROULETTE_ID  # noqa: E402
from api.services.next_number_sequence_service import refresh_next_number_sequences  # noqa: E402


logger = logging.getLogger("next_number_sequence_worker")

DEFAULT_INTERVAL_SECONDS = 600
DEFAULT_LOG_PATH = REPO_ROOT / "apps" / "monitoring" / "Logs" / "next_number_sequence_worker.log"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int) -> int:
    raw = os.getenv(name)
    try:
        value = int(str(raw).strip()) if raw is not None else default
    except ValueError:
        value = default
    return max(minimum, value)


def _configure_logging() -> None:
    log_level = (os.getenv("NEXT_NUMBER_SEQUENCE_LOG_LEVEL") or "INFO").upper()
    log_path = Path(os.getenv("NEXT_NUMBER_SEQUENCE_LOG_PATH") or DEFAULT_LOG_PATH)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    logger.setLevel(getattr(logging, log_level, logging.INFO))
    logger.handlers.clear()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger.propagate = False


async def _run_cycle(roulette_id: str) -> None:
    started_at = time.perf_counter()
    doc = await refresh_next_number_sequences(
        roulette_id=roulette_id,
        source="worker",
    )
    elapsed_ms = (time.perf_counter() - started_at) * 1000.0
    logger.info(
        "Catalogacao de sequencias atualizada | roulette=%s | catalog_count=%s | updated_at=%s | elapsed_ms=%.1f",
        doc.get("roulette_id"),
        doc.get("catalog_count"),
        doc.get("updated_at_utc"),
        elapsed_ms,
    )


async def run_worker(*, once: bool = False) -> None:
    if not _env_bool("NEXT_NUMBER_SEQUENCE_ENABLED", True):
        logger.warning("Worker de catalogacao de sequencias desabilitado por configuracao.")
        return

    roulette_id = (
        os.getenv("NEXT_NUMBER_SEQUENCE_ROULETTE_ID")
        or os.getenv("NEXT_NUMBER_SEQUENCE_ROULETTE")
        or DEFAULT_ROULETTE_ID
    ).strip() or DEFAULT_ROULETTE_ID
    interval_seconds = _env_int(
        "NEXT_NUMBER_SEQUENCE_INTERVAL_SECONDS",
        DEFAULT_INTERVAL_SECONDS,
        60,
    )

    logger.info(
        "Iniciando worker de catalogacao de sequencias | roulette=%s | interval=%ss | once=%s",
        roulette_id,
        interval_seconds,
        once,
    )

    while True:
        try:
            await _run_cycle(roulette_id)
        except Exception as exc:
            logger.exception("Falha ao atualizar catalogacao de sequencias para %s: %s", roulette_id, exc)

        if once:
            return
        await asyncio.sleep(interval_seconds)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Atualiza catalogacao de proximos 5 numeros por ocorrencia.")
    parser.add_argument("--once", action="store_true", help="Executa um ciclo e encerra.")
    return parser.parse_args()


def main() -> None:
    _configure_logging()
    args = _parse_args()
    asyncio.run(run_worker(once=bool(args.once)))


if __name__ == "__main__":
    main()
