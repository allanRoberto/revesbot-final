from __future__ import annotations

from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


TerminalSignalWindow = Literal["1h", "3h", "6h", "12h", "24h", "7d", "all"]
PayoutMode = Literal["source_html", "table_base"]
TerminalSignalSelectionMode = Literal["all", "top3", "top1", "fixed"]


class TerminalSignalProfitabilityRequest(BaseModel):
    variant: str = Field(min_length=1, max_length=64)
    roulette_ids: Optional[List[str]] = Field(default=None, max_length=40)
    window: TerminalSignalWindow = "24h"
    initial_bank: Decimal = Field(default=Decimal("100"), gt=0, le=Decimal("1000000000"))
    attempt_stakes: List[Decimal] = Field(
        default_factory=lambda: [
            Decimal("1"),
            Decimal("1.5"),
            Decimal("1.5"),
            Decimal("1.5"),
            Decimal("1.5"),
            Decimal("1.5"),
            Decimal("1.5"),
            Decimal("1.5"),
            Decimal("1.5"),
            Decimal("1.5"),
        ],
        min_length=2,
        max_length=10,
    )
    max_attempts: int = Field(default=2, ge=2, le=10)
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

    @model_validator(mode="after")
    def validate_horizon_stakes(self):
        if len(self.attempt_stakes) < self.max_attempts:
            raise ValueError("informe uma ficha para cada tentativa simulada")
        return self


class TerminalSignalScenarioRequest(TerminalSignalProfitabilityRequest):
    minimum_attempts: int = Field(default=2, ge=2, le=10)
    maximum_attempts: int = Field(default=10, ge=2, le=10)

    @model_validator(mode="after")
    def validate_comparison_range(self):
        if self.minimum_attempts > self.maximum_attempts:
            raise ValueError("a tentativa mínima não pode superar a máxima")
        if len(self.attempt_stakes) < self.maximum_attempts:
            raise ValueError("informe fichas até a tentativa máxima da comparação")
        return self


class TerminalSignalStrategyRequest(TerminalSignalScenarioRequest):
    selection_mode: TerminalSignalSelectionMode = "top3"
    ranking_lookback: int = Field(default=10, ge=5, le=200)
    tie_break_lookback: int = Field(default=30, ge=5, le=500)
    minimum_samples: int = Field(default=10, ge=3, le=200)
    minimum_assertiveness: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    fixed_roulette_ids: Optional[List[str]] = Field(default=None, max_length=40)
    comparison_modes: List[TerminalSignalSelectionMode] = Field(
        default_factory=lambda: ["all", "top3", "top1"],
        min_length=1,
        max_length=4,
    )

    @field_validator("fixed_roulette_ids")
    @classmethod
    def normalize_fixed_roulette_ids(
        cls,
        values: Optional[List[str]],
    ) -> Optional[List[str]]:
        if values is None:
            return None
        normalized = list(
            dict.fromkeys(str(value).strip() for value in values if str(value).strip())
        )
        return normalized or None

    @field_validator("comparison_modes")
    @classmethod
    def normalize_comparison_modes(
        cls,
        values: List[TerminalSignalSelectionMode],
    ) -> List[TerminalSignalSelectionMode]:
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def validate_ranking_settings(self):
        if self.minimum_samples > self.ranking_lookback:
            raise ValueError("a amostra mínima não pode superar a janela do ranking")
        if self.tie_break_lookback < self.ranking_lookback:
            raise ValueError("o desempate não pode usar uma janela menor")
        if self.selection_mode == "fixed" and not self.fixed_roulette_ids:
            raise ValueError("selecione ao menos uma mesa para o modo fixo")
        return self
