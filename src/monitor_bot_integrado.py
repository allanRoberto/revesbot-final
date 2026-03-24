"""Compat wrapper for the legacy integrated monitor script."""

from pathlib import Path
import runpy
import sys


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


if __name__ == "__main__":
    runpy.run_module(
        "apps.monitoring.scripts.monitor_bot_integrado",
        run_name="__main__",
    )
else:
    from apps.monitoring.scripts.monitor_bot_integrado import *  # noqa: F401,F403
