from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

from shared.python.roulette.orbit.orbit_builder import OrbitBuilder
from shared.python.roulette.orbit.schemas import ReplayDecision

from .snapshot import SpinRecord, iter_snapshot


@dataclass(frozen=True, slots=True)
class ChronologicalSplit:
    train_end: int
    validation_end: int
    total: int

    @property
    def train_slice(self) -> slice:
        return slice(0, self.train_end)

    @property
    def validation_slice(self) -> slice:
        return slice(self.train_end, self.validation_end)

    @property
    def test_slice(self) -> slice:
        return slice(self.validation_end, self.total)


def chronological_split(
    total: int,
    *,
    train_ratio: float = 0.60,
    validation_ratio: float = 0.20,
) -> ChronologicalSplit:
    if total < 3:
        raise ValueError("dataset precisa de ao menos tres registros")
    if not 0 < train_ratio < 1 or not 0 < validation_ratio < 1:
        raise ValueError("ratios precisam estar entre zero e um")
    if train_ratio + validation_ratio >= 1:
        raise ValueError("train + validation precisa deixar bloco de teste")
    train_end = max(1, int(total * train_ratio))
    validation_end = max(train_end + 1, int(total * (train_ratio + validation_ratio)))
    validation_end = min(total - 1, validation_end)
    return ChronologicalSplit(train_end=train_end, validation_end=validation_end, total=total)


def load_records(path: Path) -> tuple[SpinRecord, ...]:
    rows = tuple(iter_snapshot(path))
    if any(rows[index].timestamp > rows[index + 1].timestamp for index in range(len(rows) - 1)):
        raise ValueError("snapshot fora da ordem cronologica")
    return rows


def iter_replay_decisions(
    records: Sequence[SpinRecord],
    *,
    builder: OrbitBuilder,
    horizon: int = 3,
    warmup: int = 300,
    anchor_start: int | None = None,
    anchor_end: int | None = None,
) -> Iterator[ReplayDecision]:
    values = tuple(record.value for record in records)
    timestamps = tuple(record.timestamp for record in records)
    start = max(int(warmup), int(anchor_start or 0))
    end = len(records) if anchor_end is None else min(len(records), int(anchor_end))
    for decision in builder.replay_decisions(
        values,
        horizon=horizon,
        warmup=warmup,
        timestamps=timestamps,
    ):
        anchor = decision.context.anchor_index
        if anchor < start:
            continue
        if anchor >= end:
            return
        yield decision
