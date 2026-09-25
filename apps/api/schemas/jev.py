"""Strict request parsing and validation for the Jev roulette feature."""
from __future__ import annotations

import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


GROUP_KEYS = tuple(f"grupo_{index}" for index in range(1, 7))
RouletteNumber = Annotated[StrictInt, Field(ge=0, le=36)]
_SEPARATORS = re.compile(r"[ ,;\t\r\n]+")
_ASCII_INTEGER = re.compile(r"[0-9]+\Z", re.ASCII)


class JevInputError(ValueError):
    """Raised when textual roulette input cannot be parsed safely."""


def parse_roulette_text(value: str, *, field_name: str = "Histórico") -> list[int]:
    """Parse an ASCII-integer sequence without sorting or dropping values."""
    if not isinstance(value, str):
        raise JevInputError(f"{field_name} deve ser um texto.")

    stripped = value.strip(" ,;\t\r\n")
    if not stripped:
        return []

    result: list[int] = []
    for position, token in enumerate(_SEPARATORS.split(stripped), start=1):
        if not _ASCII_INTEGER.fullmatch(token):
            raise JevInputError(
                f"{field_name} contém um valor inválido na posição {position}: {token!r}."
            )
        try:
            number = int(token)
        except ValueError as exc:
            raise JevInputError(
                f"{field_name} contém um inteiro grande demais na posição {position}."
            ) from exc
        if not 0 <= number <= 36:
            raise JevInputError(
                f"{field_name} contém um número fora do intervalo de 0 a 36 na posição {position}."
            )
        result.append(number)
    return result


class JevAnalysisRequest(BaseModel):
    """Validated browser payload. Numeric coercion is deliberately disabled."""

    model_config = ConfigDict(extra="forbid", strict=True)

    history_order: Literal["oldest_to_newest"]
    historico_texto: str
    grupos: dict[str, list[RouletteNumber]]

    @field_validator("grupos")
    @classmethod
    def validate_groups(cls, groups: dict[str, list[int]]) -> dict[str, list[int]]:
        if set(groups) != set(GROUP_KEYS) or len(groups) != len(GROUP_KEYS):
            raise ValueError(
                "grupos deve conter exatamente grupo_1, grupo_2, grupo_3, grupo_4, grupo_5 e grupo_6"
            )
        for group_id in GROUP_KEYS:
            numbers = groups[group_id]
            if not numbers:
                raise ValueError(f"{group_id} não pode estar vazio")
            if len(numbers) != len(set(numbers)):
                raise ValueError(f"{group_id} não pode conter números repetidos")
        return {group_id: list(groups[group_id]) for group_id in GROUP_KEYS}


class JevRankingRequest(BaseModel):
    """Validated input for the 0-36 ranking and pull-relation catalogue."""

    model_config = ConfigDict(extra="forbid", strict=True)

    history_order: Literal["oldest_to_newest"]
    historico_texto: str


class JevEvaluationRequest(BaseModel):
    """Three observed spins used to evaluate one saved ranking."""

    model_config = ConfigDict(extra="forbid", strict=True)

    analysis_id: str
    resultados_reais_texto: str

    @field_validator("analysis_id")
    @classmethod
    def validate_analysis_id(cls, value: str) -> str:
        try:
            parsed = UUID(value)
        except (ValueError, AttributeError) as exc:
            raise ValueError("analysis_id deve ser um UUID válido") from exc
        if str(parsed) != value:
            raise ValueError("analysis_id deve usar o formato UUID canônico")
        return value
