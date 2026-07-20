from __future__ import annotations

import argparse
import json
from pathlib import Path

from shared.python.roulette.orbit.orbit_builder import OrbitBuilder

from .ablation import run_relation_ablations
from .artifacts import atomic_write_json, orbit_data_dir
from .config import load_engine_settings
from .dataset import chronological_split, iter_replay_decisions, load_records
from .evaluation import comparison_report
from .snapshot import create_mongo_snapshot
from .training import train_evaluate_models


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Motor orbital: snapshot, replay e ablacacao.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot = subparsers.add_parser("snapshot", help="Cria snapshot imutavel do MongoDB.")
    snapshot.add_argument("roulette_ids", nargs="+", help="IDs das roletas")
    snapshot.add_argument("--output-dir", type=Path)
    snapshot.add_argument(
        "--maximum-records",
        type=int,
        help="Limita cada mesa aos registros mais recentes (util para validacao rapida).",
    )

    replay = subparsers.add_parser("replay", help="Compara motor orbital com baselines.")
    replay.add_argument("snapshot", type=Path)
    replay.add_argument("--horizon", type=int, default=3)
    replay.add_argument("--warmup", type=int, default=300)
    replay.add_argument("--maximum", type=int, default=5000)
    replay.add_argument("--output", type=Path)

    ablation = subparsers.add_parser("ablation", help="Remove uma relacao por vez.")
    ablation.add_argument("snapshot", type=Path)
    ablation.add_argument("--horizon", type=int, default=3)
    ablation.add_argument("--warmup", type=int, default=300)
    ablation.add_argument("--maximum", type=int, default=2000)
    ablation.add_argument("--output", type=Path)

    train = subparsers.add_parser("train", help="Treina ranker e sobrevivencia por blocos temporais.")
    train.add_argument("snapshot", type=Path)
    train.add_argument("--horizon", type=int, default=3)
    train.add_argument("--warmup", type=int, default=300)
    train.add_argument("--max-train", type=int, default=20_000)
    train.add_argument("--max-validation", type=int, default=5_000)
    train.add_argument("--max-test", type=int, default=5_000)
    train.add_argument("--artifact-dir", type=Path)
    return parser


def _builder() -> OrbitBuilder:
    settings = load_engine_settings()
    return OrbitBuilder(
        pre_window=settings.pre_window,
        post_window=settings.post_window,
        memory_occurrences=settings.memory_occurrences,
    )


def main() -> None:
    args = _parser().parse_args()
    if args.command == "snapshot":
        result = create_mongo_snapshot(
            args.roulette_ids,
            output_dir=args.output_dir,
            maximum_records=args.maximum_records,
        )
    else:
        records = load_records(args.snapshot)
        builder = _builder()
        split = chronological_split(len(records))

        if args.command == "train":
            artifact_dir = args.artifact_dir or (
                orbit_data_dir() / "orbit-artifacts" / args.snapshot.stem
            )
            result = train_evaluate_models(
                records,
                builder=builder,
                split=split,
                artifact_dir=artifact_dir,
                horizon=args.horizon,
                warmup=args.warmup,
                max_train=args.max_train,
                max_validation=args.max_validation,
                max_test=args.max_test,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return

        def decisions_factory():
            return iter_replay_decisions(
                records,
                builder=builder,
                horizon=args.horizon,
                warmup=args.warmup,
                anchor_start=split.validation_end,
            )

        def calibration_decisions_factory():
            return iter_replay_decisions(
                records,
                builder=builder,
                horizon=args.horizon,
                warmup=args.warmup,
                anchor_start=split.train_end,
                anchor_end=split.validation_end - args.horizon,
            )

        values = tuple(record.value for record in records)
        if args.command == "replay":
            result = comparison_report(
                values,
                decisions_factory,
                horizon=args.horizon,
                maximum=args.maximum,
                training_end=split.train_end,
                calibration_decisions_factory=calibration_decisions_factory,
            )
        else:
            result = run_relation_ablations(
                decisions_factory,
                horizon=args.horizon,
                maximum=args.maximum,
            )
        output = args.output or (
            orbit_data_dir() / "reports" / f"{args.command}-{args.snapshot.stem}.json"
        )
        result = {
            **result,
            "split": {
                "train_end": split.train_end,
                "validation_end": split.validation_end,
                "total": split.total,
                "evaluation_block": "test",
            },
            "report_path": str(output),
        }
        atomic_write_json(output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
