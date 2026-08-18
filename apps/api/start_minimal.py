import os
import sys
from pathlib import Path

import uvicorn


CURRENT_DIR = Path(__file__).resolve().parent
APPS_ROOT = CURRENT_DIR.parent
REPO_ROOT = APPS_ROOT.parent

for import_root in (REPO_ROOT, APPS_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))


if __name__ == "__main__":
    uvicorn.run(
        "api.minimal_main:app",
        host="127.0.0.1",
        port=int(os.environ.get("API_PORT", os.environ.get("PORT", "8082"))),
        workers=max(1, int(os.environ.get("API_WORKERS", "2"))),
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
    )
