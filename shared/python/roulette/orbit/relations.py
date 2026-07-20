"""Relacoes direcionais e simetricas entre dois numeros."""

from __future__ import annotations

from .constants import MIRRORS, validate_number
from .number_features import get_number_features
from .schemas import PairRelation


def signed_wheel_delta(source_index: int, target_index: int) -> int:
    """Menor deslocamento assinado na ordem canonica, no intervalo -18..18."""
    clockwise = (target_index - source_index) % 37
    return clockwise if clockwise <= 18 else clockwise - 37


def build_pair_relation(source: int, target: int) -> PairRelation:
    source_value = validate_number(source)
    target_value = validate_number(target)
    source_features = get_number_features(source_value)
    target_features = get_number_features(target_value)
    numeric_delta = target_value - source_value
    wheel_delta = signed_wheel_delta(source_features.wheel_index, target_features.wheel_index)
    exact = source_value == target_value
    return PairRelation(
        source=source_value,
        target=target_value,
        exact=exact,
        numeric_delta=numeric_delta,
        numeric_distance=abs(numeric_delta),
        numeric_sequence_distance=(abs(numeric_delta) if 0 < abs(numeric_delta) <= 2 else None),
        wheel_delta=wheel_delta,
        wheel_distance=abs(wheel_delta),
        mirror=MIRRORS.get(source_value) == target_value,
        same_parity=(
            source_features.parity != "NE"
            and source_features.parity == target_features.parity
        ),
        same_color=(
            source_features.color != "VD"
            and source_features.color == target_features.color
        ),
        same_dozen=(
            source_features.dozen != 0
            and source_features.dozen == target_features.dozen
        ),
        same_column=(
            source_features.column != 0
            and source_features.column == target_features.column
        ),
        same_sector=source_features.sector == target_features.sector,
        same_digit_sum=(
            source_features.digit_sum_group != 0
            and source_features.digit_sum_group == target_features.digit_sum_group
        ),
        same_terminal_family=(
            source_features.terminal_family is not None
            and source_features.terminal_family == target_features.terminal_family
        ),
    )
