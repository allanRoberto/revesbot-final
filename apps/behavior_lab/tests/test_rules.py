from __future__ import annotations

from behavior_lab.config import BehaviorLabConfig
from behavior_lab.rules import (
    ExactPairContinuationRule,
    RepeatedSameDoubleRule,
    Structural21TerminalOneDoubleRule,
)


def test_exact_pair_replays_historical_continuation() -> None:
    history = [26, 36, 2, 34, 5, *([8] * 6), 26, 36]
    proposal = ExactPairContinuationRule().detect(history, BehaviorLabConfig(exhaustion_window=5))
    assert proposal is not None
    assert proposal.targets == (2, 34, 5)
    assert proposal.evidence["trigger_pair"] == [26, 36]


def test_same_double_uses_its_previous_tail() -> None:
    history = [3, 3, 32, 30, 13, *([5] * 6), 3, 3]
    proposal = RepeatedSameDoubleRule().detect(history, BehaviorLabConfig(exhaustion_window=5))
    assert proposal is not None
    assert proposal.targets == (32, 30, 13)


def test_structural_21_terminal_one_double_prunes_already_paid_target() -> None:
    history = [
        21,
        11,
        14,
        14,
        12,
        25,
        21,
        36,
        *([10] * 9),
        21,
        31,
        3,
        3,
    ]
    proposal = Structural21TerminalOneDoubleRule().detect(
        history, BehaviorLabConfig(exhaustion_window=8)
    )
    assert proposal is not None
    assert proposal.targets == (12, 25, 36)
    assert proposal.exhausted_targets == (21,)
    assert proposal.evidence["current_motif"]["terminal"] == 31


def test_anchor_21_is_not_accepted_as_terminal_one() -> None:
    history = [21, 11, 14, 14, 12, 25, 36, 8, 8, 8, 21, 21, 3, 3]
    assert Structural21TerminalOneDoubleRule().detect(history, BehaviorLabConfig()) is None


def test_structural_rule_accepts_one_insertion_before_terminal() -> None:
    history = [
        21,
        11,
        14,
        14,
        12,
        25,
        36,
        8,
        *([10] * 9),
        21,
        8,
        31,
        3,
        3,
    ]
    proposal = Structural21TerminalOneDoubleRule().detect(
        history, BehaviorLabConfig(exhaustion_window=5)
    )
    assert proposal is not None
    assert proposal.evidence["current_motif"]["gap"] == 1
