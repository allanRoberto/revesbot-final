"""Snapshot imutavel e deterministico da colecao history."""

from __future__ import annotations

import gzip
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from .artifacts import atomic_write_json, orbit_data_dir, sha256_file


@dataclass(frozen=True, slots=True)
class SpinRecord:
    roulette_id: str
    value: int
    timestamp: datetime
    source_id: str


def _mongo_url() -> str:
    value = os.getenv("MONGO_URL") or os.getenv("mongo_url")
    if not value:
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass
        value = os.getenv("MONGO_URL") or os.getenv("mongo_url")
    if not value:
        raise RuntimeError("MONGO_URL/mongo_url nao configurada para snapshot orbital")
    return value


def _serialize_record(document: Mapping[str, Any]) -> dict[str, Any]:
    timestamp = document.get("timestamp")
    if not isinstance(timestamp, datetime):
        raise ValueError(f"timestamp invalido no history: {timestamp!r}")
    if timestamp.tzinfo is None:
        # PyMongo devolve datas BSON UTC como ``datetime`` sem timezone quando
        # tz_aware nao foi habilitado no cliente.
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    else:
        timestamp = timestamp.astimezone(timezone.utc)
    value = int(document.get("value"))
    if not 0 <= value <= 36:
        raise ValueError(f"valor invalido no history: {value}")
    return {
        "roulette_id": str(document.get("roulette_id") or ""),
        "value": value,
        "timestamp": timestamp.isoformat(),
        "source_id": str(document.get("_id")),
    }


def create_mongo_snapshot(
    roulette_ids: Sequence[str],
    *,
    output_dir: Path | None = None,
    batch_size: int = 25_000,
    maximum_records: int | None = None,
    mongo_url: str | None = None,
) -> dict[str, Any]:
    try:
        from pymongo import ASCENDING, DESCENDING, MongoClient
    except ImportError as exc:  # pragma: no cover - dependency error is explicit
        raise RuntimeError("pymongo e necessario para criar snapshot") from exc

    safe_ids = tuple(dict.fromkeys(str(value).strip() for value in roulette_ids if str(value).strip()))
    if not safe_ids:
        raise ValueError("informe ao menos uma roulette_id")
    if maximum_records is not None and int(maximum_records) <= 0:
        raise ValueError("maximum_records precisa ser positivo")
    destination = (output_dir or orbit_data_dir() / "snapshots").resolve()
    destination.mkdir(parents=True, exist_ok=True)
    client = MongoClient(
        mongo_url or _mongo_url(),
        connectTimeoutMS=20_000,
        serverSelectionTimeoutMS=20_000,
        compressors="zlib",
    )
    collection = client["roleta_db"]["history"]
    created_at = datetime.now(timezone.utc)
    snapshot_id = created_at.strftime("%Y%m%dT%H%M%SZ")
    partitions: list[dict[str, Any]] = []

    try:
        for roulette_id in safe_ids:
            boundary = collection.find_one(
                {"roulette_id": roulette_id},
                projection={"_id": 1, "timestamp": 1},
                sort=[("timestamp", DESCENDING), ("_id", DESCENDING)],
            )
            if not boundary:
                continue
            output_path = destination / f"{snapshot_id}-{roulette_id}.jsonl.gz"
            count = 0
            first_timestamp: str | None = None
            last_timestamp: str | None = None
            try:
                # A colecao ja possui este indice, mantido pelo monitor. Ler do
                # mais novo para o mais antigo permite keyset pagination sem
                # sort bloqueante; os chunks sao unidos na ordem inversa.
                index_hint = [("roulette_id", ASCENDING), ("timestamp", DESCENDING), ("_id", DESCENDING)]
                indexes = collection.index_information()
                if not any(
                    tuple(spec.get("key") or ()) == tuple(index_hint)
                    for spec in indexes.values()
                ):
                    raise RuntimeError(
                        "snapshot orbital requer indice (roulette_id:1,timestamp:-1,_id:-1)"
                    )
                with tempfile.TemporaryDirectory(prefix="orbit-snapshot-", dir=destination) as temp:
                    chunk_dir = Path(temp)
                    chunks: list[tuple[Path, int, str, str]] = []
                    upper_timestamp = boundary["timestamp"]
                    upper_id = boundary["_id"]
                    inclusive = True
                    exported = 0
                    while True:
                        if inclusive:
                            # A primeira pagina define, atomicamente para este
                            # export, a fronteira superior efetivamente lida.
                            query = {"roulette_id": roulette_id}
                        else:
                            query = {
                                "roulette_id": roulette_id,
                                "$or": [
                                    {"timestamp": {"$lt": upper_timestamp}},
                                    {"timestamp": upper_timestamp, "_id": {"$lt": upper_id}},
                                ],
                            }
                        remaining = (
                            None
                            if maximum_records is None
                            else max(0, int(maximum_records) - exported)
                        )
                        if remaining == 0:
                            break
                        page_limit = max(1, int(batch_size))
                        if remaining is not None:
                            page_limit = min(page_limit, remaining)
                        documents = list(
                            collection.find(
                                query,
                                projection={
                                    "_id": 1,
                                    "roulette_id": 1,
                                    "value": 1,
                                    "timestamp": 1,
                                },
                            )
                            .sort([("timestamp", DESCENDING), ("_id", DESCENDING)])
                            .hint(index_hint)
                            .limit(page_limit)
                        )
                        if not documents:
                            break
                        if inclusive:
                            boundary = {
                                "timestamp": documents[0]["timestamp"],
                                "_id": documents[0]["_id"],
                            }
                        rows = [_serialize_record(document) for document in reversed(documents)]
                        chunk_path = chunk_dir / f"{len(chunks):08d}.jsonl"
                        with chunk_path.open("w", encoding="utf-8") as chunk:
                            for row in rows:
                                chunk.write(
                                    json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                                    + "\n"
                                )
                        chunks.append(
                            (chunk_path, len(rows), rows[0]["timestamp"], rows[-1]["timestamp"])
                        )
                        exported += len(rows)
                        oldest = documents[-1]
                        upper_timestamp = oldest["timestamp"]
                        upper_id = oldest["_id"]
                        inclusive = False

                    with gzip.open(output_path, "wt", encoding="utf-8") as output:
                        for chunk_path, _size, _first, _last in reversed(chunks):
                            with chunk_path.open("r", encoding="utf-8") as chunk:
                                shutil.copyfileobj(chunk, output)
                    count = sum(size for _path, size, _first, _last in chunks)
                    if chunks:
                        first_timestamp = chunks[-1][2]
                        last_timestamp = chunks[0][3]
            except BaseException:
                output_path.unlink(missing_ok=True)
                raise
            partitions.append({
                "roulette_id": roulette_id,
                "path": str(output_path),
                "count": count,
                "first_timestamp": first_timestamp,
                "last_timestamp": last_timestamp,
                "sha256": sha256_file(output_path),
            })
    finally:
        client.close()

    manifest = {
        "snapshot_id": snapshot_id,
        "created_at_utc": created_at.isoformat(),
        "format": "jsonl.gz",
        "ordering": ["timestamp:asc", "_id:asc"],
        "maximum_records_per_roulette": maximum_records,
        "partitions": partitions,
        "total_records": sum(int(partition["count"]) for partition in partitions),
    }
    manifest_path = destination / f"{snapshot_id}-manifest.json"
    atomic_write_json(manifest_path, manifest)
    return {**manifest, "manifest_path": str(manifest_path)}


def iter_snapshot(path: Path) -> Iterator[SpinRecord]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            try:
                yield SpinRecord(
                    roulette_id=str(payload["roulette_id"]),
                    value=int(payload["value"]),
                    timestamp=datetime.fromisoformat(str(payload["timestamp"])),
                    source_id=str(payload["source_id"]),
                )
            except Exception as exc:
                raise ValueError(f"registro invalido em {path}:{line_number}") from exc
