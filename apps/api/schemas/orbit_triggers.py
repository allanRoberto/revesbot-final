from __future__ import annotations

from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


PerformanceWindow = Literal["1h", "3h", "6h", "12h", "24h", "all"]


class OrbitTriggerProfitabilityRequest(BaseModel):
    roulette_ids: List[str] = Field(min_length=1, max_length=20)
    strategy_slugs: Optional[List[str]] = Field(default=None, min_length=1, max_length=9)
    window: PerformanceWindow = "24h"
    initial_bank: Decimal = Field(gt=0, le=Decimal("1000000000"))
    attempt_stakes: List[Decimal] = Field(min_length=5, max_length=10)
    maximum_records: int = Field(default=50_000, ge=100, le=200_000)
    maximum_chart_points: int = Field(default=400, ge=50, le=1_000)

    @field_validator("roulette_ids", "strategy_slugs")
    @classmethod
    def normalize_identifiers(cls, values: Optional[List[str]]) -> Optional[List[str]]:
        if values is None:
            return None
        normalized = list(
            dict.fromkeys(str(value).strip() for value in values if str(value).strip())
        )
        if not normalized:
            raise ValueError("informe ao menos um identificador")
        return normalized

    @field_validator("attempt_stakes")
    @classmethod
    def validate_attempt_stakes(cls, values: List[Decimal]) -> List[Decimal]:
        if any(value < 0 for value in values):
            raise ValueError("os valores por tentativa nao podem ser negativos")
        if any(value != value.to_integral_value() for value in values):
            raise ValueError("as fichas por numero precisam ser valores inteiros")
        if any(value > Decimal("100000000") for value in values):
            raise ValueError("valor por tentativa acima do limite permitido")
        return values
