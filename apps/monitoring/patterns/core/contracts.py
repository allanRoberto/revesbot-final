from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


def utc_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("timestamp ausente ou invalido")
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


@dataclass(frozen=True)
class Spin:
    history_id: str
    source_id: Any
    roulette_id: str
    value: int
    timestamp: datetime

    @classmethod
    def from_mongo(cls, document: Mapping[str, Any]) -> "Spin":
        value = int(document.get("value"))
        if not 0 <= value <= 36:
            raise ValueError(f"numero fora da roleta europeia: {value}")
        source_id = document.get("_id")
        if source_id is None:
            raise ValueError("resultado sem _id")
        roulette_id = str(document.get("roulette_id") or "").strip()
        if not roulette_id:
            raise ValueError("resultado sem roulette_id")
        return cls(
            history_id=str(source_id),
            source_id=source_id,
            roulette_id=roulette_id,
            value=value,
            timestamp=utc_datetime(document.get("timestamp") or document.get("captured_at")),
        )

    def audit_dict(self) -> dict[str, Any]:
        return {
            "history_id": self.history_id,
            "value": self.value,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class PatternDefinition:
    key: str
    name: str
    version: str
    description: str
    required_history: int
    history_size: int
    max_attempts: int
    roulette_ids: tuple[str, ...]
    schedules: Mapping[str, tuple[int, ...]]
    default_chip_profile: tuple[float, ...] = (2.5, 1.5, 1.5, 1.0)
    configuration: Mapping[str, Any] = field(default_factory=dict)
    ui_schema: Mapping[str, Any] = field(default_factory=dict)

    def as_document(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "version": self.version,
            "implementation": self.key,
            "enabled": True,
            "description": self.description,
            "required_history": self.required_history,
            "history_size": self.history_size,
            "max_attempts": self.max_attempts,
            "roulette_ids": list(self.roulette_ids),
            "schedules": {key: list(hours) for key, hours in self.schedules.items()},
            "default_chip_profile": list(self.default_chip_profile),
            "configuration": dict(self.configuration),
            "ui_schema": dict(self.ui_schema),
        }


@dataclass(frozen=True)
class PatternCandidate:
    trigger_number: int
    bet_numbers: tuple[int, ...]
    target_name: str
    details: Mapping[str, Any] = field(default_factory=dict)
    runtime: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AttemptGate:
    count_attempt: bool
    runtime: Mapping[str, Any]
    reason: str | None = None


class PatternEngine(ABC):
    @abstractmethod
    def analyze(
        self,
        history: Sequence[Spin],
        *,
        roulette_id: str,
        payout: int,
    ) -> PatternCandidate | None:
        """Recebe historico do mais recente para o mais antigo."""

    def before_attempt(self, signal: Mapping[str, Any], spin: Spin) -> AttemptGate:
        return AttemptGate(
            count_attempt=True,
            runtime=dict(signal.get("runtime") or {}),
        )


@dataclass(frozen=True)
class LoadedPattern:
    definition: PatternDefinition
    engine: PatternEngine
