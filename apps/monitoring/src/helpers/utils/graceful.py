from pathlib import Path
import sys

for parent in Path(__file__).resolve().parents:
    shared_python = parent / "shared" / "python"
    if shared_python.exists():
        if str(shared_python) not in sys.path:
            sys.path.insert(0, str(shared_python))
        break

from utils.graceful import setup_graceful_shutdown  # noqa: E402

__all__ = ["setup_graceful_shutdown"]
