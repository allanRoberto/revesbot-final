from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from .config import BehaviorLabConfig
from .contracts import RuleProposal
from .wheel import classify_payment


class BehaviorRule(Protocol):
    name: str

    def detect(self, history: Sequence[int], config: BehaviorLabConfig) -> RuleProposal | None: ...


def _unique(values: Sequence[int]) -> list[int]:
    return list(dict.fromkeys(int(value) for value in values))


def _partition_exhausted(
    candidates: Sequence[int],
    history: Sequence[int],
    *,
    config: BehaviorLabConfig,
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Remove targets whose payable region already appeared near the trigger.

    The trigger itself is included.  This is intentional: in ``26, 36`` a
    historical continuation containing 36 cannot propose 36 again because the
    second 36 has already paid that target while forming the trigger.
    """

    if config.exhaustion_window <= 0:
        return tuple(_unique(candidates)), ()
    recent = history[-config.exhaustion_window :]
    remaining: list[int] = []
    exhausted: list[int] = []
    for candidate in _unique(candidates):
        paid = any(
            classify_payment(
                value,
                [candidate],
                span=config.neighbor_span,
                mirrors=config.mirrors,
            )
            is not None
            for value in recent
        )
        (exhausted if paid else remaining).append(candidate)
    return tuple(remaining), tuple(exhausted)


@dataclass(frozen=True)
class ExactPairContinuationRule:
    name: str = "exact_pair_continuation"

    def detect(self, history: Sequence[int], config: BehaviorLabConfig) -> RuleProposal | None:
        tail_size = config.pair_tail_size
        if len(history) < tail_size + 4:
            return None
        pair = (int(history[-2]), int(history[-1]))
        if pair[0] == pair[1]:
            return None
        current_start = len(history) - 2
        prior_start: int | None = None
        for index in range(current_start - tail_size - 2, -1, -1):
            if (int(history[index]), int(history[index + 1])) == pair:
                prior_start = index
                break
        if prior_start is None:
            return None

        raw_candidates = _unique(history[prior_start + 2 : prior_start + 2 + tail_size])
        targets, exhausted = _partition_exhausted(raw_candidates, history, config=config)
        if not targets:
            return None
        return RuleProposal(
            rule=self.name,
            targets=targets,
            exhausted_targets=exhausted,
            evidence={
                "trigger_pair": list(pair),
                "prior_start_index": prior_start,
                "current_start_index": current_start,
                "historical_continuation": raw_candidates,
            },
        )


@dataclass(frozen=True)
class RepeatedSameDoubleRule:
    name: str = "repeated_same_double"

    def detect(self, history: Sequence[int], config: BehaviorLabConfig) -> RuleProposal | None:
        tail_size = config.double_tail_size
        if len(history) < tail_size + 4 or history[-1] != history[-2]:
            return None
        doubled = int(history[-1])
        current_start = len(history) - 2
        prior_start: int | None = None
        for index in range(current_start - tail_size - 2, -1, -1):
            if int(history[index]) == doubled and int(history[index + 1]) == doubled:
                prior_start = index
                break
        if prior_start is None:
            return None

        raw_candidates = _unique(history[prior_start + 2 : prior_start + 2 + tail_size])
        targets, exhausted = _partition_exhausted(raw_candidates, history, config=config)
        if not targets:
            return None
        return RuleProposal(
            rule=self.name,
            targets=targets,
            exhausted_targets=exhausted,
            evidence={
                "trigger_double": doubled,
                "prior_start_index": prior_start,
                "current_start_index": current_start,
                "historical_continuation": raw_candidates,
            },
        )


@dataclass(frozen=True)
class _StructuralMotif:
    start: int
    end: int
    gap: int
    terminal: int
    doubled: int


def _structural_motifs(
    history: Sequence[int],
    *,
    terminal_numbers: set[int],
    max_gap: int,
) -> list[_StructuralMotif]:
    motifs: list[_StructuralMotif] = []
    length = len(history)
    for start, value in enumerate(history):
        if int(value) != 21:
            continue
        for gap in range(max_gap + 1):
            terminal_index = start + 1 + gap
            double_start = terminal_index + 1
            double_end = double_start + 1
            if double_end >= length:
                continue
            if int(history[terminal_index]) not in terminal_numbers:
                continue
            if int(history[double_start]) != int(history[double_end]):
                continue
            motifs.append(
                _StructuralMotif(
                    start=start,
                    end=double_end,
                    gap=gap,
                    terminal=int(history[terminal_index]),
                    doubled=int(history[double_start]),
                )
            )
    return motifs


@dataclass(frozen=True)
class Structural21TerminalOneDoubleRule:
    name: str = "structural_21_terminal1_double"

    def detect(self, history: Sequence[int], config: BehaviorLabConfig) -> RuleProposal | None:
        if len(history) < config.structural_tail_size + 8:
            return None
        motifs = _structural_motifs(
            history,
            terminal_numbers=set(config.terminal_one_numbers),
            max_gap=config.structural_max_gap,
        )
        current_options = [motif for motif in motifs if motif.end == len(history) - 1]
        if not current_options:
            return None
        # Prefer the tightest motif, then the latest anchor.
        current = sorted(current_options, key=lambda motif: (motif.gap, -motif.start))[0]
        prior_options = [
            motif
            for motif in motifs
            if motif.end + config.structural_tail_size < current.start
        ]
        if not prior_options:
            return None
        prior = max(prior_options, key=lambda motif: motif.end)
        raw_candidates = _unique(
            history[prior.end + 1 : prior.end + 1 + config.structural_tail_size]
        )
        targets, exhausted = _partition_exhausted(raw_candidates, history, config=config)
        if not targets:
            return None
        return RuleProposal(
            rule=self.name,
            targets=targets,
            exhausted_targets=exhausted,
            evidence={
                "prior_motif": {
                    "start_index": prior.start,
                    "end_index": prior.end,
                    "gap": prior.gap,
                    "terminal": prior.terminal,
                    "double": prior.doubled,
                },
                "current_motif": {
                    "start_index": current.start,
                    "end_index": current.end,
                    "gap": current.gap,
                    "terminal": current.terminal,
                    "double": current.doubled,
                },
                "historical_continuation": raw_candidates,
            },
        )


def default_rules() -> tuple[BehaviorRule, ...]:
    return (
        ExactPairContinuationRule(),
        RepeatedSameDoubleRule(),
        Structural21TerminalOneDoubleRule(),
    )
