from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    # PM2 executes this file directly; expose /apps as a package root.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from behavior_lab.backtest import replay
from behavior_lab.config import load_config
from behavior_lab.source_api import ResultAPIClient
from behavior_lab.worker import run_worker


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Independent roulette behavior lab")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("worker", help="consume live results and maintain Redis state")

    backtest = subparsers.add_parser("backtest", help="run a causal replay")
    source = backtest.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path, help="JSON array or {items/results: [...]} file")
    source.add_argument("--api", action="store_true", help="read production history API")
    backtest.add_argument("--limit", type=int, default=2_000)
    backtest.add_argument(
        "--input-order",
        choices=("chronological", "oldest-first", "newest-first"),
        default=None,
    )
    backtest.add_argument("--output", type=Path)
    backtest.add_argument("--compact", action="store_true")
    return parser


def _file_events(path: Path) -> list[Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict):
        payload = payload.get("items", payload.get("results"))
    if not isinstance(payload, list):
        raise ValueError("arquivo deve conter uma lista ou objeto items/results")
    return payload


async def _backtest_from_api(limit: int) -> list[Any]:
    config = load_config()
    client = ResultAPIClient(
        base_url=os.getenv("BEHAVIOR_LAB_API_BASE_URL", "https://api.revesbot.com.br"),
        roulette_id=config.roulette_id,
    )
    return [spin.as_dict() for spin in await client.fetch_history(limit)]


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, os.getenv("BEHAVIOR_LAB_LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if args.command == "worker":
        try:
            asyncio.run(run_worker())
        except KeyboardInterrupt:
            return 130
        return 0

    config = load_config()
    if args.api:
        events = asyncio.run(_backtest_from_api(args.limit))
        input_order = args.input_order or "chronological"
    else:
        events = _file_events(args.file)
        input_order = args.input_order or "newest-first"
    report = replay(events, config=config, input_order=input_order)
    serialized = json.dumps(report, ensure_ascii=False, indent=None if args.compact else 2)
    if args.output:
        args.output.write_text(serialized + "\n", encoding="utf-8")
    else:
        print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
