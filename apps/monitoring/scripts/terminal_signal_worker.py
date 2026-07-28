#!/usr/bin/env python3
"""Entrypoint parametrizado para uma variação dos sinais de terminais."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.monitoring.terminal_signals.runtime import TerminalSignalWorker


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    variant = os.getenv("TERMINAL_SIGNAL_VARIANT", "").strip()
    if not variant:
        raise RuntimeError("TERMINAL_SIGNAL_VARIANT é obrigatório")
    worker = TerminalSignalWorker(
        variant_slug=variant,
        roulette_ids_raw=os.getenv("TERMINAL_SIGNAL_ROULETTE_IDS", "all"),
        result_channel=os.getenv("RESULT_CHANNEL", "new_result"),
        history_limit=int(os.getenv("TERMINAL_SIGNAL_HISTORY_LIMIT", "500")),
        reconcile_seconds=float(os.getenv("TERMINAL_SIGNAL_RECONCILE_SECONDS", "5")),
        discovery_seconds=float(os.getenv("TERMINAL_SIGNAL_DISCOVERY_SECONDS", "60")),
        max_batch=int(os.getenv("TERMINAL_SIGNAL_MAX_BATCH", "2000")),
        max_attempts=int(os.getenv("TERMINAL_SIGNAL_MAX_ATTEMPTS", "10")),
    )
    worker.run_forever()


if __name__ == "__main__":
    main()
