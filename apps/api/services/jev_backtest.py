"""Paid, resumable historical evaluation of the original Jev number ranking."""
from __future__ import annotations

import asyncio
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from uuid import UUID

from api.services.jev_history_service import ROULETTE_SLUG, utc_iso
from api.services.jev_ranking import NEXT_SPIN_CHOICE_KEY, build_ranking_payload


BACKTEST_VERSION = "jev_original_ranking_v1"


class JevBacktestError(ValueError):
    pass


class JevBacktestNotFoundError(FileNotFoundError):
    pass


def required_history_size(history_points: int, context_numbers: int, attempts: int) -> int:
    """Return the exact snapshot size needed for all historical cutoffs."""
    return context_numbers + history_points + attempts - 1


def build_backtest_job(
    *,
    backtest_id: str,
    history: Sequence[int],
    history_points: int,
    context_numbers: int,
    chip_count: int,
    attempts: int,
    requested_model: str,
    created_at: str,
    history_fetched_at: str,
) -> dict[str, Any]:
    required = required_history_size(history_points, context_numbers, attempts)
    if len(history) != required:
        raise JevBacktestError(
            f"O snapshot deve conter exatamente {required} números; recebeu {len(history)}."
        )
    if any(
        isinstance(number, bool) or not isinstance(number, int) or not 0 <= number <= 36
        for number in history
    ):
        raise JevBacktestError("O snapshot contém números inválidos.")
    return {
        "backtest_id": backtest_id,
        "analysis_type": "jev_historical_backtest",
        "version": BACKTEST_VERSION,
        "status": "ready",
        "roulette_slug": ROULETTE_SLUG,
        "created_at": created_at,
        "updated_at": created_at,
        "completed_at": None,
        "requested_model": requested_model,
        "returned_models": [],
        "configuration": {
            "history_points": history_points,
            "context_numbers": context_numbers,
            "chip_count": chip_count,
            "attempts": attempts,
            "overlapping_windows": True,
            "ranking_source": "jev_next_spin_choice",
        },
        "source": {
            "history_order": "oldest_to_newest",
            "history_fetched_at": history_fetched_at,
            "snapshot_size": len(history),
        },
        "history_snapshot": list(history),
        "progress": {
            "total_calls": history_points,
            "next_step": 0,
            "attempted_calls": 0,
            "successful_calls": 0,
            "failed_calls": 0,
        },
        "metrics": {
            "hits": 0,
            "misses": 0,
            "accuracy": None,
            "hits_by_attempt": {str(index): 0 for index in range(1, attempts + 1)},
            "average_attempt_on_hit": None,
            "sum_attempts_on_hit": 0,
        },
        "usage": {
            "cost_usd": 0.0,
            "cost_reported_calls": 0,
            "input_tokens": 0,
            "input_tokens_reported_calls": 0,
            "average_cost_per_reported_call_usd": None,
            "projected_cost_per_1000_calls_usd": None,
            "average_input_tokens_per_reported_call": None,
        },
        "last_step": None,
        "last_error": None,
    }


def step_window(job: dict[str, Any], step: int) -> tuple[list[int], list[int]]:
    config = job["configuration"]
    context_numbers = int(config["context_numbers"])
    attempts = int(config["attempts"])
    total = int(config["history_points"])
    if step < 0 or step >= total:
        raise JevBacktestError("A etapa solicitada está fora do backtest.")
    snapshot = job.get("history_snapshot")
    if not isinstance(snapshot, list):
        raise JevBacktestError("O snapshot do backtest é inválido.")
    history = snapshot[step : step + context_numbers]
    future = snapshot[step + context_numbers : step + context_numbers + attempts]
    if len(history) != context_numbers or len(future) != attempts:
        raise JevBacktestError("O snapshot não contém contexto suficiente para esta etapa.")
    return history, future


def build_original_jev_step_payload(history: Sequence[int]) -> dict[str, Any]:
    """Build the production ranking state but ask only for Jev's original next-spin ranking."""
    ranking_payload = build_ranking_payload(history)
    question = ranking_payload["questions"][NEXT_SPIN_CHOICE_KEY]
    return {
        "state": ranking_payload["state"],
        "questions": {NEXT_SPIN_CHOICE_KEY: question},
    }


def select_chips(probabilities: dict[str, float], chip_count: int) -> list[int]:
    expected = {str(number) for number in range(37)}
    if set(probabilities) != expected:
        raise JevBacktestError("O ranking do Jev não contém os 37 números.")
    return [
        int(number)
        for number, _probability in sorted(
            probabilities.items(),
            key=lambda item: (-float(item[1]), int(item[0])),
        )[:chip_count]
    ]


def evaluate_step(
    selected_numbers: Sequence[int], future_numbers: Sequence[int]
) -> dict[str, Any]:
    selected = set(selected_numbers)
    first_hit_attempt = next(
        (index for index, number in enumerate(future_numbers, start=1) if number in selected),
        None,
    )
    return {
        "hit": first_hit_attempt is not None,
        "first_hit_attempt": first_hit_attempt,
        "hit_number": (
            future_numbers[first_hit_attempt - 1] if first_hit_attempt is not None else None
        ),
    }


def _usage_values(raw_response: dict[str, Any]) -> tuple[float | None, int | None]:
    usage = raw_response.get("usage")
    if not isinstance(usage, dict):
        return None, None
    raw_cost = usage.get("cost")
    cost = (
        float(raw_cost)
        if isinstance(raw_cost, (int, float))
        and not isinstance(raw_cost, bool)
        and math.isfinite(float(raw_cost))
        and float(raw_cost) >= 0
        else None
    )
    raw_tokens = usage.get("input_tokens")
    input_tokens = (
        int(raw_tokens)
        if isinstance(raw_tokens, int) and not isinstance(raw_tokens, bool) and raw_tokens >= 0
        else None
    )
    return cost, input_tokens


def record_success(
    job: dict[str, Any],
    *,
    step: int,
    selected_numbers: Sequence[int],
    future_numbers: Sequence[int],
    returned_model: str | None,
    latency_ms: int,
    raw_response: dict[str, Any],
) -> dict[str, Any]:
    progress = job["progress"]
    if step != int(progress["next_step"]):
        raise JevBacktestError("A etapa não corresponde ao próximo ponto pendente.")
    evaluation = evaluate_step(selected_numbers, future_numbers)
    cost, input_tokens = _usage_values(raw_response)
    step_record = {
        "step": step,
        "status": "success",
        "selected_numbers": list(selected_numbers),
        "future_numbers": list(future_numbers),
        **evaluation,
        "returned_model": returned_model,
        "latency_ms": latency_ms,
        "usage": {"cost_usd": cost, "input_tokens": input_tokens},
    }
    progress["next_step"] += 1
    progress["attempted_calls"] += 1
    progress["successful_calls"] += 1
    metrics = job["metrics"]
    if evaluation["hit"]:
        metrics["hits"] += 1
        attempt_key = str(evaluation["first_hit_attempt"])
        metrics["hits_by_attempt"][attempt_key] += 1
        metrics["sum_attempts_on_hit"] += evaluation["first_hit_attempt"]
    else:
        metrics["misses"] += 1
    resolved = metrics["hits"] + metrics["misses"]
    metrics["accuracy"] = metrics["hits"] / resolved if resolved else None
    metrics["average_attempt_on_hit"] = (
        metrics["sum_attempts_on_hit"] / metrics["hits"] if metrics["hits"] else None
    )
    usage = job["usage"]
    if cost is not None:
        usage["cost_usd"] = round(usage["cost_usd"] + cost, 12)
        usage["cost_reported_calls"] += 1
        average_cost = usage["cost_usd"] / usage["cost_reported_calls"]
        usage["average_cost_per_reported_call_usd"] = round(average_cost, 12)
        usage["projected_cost_per_1000_calls_usd"] = round(average_cost * 1000, 9)
    if input_tokens is not None:
        usage["input_tokens"] += input_tokens
        usage["input_tokens_reported_calls"] += 1
        usage["average_input_tokens_per_reported_call"] = (
            usage["input_tokens"] / usage["input_tokens_reported_calls"]
        )
    if returned_model and returned_model not in job["returned_models"]:
        job["returned_models"].append(returned_model)
    job["last_step"] = step_record
    job["last_error"] = None
    _advance_status(job)
    return step_record


def record_failure(job: dict[str, Any], *, step: int, code: str, message: str) -> dict[str, Any]:
    progress = job["progress"]
    if step != int(progress["next_step"]):
        raise JevBacktestError("A etapa não corresponde ao próximo ponto pendente.")
    step_record = {
        "step": step,
        "status": "failed",
        "error": {"code": code, "message": message},
    }
    progress["next_step"] += 1
    progress["attempted_calls"] += 1
    progress["failed_calls"] += 1
    job["last_step"] = step_record
    job["last_error"] = step_record["error"]
    job["status"] = "paused_error"
    job["updated_at"] = utc_iso(datetime.now(timezone.utc))
    if progress["next_step"] >= progress["total_calls"]:
        _advance_status(job)
    return step_record


def _advance_status(job: dict[str, Any]) -> None:
    progress = job["progress"]
    now = utc_iso(datetime.now(timezone.utc))
    if progress["next_step"] >= progress["total_calls"]:
        job["status"] = "completed_with_errors" if progress["failed_calls"] else "completed"
        job["completed_at"] = now
    else:
        job["status"] = "running"
    job["updated_at"] = now


def public_backtest(job: dict[str, Any], *, include_last_step: bool = True) -> dict[str, Any]:
    result = {
        key: value
        for key, value in job.items()
        if key != "history_snapshot" and (include_last_step or key != "last_step")
    }
    return result


def _canonical_uuid(value: Any) -> str:
    if not isinstance(value, str):
        raise JevBacktestError("backtest_id inválido.")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as exc:
        raise JevBacktestError("backtest_id inválido.") from exc
    if str(parsed) != value:
        raise JevBacktestError("backtest_id inválido.")
    return value


def _backtest_directory(results_dir: str) -> Path:
    return Path(results_dir).expanduser() / "backtests"


def _job_path(backtest_id: str, results_dir: str) -> Path:
    return _backtest_directory(results_dir) / f"{_canonical_uuid(backtest_id)}.json"


def _steps_path(backtest_id: str, results_dir: str) -> Path:
    return _backtest_directory(results_dir) / f"{_canonical_uuid(backtest_id)}.steps.jsonl"


def _write_job(job: dict[str, Any], results_dir: str) -> Path:
    directory = _backtest_directory(results_dir)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination = _job_path(job.get("backtest_id"), results_dir)
    temporary = destination.with_name(f".{destination.name}.tmp")
    serialized = json.dumps(job, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
    with temporary.open("w", encoding="utf-8") as handle:
        os.chmod(temporary, 0o600)
        handle.write(serialized)
        handle.write("\n")
    os.replace(temporary, destination)
    return destination


def _read_job(backtest_id: str, results_dir: str) -> dict[str, Any]:
    source = _job_path(backtest_id, results_dir)
    try:
        with source.open("r", encoding="utf-8") as handle:
            job = json.load(handle)
    except FileNotFoundError as exc:
        raise JevBacktestNotFoundError("Backtest não encontrado.") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JevBacktestError("O backtest não pôde ser lido.") from exc
    if not isinstance(job, dict) or job.get("backtest_id") != backtest_id:
        raise JevBacktestError("O registro do backtest é inválido.")
    return job


def _append_step(backtest_id: str, step_record: dict[str, Any], results_dir: str) -> Path:
    directory = _backtest_directory(results_dir)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination = _steps_path(backtest_id, results_dir)
    line = json.dumps(step_record, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    with destination.open("a", encoding="utf-8") as handle:
        os.chmod(destination, 0o600)
        handle.write(line)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return destination


async def create_backtest(job: dict[str, Any], results_dir: str) -> Path:
    return await asyncio.to_thread(_write_job, job, results_dir)


async def load_backtest(backtest_id: str, results_dir: str) -> dict[str, Any]:
    return await asyncio.to_thread(_read_job, backtest_id, results_dir)


async def save_backtest_step(
    job: dict[str, Any], step_record: dict[str, Any], results_dir: str
) -> None:
    # Persist the advanced cursor first. If the secondary JSONL append fails, a retry
    # still cannot repeat a paid inference that already completed.
    await asyncio.to_thread(_write_job, job, results_dir)
    await asyncio.to_thread(_append_step, job["backtest_id"], step_record, results_dir)
