from __future__ import annotations

import pytest

from behavior_lab.config import BehaviorLabConfig, load_config
from behavior_lab.wheel import classify_payment, coverage_for_target, neighbors, validate_number


def test_default_configuration_is_frozen_for_live_table() -> None:
    config = load_config()
    assert config.roulette_id == "pragmatic-auto-roulette"
    assert config.context_size == 500
    assert config.signal_horizon == 10
    assert config.terminal_one_numbers == (1, 11, 31)
    assert config.mirrors == ((13, 31),)


def test_horizon_and_table_cannot_be_changed_in_v1() -> None:
    with pytest.raises(ValueError):
        BehaviorLabConfig(signal_horizon=9)
    with pytest.raises(ValueError):
        BehaviorLabConfig(roulette_id="another-table")


@pytest.mark.parametrize("value", [True, False, 1.0, 1.5, -1, 37, None])
def test_invalid_results_are_rejected_without_float_truncation(value) -> None:
    with pytest.raises(ValueError):
        validate_number(value)


def test_canonical_european_wheel_wraps_and_classifies() -> None:
    assert neighbors(0) == (26, 32)
    assert neighbors(13) == (27, 36)
    assert coverage_for_target(13, mirrors=((13, 31),)) == (13, 27, 36, 31)
    assert classify_payment(13, [13], mirrors=((13, 31),)) == ("exact", 13)
    assert classify_payment(36, [13], mirrors=((13, 31),)) == ("neighbor", 13)
    assert classify_payment(31, [13], mirrors=((13, 31),)) == ("mirror", 13)
    # 31 is mirror of 13 but physical neighbour of 14: neighbour wins the tie.
    assert classify_payment(31, [13, 14], mirrors=((13, 31),)) == ("neighbor", 14)
