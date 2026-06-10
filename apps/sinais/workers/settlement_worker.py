"""Worker de apuração: observa as próximas rodadas e debita/credita os créditos.

Roda em loop contínuo (pm2). A cada ciclo varre as entradas pendentes e apura
as que já têm `attempts` rodadas após a geração.
"""

import asyncio
import logging
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
APPS_ROOT = CURRENT_DIR.parent.parent  # apps/
if str(APPS_ROOT) not in sys.path:
    sys.path.insert(0, str(APPS_ROOT))

from sinais.core.config import settings  # noqa: E402
from sinais.core.db import ensure_indexes  # noqa: E402
from sinais.services.settlement import settle_pending_once  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger("settlement-worker")


async def main() -> None:
    await ensure_indexes()
    poll = settings.settlement_poll_seconds
    log.info("worker de apuração iniciado (poll=%ss)", poll)
    while True:
        try:
            n = await settle_pending_once()
            if n:
                log.info("apuradas %d entrada(s)", n)
        except Exception:
            log.exception("erro no ciclo de apuração")
        await asyncio.sleep(poll)


if __name__ == "__main__":
    asyncio.run(main())
