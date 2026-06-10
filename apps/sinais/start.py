import os
import sys
from pathlib import Path

import uvicorn

CURRENT_DIR = Path(__file__).resolve().parent
APPS_ROOT = CURRENT_DIR.parent

# Garante que "sinais" seja importável a partir de apps/.
if str(APPS_ROOT) not in sys.path:
    sys.path.insert(0, str(APPS_ROOT))

if __name__ == "__main__":
    port = int(os.environ.get("PORT") or os.environ.get("SINAIS_PORT", "8090"))
    workers = max(1, int(os.environ.get("SINAIS_WORKERS", "1") or "1"))
    uvicorn.run("sinais.main:app", host="0.0.0.0", port=port, workers=workers)
