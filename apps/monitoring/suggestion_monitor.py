#!/usr/bin/env python3
import asyncio
import logging
import sys
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parent
REPO_ROOT = APP_ROOT.parent.parent
APPS_ROOT = REPO_ROOT / "apps"

for candidate in (REPO_ROOT, APPS_ROOT, APP_ROOT):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

try:
    from apps.monitoring.src.suggestion_monitor_worker import main as suggestion_monitor_main
except ImportError:
    from src.suggestion_monitor_worker import main as suggestion_monitor_main


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    asyncio.run(suggestion_monitor_main())
