from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
APPS_ROOT = REPO_ROOT / "apps"
if str(APPS_ROOT) not in sys.path:
    sys.path.insert(0, str(APPS_ROOT))

from api.services.pattern_score_live_service import backfill_pattern_scores_from_snapshots  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Pontua padrões a partir de snapshots resolvidos e gera multiplicadores dinâmicos.",
    )
    parser.add_argument(
        "--roulette-id",
        required=True,
        help="Slug da roleta, ex: pragmatic-brazilian-roulette.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Quantidade máxima de snapshots recentes para processar.",
    )
    parser.add_argument(
        "--config-key",
        default="",
        help="Opcional: processa apenas snapshots de um config_key específico.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Grava eventos e estado no Mongo. Sem esta flag roda apenas simulação.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Apaga scores/eventos existentes da roleta antes de reprocessar. Só tem efeito com --apply.",
    )
    return parser


async def _main() -> None:
    args = _build_parser().parse_args()
    result = await backfill_pattern_scores_from_snapshots(
        roulette_id=str(args.roulette_id),
        limit=int(args.limit),
        config_key=str(args.config_key or "").strip() or None,
        reset=bool(args.reset),
        dry_run=not bool(args.apply),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(_main())
