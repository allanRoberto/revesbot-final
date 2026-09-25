"""Private JSON audit records for completed Jev analyses."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from uuid import UUID


class JevRecordNotFoundError(FileNotFoundError):
    pass


class JevInvalidRecordError(ValueError):
    pass


def _canonical_uuid(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise JevInvalidRecordError(f"{label} inválido.")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as exc:
        raise JevInvalidRecordError(f"{label} inválido.") from exc
    if str(parsed) != value:
        raise JevInvalidRecordError(f"{label} inválido.")
    return value


def _results_directory(results_dir: str) -> Path:
    return Path(results_dir).expanduser()


def _write_record(record: dict[str, Any], results_dir: str) -> Path:
    directory = _results_directory(results_dir)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    analysis_id = _canonical_uuid(record.get("analysis_id"), "analysis_id")
    filename = f"{analysis_id}.json"
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


def _read_analysis(analysis_id: str, results_dir: str) -> dict[str, Any]:
    canonical_id = _canonical_uuid(analysis_id, "analysis_id")
    source = _results_directory(results_dir) / f"{canonical_id}.json"
    try:
        with source.open("r", encoding="utf-8") as handle:
            record = json.load(handle)
    except FileNotFoundError as exc:
        raise JevRecordNotFoundError("Ranking não encontrado.") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JevInvalidRecordError("O registro do ranking não pôde ser lido.") from exc
    if not isinstance(record, dict) or record.get("analysis_id") != canonical_id:
        raise JevInvalidRecordError("O registro do ranking é inválido.")
    return record


async def load_analysis(analysis_id: str, results_dir: str) -> dict[str, Any]:
    return await asyncio.to_thread(_read_analysis, analysis_id, results_dir)


def _write_evaluation(record: dict[str, Any], results_dir: str) -> Path:
    directory = _results_directory(results_dir)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    analysis_id = _canonical_uuid(record.get("analysis_id"), "analysis_id")
    evaluation_id = _canonical_uuid(record.get("evaluation_id"), "evaluation_id")
    filename = f"{analysis_id}.evaluation.{evaluation_id}.json"
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


async def persist_evaluation(record: dict[str, Any], results_dir: str) -> Path:
    return await asyncio.to_thread(_write_evaluation, record, results_dir)
