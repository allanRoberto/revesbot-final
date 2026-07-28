from __future__ import annotations

from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


TerminalSignalWindow = Literal["1h", "3h", "6h", "12h", "24h", "7d", "all"]
PayoutMode = Literal["source_html", "table_base"]


class TerminalSignalProfitabilityRequest(BaseModel):
    variant: str = Field(min_length=1, max_length=64)
    roulette_ids: Optional[List[str]] = Field(default=None, max_length=40)
    window: TerminalSignalWindow = "24h"
    initial_bank: Decimal = Field(default=Decimal("100"), gt=0, le=Decimal("1000000000"))
    attempt_stakes: List[Decimal] = Field(
        default_factory=lambda: [Decimal("1"), Decimal("1.5")],
        min_length=2,
        max_length=2,
    )
    payout_mode: PayoutMode = "source_html"
    maximum_records: int = Field(default=50_000, ge=100, le=200_000)
    maximum_chart_points: int = Field(default=500, ge=50, le=1_000)

    @field_validator("roulette_ids")
    @classmethod
    def normalize_roulette_ids(cls, values: Optional[List[str]]) -> Optional[List[str]]:
        if values is None:
            return None
        normalized = list(
            dict.fromkeys(str(value).strip() for value in values if str(value).strip())
        )
        return normalized or None

    @field_validator("attempt_stakes")
    @classmethod
    def validate_attempt_stakes(cls, values: List[Decimal]) -> List[Decimal]:
        if any(value < 0 for value in values):
            raise ValueError("as fichas precisam ser não negativas")
        if any(value > Decimal("100000000") for value in values):
            raise ValueError("valor de ficha acima do limite")
        return values
