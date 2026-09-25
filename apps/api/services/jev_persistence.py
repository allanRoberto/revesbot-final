"""Private JSON audit records for completed Jev analyses."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any


def _write_record(record: dict[str, Any], results_dir: str) -> Path:
    directory = Path(results_dir).expanduser()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    filename = f"{record['analysis_id']}.json"
    destination = directory / filename
    temporary = directory / f".{filename}.tmp"
    serialized = json.dumps(
        record,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    )
    with temporary.open("w", encoding="utf-8") as handle:
        os.chmod(temporary, 0o600)
        handle.write(serialized)
        handle.write("\n")
    os.replace(temporary, destination)
    return destination


async def persist_analysis(record: dict[str, Any], results_dir: str) -> Path:
    return await asyncio.to_thread(_write_record, record, results_dir)
