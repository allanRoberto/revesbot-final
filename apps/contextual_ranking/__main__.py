from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    # PM2 executes this file directly; expose /apps as a package root.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_ranking.worker import main

if __name__ == "__main__":
    main()
