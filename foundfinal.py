#!/usr/bin/env python3
import asyncio
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
for candidate in (REPO_ROOT, REPO_ROOT / "apps"):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from apps.monitoring.foundfinal import run_worker  # noqa: E402


if __name__ == "__main__":
    asyncio.run(run_worker())
