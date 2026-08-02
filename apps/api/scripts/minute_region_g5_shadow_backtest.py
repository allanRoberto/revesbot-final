#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from bisect import bisect_left, bisect_right
from datetime import timedelta, timezone
from math import sqrt
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[3] if len(SCRIPT_PATH.parents) > 3 else Path.cwd()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.monitoring.src.minute_region_signal_runtime import (  # noqa: E402
    build_alternative_analysis,
    region_numbers,
)
from apps.monitoring.src.mongo import mongo_db  # noqa: E402


TRAINING_DAYS = 10
WINDOW_SECONDS = 3 * 60
ANALYSIS_NEIGHBORS = 3
CENTERS_COUNT = 2
ATTEMPT_HORIZON = 5


def _as_utc(value):
    return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(
        timezone.utc
    )


def _wilson_low(hits: int, signals: int) -> float:
    if signals <= 0:
        return 0.0
    probability = hits / signals
    z_score = 1.96
    denominator = 1 + z_score * z_score / signals
    center = (
        probability + z_score * z_score / (2 * signals)
    ) / denominator
    margin = (
        z_score
        * sqrt(
            probability * (1 - probability) / signals
            + z_score * z_score / (4 * signals * signals)
        )
        / denominator
    )
    return max(0.0, center - margin) * 100


def _empty_metrics() -> dict:
    return {
        "signals": 0,
        "hits": 0,
        "coverage_sum": 0,
        "expected_random_hits_sum": 0.0,
        "first_hits": [0] * ATTEMPT_HORIZON,
    }


def _add(metrics: dict, targets: set[int], attempts: list[int]) -> None:
    metrics["signals"] += 1
    metrics["coverage_sum"] += len(targets)
    metrics["expected_random_hits_sum"] += 1 - (
        1 - len(targets) / 37
    ) ** ATTEMPT_HORIZON
    first_hit = next(
        (
            index
            for index, value in enumerate(
                attempts[:ATTEMPT_HORIZON], 1
            )
            if value in targets
        ),
        None,
    )
    if first_hit is not None:
        metrics["hits"] += 1
        metrics["first_hits"][first_hit - 1] += 1


def _serialize(metrics: dict) -> dict:
    signals = int(metrics["signals"])
    hits = int(metrics["hits"])
    cumulative_hits = 0
    attempt_rows = []
    for attempt, exact_hits in enumerate(metrics["first_hits"], 1):
        cumulative_hits += exact_hits
        attempt_rows.append(
            {
                "attempt": attempt,
                "exact_hits": exact_hits,
                "exact_accuracy": round(
                    exact_hits / max(1, signals) * 100, 2
                ),
                "cumulative_hits": cumulative_hits,
                "cumulative_accuracy": round(
                    cumulative_hits / max(1, signals) * 100, 2
                ),
            }
        )
    return {
        "signals": signals,
        "hits": hits,
        "accuracy": round(hits / max(1, signals) * 100, 2),
        "wilson_low_95": round(_wilson_low(hits, signals), 2),
        "retention": 100.0 if signals else 0.0,
        "average_coverage": round(
            metrics["coverage_sum"] / max(1, signals), 2
        ),
        "expected_random_accuracy": round(
            metrics["expected_random_hits_sum"] / max(1, signals) * 100,
            2,
        ),
        "attempt_accuracy": attempt_rows,
    }


def _run(*, roulette_id: str, days: int, step_minutes: int) -> dict:
    history = mongo_db["history"]
    latest_doc = history.find_one(
        {"roulette_id": roulette_id},
        {"timestamp": 1},
        sort=[("timestamp", -1)],
    )
    earliest_doc = history.find_one(
        {"roulette_id": roulette_id},
        {"timestamp": 1},
        sort=[("timestamp", 1)],
    )
    if not latest_doc or not earliest_doc:
        raise RuntimeError(f"Sem histórico para {roulette_id}.")

    latest = _as_utc(latest_doc["timestamp"])
    earliest = _as_utc(earliest_doc["timestamp"])
    evaluation_end = latest.replace(second=0, microsecond=0) - timedelta(
        minutes=5
    )
    evaluation_start = max(
        earliest + timedelta(days=TRAINING_DAYS),
        evaluation_end - timedelta(days=max(1, days)),
    ).replace(second=0, microsecond=0)
    fetch_start = evaluation_start - timedelta(
        days=TRAINING_DAYS, minutes=4
    )
    docs = list(
        history.find(
            {
                "roulette_id": roulette_id,
                "timestamp": {"$gte": fetch_start, "$lte": latest},
            },
            {"timestamp": 1, "value": 1},
        ).sort([("timestamp", 1), ("_id", 1)])
    )
    timestamps = [_as_utc(item["timestamp"]).timestamp() for item in docs]
    values = [int(item["value"]) for item in docs]
    centers_by_value = {
        value: {
            center
            for center in range(37)
            if value in set(region_numbers(center, ANALYSIS_NEIGHBORS))
        }
        for value in range(37)
    }

    def rankings_for(signal_minute):
        hit_days = [0] * 37
        total_matches = [0] * 37
        for day_offset in range(1, TRAINING_DAYS + 1):
            target_epoch = (
                signal_minute - timedelta(days=day_offset)
            ).timestamp()
            start = bisect_left(
                timestamps, target_epoch - WINDOW_SECONDS
            )
            end = bisect_right(
                timestamps, target_epoch + WINDOW_SECONDS
            )
            day_centers = set()
            for value in values[start:end]:
                centers = centers_by_value[value]
                day_centers.update(centers)
                for center in centers:
                    total_matches[center] += 1
            for center in day_centers:
                hit_days[center] += 1
        rankings = [
            {
                "center": center,
                "hit_days": hit_days[center],
                "total_days": TRAINING_DAYS,
                "hit_rate": round(hit_days[center] / TRAINING_DAYS, 4),
                "total_matches": total_matches[center],
            }
            for center in range(37)
        ]
        rankings.sort(
            key=lambda item: (
                -item["hit_days"],
                -item["total_matches"],
                item["center"],
            )
        )
        return rankings

    def scenario_targets(rankings, neighbors: int) -> set[int]:
        selected = rankings[:CENTERS_COUNT]
        targets = set()
        for item in selected:
            targets.update(region_numbers(item["center"], neighbors))
        alternative = build_alternative_analysis(
            rankings,
            selected,
            bet_neighbors=neighbors,
        )
        targets.update(alternative.get("alternative_bet_values", []))
        return targets

    metrics = {neighbors: _empty_metrics() for neighbors in (3, 4, 5)}
    minute = evaluation_start
    while minute <= evaluation_end:
        attempt_start = bisect_right(timestamps, minute.timestamp())
        attempts = values[attempt_start : attempt_start + 10]
        if len(attempts) < 10:
            break
        rankings = rankings_for(minute)
        for neighbors in metrics:
            _add(
                metrics[neighbors],
                scenario_targets(rankings, neighbors),
                attempts,
            )
        minute += timedelta(minutes=max(1, step_minutes))

    return {
        "config": {
            "roulette_id": roulette_id,
            "evaluation_start_utc": evaluation_start.isoformat(),
            "evaluation_end_utc": evaluation_end.isoformat(),
            "days": days,
            "step_minutes": step_minutes,
            "training_days": TRAINING_DAYS,
            "window_minutes": 3,
            "analysis_neighbors": ANALYSIS_NEIGHBORS,
            "centers_count": CENTERS_COUNT,
            "attempt_horizon": ATTEMPT_HORIZON,
            "alternative_recalculated_per_scenario": True,
        },
        "scenarios": {
            f"neighbors_{neighbors}": _serialize(result)
            for neighbors, result in metrics.items()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backtest cronológico do modo sombra G5 por quantidade de vizinhos."
    )
    parser.add_argument(
        "--roulette-id", default="pragmatic-auto-roulette"
    )
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--step-minutes", type=int, default=1)
    args = parser.parse_args()
    print(
        json.dumps(
            _run(
                roulette_id=args.roulette_id,
                days=max(1, args.days),
                step_minutes=max(1, args.step_minutes),
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
