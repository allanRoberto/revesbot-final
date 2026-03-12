import os
import sys
from pathlib import Path

import uvicorn


CURRENT_DIR = Path(__file__).resolve().parent
APPS_ROOT = CURRENT_DIR.parent

# Garante que "api" seja importável a partir de apps/api após o move para apps/.
if str(APPS_ROOT) not in sys.path:
    sys.path.insert(0, str(APPS_ROOT))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))  # App Engine define essa variável
    uvicorn.run("api.main:app", host="0.0.0.0", port=port)
