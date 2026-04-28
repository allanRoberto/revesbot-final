#!/usr/bin/env python3
import asyncio
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
    from apps.monitoring.src.signal_listener import main as signal_listener_main
except ImportError:
    from src.signal_listener import main as signal_listener_main


if __name__ == "__main__":
    asyncio.run(signal_listener_main())
