from __future__ import annotations

import logging
import threading


def start_retention_worker(repository, limit: int, interval_seconds: int) -> threading.Thread | None:
    if limit <= 0:
        return None
    logger = logging.getLogger("collector.retention")

    def run() -> None:
        while True:
            if stop.wait(interval_seconds):
                return
            try:
                removed = repository.trim(limit)
                if removed:
                    logger.info("retention_removed_documents=%s", removed)
            except Exception:
                logger.exception("retention_failed")

    stop = threading.Event()
    thread = threading.Thread(target=run, name="collector-retention", daemon=True)
    thread.start()
    return thread
