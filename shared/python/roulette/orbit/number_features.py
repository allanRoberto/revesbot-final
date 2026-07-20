"""Codificacao estatica canonica dos numeros 0..36."""

from __future__ import annotations

from functools import lru_cache

from .constants import (
    BLACK_NUMBERS,
    DIGIT_SUM_MEMBERSHIP,
    EUROPEAN_WHEEL,
    MIRRORS,
    ORPHELINS,
    RED_NUMBERS,
    TERMINAL_POSITION,
    TIERS_CYLINDRE,
    VOISINS_ZERO,
    WHEEL_INDEX,
    validate_number,
)
from .schemas import NumberFeatures


def _parity(number: int) -> str:
    if number == 0:
        return "NE"
    return "PA" if number % 2 == 0 else "IM"


def _color(number: int) -> str:
    if number in RED_NUMBERS:
        return "VM"
    if number in BLACK_NUMBERS:
        return "PR"
    return "VD"


def _dozen(number: int) -> int:
    return ((number - 1) // 12) + 1 if number else 0


def _column(number: int) -> int:
    if number == 0:
        return 0
    remainder = number % 3
    return 3 if remainder == 0 else remainder


def _sector(number: int) -> str:
    if number in VOISINS_ZERO:
        return "VZ"
    if number in TIERS_CYLINDRE:
        return "TI"
    if number in ORPHELINS:
        return "OR"
    raise AssertionError(f"numero sem setor: {number}")


@lru_cache(maxsize=37)
def get_number_features(number: int) -> NumberFeatures:
    value = validate_number(number)
    wheel_index = WHEEL_INDEX[value]
    digit_sum_group, digit_sum_position = DIGIT_SUM_MEMBERSHIP.get(value, (0, 0))
    terminal_family, terminal_position = TERMINAL_POSITION.get(value % 10, (None, 0))
    return NumberFeatures(
        number=value,
        wheel_index=wheel_index,
        parity=_parity(value),
        color=_color(value),
        dozen=_dozen(value),
        column=_column(value),
        sector=_sector(value),
        digit_sum_group=digit_sum_group,
        digit_sum_position=digit_sum_position,
        mirror=MIRRORS.get(value),
        terminal_family=terminal_family,
        terminal_position=terminal_position,
        wheel_neighbors=(
            EUROPEAN_WHEEL[(wheel_index - 1) % 37],
            EUROPEAN_WHEEL[(wheel_index + 1) % 37],
        ),
    )


NUMBER_FEATURES = tuple(get_number_features(number) for number in range(37))
