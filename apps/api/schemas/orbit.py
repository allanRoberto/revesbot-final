from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class OrbitReplayRequest(BaseModel):
    history_chronological: List[int] = Field(min_length=20, max_length=50_000)
    pivot: Optional[int] = Field(default=None, ge=0, le=36)
    pre_window: int = Field(default=5, ge=1, le=20)
    post_window: int = Field(default=5, ge=1, le=20)
    memory_occurrences: int = Field(default=6, ge=1, le=100)
    horizon: int = Field(default=3, ge=1, le=10)
    warmup: int = Field(default=300, ge=10, le=20_000)
    maximum_decisions: int = Field(default=500, ge=1, le=2_000)

    @field_validator("history_chronological")
    @classmethod
    def validate_history(cls, values: List[int]) -> List[int]:
        if any(isinstance(value, bool) or not 0 <= int(value) <= 36 for value in values):
            raise ValueError("history_chronological aceita apenas numeros 0..36")
        return [int(value) for value in values]
