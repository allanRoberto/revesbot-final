"""Identificadores humanos e estaveis para observacoes orbitais."""

from __future__ import annotations

from .constants import SCHEMA_VERSION, validate_number
from .number_features import get_number_features
from .relation_matrix import RELATION_MATRIX


def build_orbital_identifier(
    *,
    pivot: int,
    number: int,
    occurrence_lag: int,
    relative_offset: int,
) -> str:
    pivot_value = validate_number(pivot)
    number_value = validate_number(number)
    if relative_offset == 0:
        raise ValueError("relative_offset zero pertence ao pivo, nao a uma observacao")
    relation = RELATION_MATRIX.get(pivot_value, number_value)
    features = get_number_features(number_value)
    side = "A" if relative_offset < 0 else "D"
    equal: list[str] = []
    if relation.same_color:
        equal.append("COR")
    if relation.same_parity:
        equal.append("PAR")
    if relation.same_dozen:
        equal.append("DZ")
    if relation.same_column:
        equal.append("COL")
    if relation.same_sector:
        equal.append("SET")
    if relation.same_digit_sum:
        equal.append("SG")
    if relation.same_terminal_family:
        equal.append("FT")
    equality = ",".join(equal) if equal else "-"
    return (
        f"IOR:{SCHEMA_VERSION}|P{pivot_value:02d}|T{int(occurrence_lag):+d}|"
        f"{side}{abs(int(relative_offset))}|N{number_value:02d}|"
        f"RF{relation.wheel_delta:+03d}|DN{relation.numeric_delta:+03d}|"
        f"EQ[{equality}]|ES{1 if relation.mirror else 0}|"
        f"SG{features.digit_sum_group:02d}S{features.digit_sum_position}|"
        f"FT{features.terminal_family or '---'}P{features.terminal_position}"
    )
