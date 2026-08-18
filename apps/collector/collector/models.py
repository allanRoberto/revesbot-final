from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


MultiplierValue = int | float


@dataclass(frozen=True)
class RouletteResult:
    roulette_id: str
    value: int
    timestamp: datetime
    external_game_id: str | None
    slots: dict[str, MultiplierValue] = field(default_factory=dict)
    winning_multiplier: MultiplierValue | None = None
    captured_at: datetime | None = None
    recovered: bool = False
    timestamp_source: str = "captured"

    def as_document(self) -> dict:
        return {
            "roulette_id": self.roulette_id,
            "roulette_name": self.roulette_id,
            "slug": self.roulette_id,
            "external_game_id": self.external_game_id,
            "value": self.value,
            "timestamp": self.timestamp,
            "slots": self.slots,
            "winning_multiplier": self.winning_multiplier,
            "captured_at": self.captured_at or self.timestamp,
            "recovered": self.recovered,
            "timestamp_source": self.timestamp_source,
        }
