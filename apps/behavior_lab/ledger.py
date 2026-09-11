from __future__ import annotations

from collections.abc import Iterable

from .config import BehaviorLabConfig
from .contracts import RuleProposal, Signal, SignalStatus, Spin
from .wheel import classify_payment, mirror_map, neighbors


def suggestion_for_targets(targets: Iterable[int], config: BehaviorLabConfig) -> list[int]:
    """Build a bounded group while preserving all exact targets first."""

    safe_targets = list(dict.fromkeys(int(value) for value in targets))
    suggestion: list[int] = list(safe_targets)
    for target in safe_targets:
        suggestion.extend(neighbors(target, config.neighbor_span))
    configured_mirrors = mirror_map(config.mirrors)
    for target in safe_targets:
        mirrored = configured_mirrors.get(target)
        if mirrored is not None:
            suggestion.append(mirrored)
    return list(dict.fromkeys(suggestion))[: config.max_suggested_numbers]


class SignalLedger:
    def __init__(self, config: BehaviorLabConfig, signals: Iterable[Signal] = ()) -> None:
        self.config = config
        self.signals: list[Signal] = list(signals)

    @property
    def active(self) -> list[Signal]:
        return [signal for signal in self.signals if signal.status == SignalStatus.ACTIVE]

    def activate(self, proposal: RuleProposal, spin: Spin, index: int) -> Signal:
        signal = Signal.create(
            proposal=proposal,
            spin=spin,
            index=index,
            suggested_numbers=suggestion_for_targets(proposal.targets, self.config),
        )
        self.signals.append(signal)
        return signal

    def settle(self, spin: Spin, index: int) -> list[Signal]:
        """Consume one attempt for every active signal.

        Numeric equality to the previous spin has no special treatment.  A
        legitimate repeated number consumes an attempt exactly like any other
        result; event identity de-duplication happens before this method.
        """

        resolved: list[Signal] = []
        for signal in list(self.active):
            signal.attempts += 1
            match = None
            if spin.value in signal.suggested_numbers:
                match = classify_payment(
                    spin.value,
                    signal.targets,
                    span=self.config.neighbor_span,
                    mirrors=self.config.mirrors,
                )
            if match is not None:
                signal.status = SignalStatus.WON
                signal.payment_type, signal.paid_target = match
                signal.paid_value = spin.value
                signal.resolved_at_index = index
                resolved.append(signal)
            elif signal.attempts >= self.config.signal_horizon:
                signal.status = SignalStatus.LOST
                signal.resolved_at_index = index
                resolved.append(signal)
        return resolved

    def censor_active(self, final_index: int | None = None) -> list[Signal]:
        censored: list[Signal] = []
        for signal in self.active:
            signal.status = SignalStatus.CENSORED
            signal.resolved_at_index = final_index
            censored.append(signal)
        return censored

    def recent(self, limit: int = 50, status: str | None = None) -> list[Signal]:
        selected = self.signals
        if status:
            selected = [signal for signal in selected if signal.status.value == status]
        return list(reversed(selected[-max(0, limit) :]))
