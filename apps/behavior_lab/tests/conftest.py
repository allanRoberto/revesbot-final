from __future__ import annotations

import sys
from pathlib import Path


APPS_ROOT = Path(__file__).resolve().parents[2]
if str(APPS_ROOT) not in sys.path:
    sys.path.insert(0, str(APPS_ROOT))
