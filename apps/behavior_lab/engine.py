from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .config import BehaviorLabConfig
from .contracts import ProcessResult, Signal, SignalStatus, Spin, utc_now_iso
from .ledger import SignalLedger
from .rules import BehaviorRule, default_rules


class BehaviorEngine:
    """Single-table causal state machine.

    Processing order is fixed: settle old signals, append the new result,
    detect triggers, then publish the next-spin suggestion.
    """

    def __init__(
        self,
        config: BehaviorLabConfig,
        *,
        rules: Sequence[BehaviorRule] | None = None,
        history: Iterable[Spin] = (),
        signals: Iterable[Signal] = (),
        processed_count: int = 0,
        seen_identity_keys: Iterable[str] = (),
        decisions: Iterable[Mapping[str, Any]] = (),
        prospective_spins: int = 0,
        duplicate_events: int = 0,
        resolved_signal_retention: int | None = None,
        archived_signal_metrics: Mapping[str, Any] | None = None,
        identity_retention: int | None = None,
    ) -> None:
        self.config = config
        self.rules = tuple(default_rules() if rules is None else rules)
        self.history: deque[Spin] = deque(history, maxlen=config.context_size)
        self.ledger = SignalLedger(config, signals)
        self.processed_count = int(processed_count)
        self.decisions: deque[dict[str, Any]] = deque(
            (dict(decision) for decision in decisions), maxlen=config.context_size
        )
        self.prospective_spins = int(prospective_spins)
        self.duplicate_events = int(duplicate_events)
        self.resolved_signal_retention = (
            None
            if resolved_signal_retention is None
            else max(1, int(resolved_signal_retention))
        )
        self.archived_signal_metrics = dict(archived_signal_metrics or {})
        self.identity_retention = (
            None if identity_retention is None else max(1, int(identity_retention))
        )
        self._seen_order: deque[str] = deque(maxlen=self.identity_retention)
        self._seen_set: set[str] = set()
        for key in seen_identity_keys:
            self._remember_identity(str(key))

    def _remember_identity(self, key: str) -> None:
        if key in self._seen_set:
            return
        if (
            self._seen_order.maxlen is not None
            and len(self._seen_order) == self._seen_order.maxlen
        ):
            oldest = self._seen_order.popleft()
            self._seen_set.discard(oldest)
        self._seen_order.append(key)
        self._seen_set.add(key)

    def _is_duplicate(self, spin: Spin) -> bool:
        return any(key in self._seen_set for key in spin.identity_keys)

    def current_suggestion(self) -> tuple[int, ...]:
        # Newer signals receive display/bet priority when the aggregate is full.
        values: list[int] = []
        for signal in reversed(self.ledger.active):
            values.extend(signal.suggested_numbers)
        return tuple(dict.fromkeys(values))[: self.config.max_suggested_numbers]

    def _prune_resolved_signals(self) -> None:
        if self.resolved_signal_retention is None:
            return
        resolved = [
            signal for signal in self.ledger.signals if signal.status != SignalStatus.ACTIVE
        ]
        excess = len(resolved) - self.resolved_signal_retention
        if excess <= 0:
            return
        archived = resolved[:excess]
        archived_ids = {signal.signal_id for signal in archived}
        from .metrics import archive_signals

        self.archived_signal_metrics = archive_signals(
            self.archived_signal_metrics,
            archived,
        )
        self.ledger.signals = [
            signal for signal in self.ledger.signals if signal.signal_id not in archived_ids
        ]

    def process(
        self,
        raw: int | Mapping[str, Any] | Spin,
        *,
        source: str = "unknown",
        count_duplicate: bool = True,
    ) -> ProcessResult:
        spin = Spin.from_raw(raw, expected_roulette_id=self.config.roulette_id, source=source)
        if self._is_duplicate(spin):
            if count_duplicate:
                self.duplicate_events += 1
            return ProcessResult(
                accepted=False,
                duplicate=True,
                index=None,
                spin=spin,
                active_signal_ids=tuple(signal.signal_id for signal in self.ledger.active),
                suggestion=self.current_suggestion(),
                reason="same_event_identity",
            )

        index = self.processed_count
        suggestion_before = list(self.current_suggestion())
        active_before = [signal.signal_id for signal in self.ledger.active]
        resolved = self.ledger.settle(spin, index)
        self.history.append(spin)
        self.processed_count += 1
        for key in spin.identity_keys:
            self._remember_identity(key)

        values = [item.value for item in self.history]
        activated: list[Signal] = []
        for rule in self.rules:
            proposal = rule.detect(values, self.config)
            if proposal is not None:
                activated.append(self.ledger.activate(proposal, spin, index))
        self._prune_resolved_signals()

        self.decisions.append(
            {
                "index": index,
                "event_id": spin.external_game_id or spin.event_id,
                "result": spin.value,
                "suggestion": suggestion_before,
                "active_signal_ids": active_before,
                "hit": spin.value in suggestion_before,
                "decision": "BET" if suggestion_before else "NO_BET",
                "activated_signal_ids": [signal.signal_id for signal in activated],
                "resolved_signal_ids": [signal.signal_id for signal in resolved],
            }
        )
        self.prospective_spins += 1

        active = self.ledger.active
        return ProcessResult(
            accepted=True,
            duplicate=False,
            index=index,
            spin=spin,
            activated_signal_ids=tuple(signal.signal_id for signal in activated),
            resolved_signal_ids=tuple(signal.signal_id for signal in resolved),
            active_signal_ids=tuple(signal.signal_id for signal in active),
            suggestion=self.current_suggestion(),
            reason="signal_active" if active else "no_active_signal",
        )

    def snapshot(self) -> dict[str, Any]:
        from .metrics import build_metrics

        last_spin = self.history[-1] if self.history else None
        suggestion = list(self.current_suggestion())
        return {
            "version": self.config.version,
            "config_fingerprint": self.config.fingerprint,
            "generated_at": utc_now_iso(),
            "roulette_id": self.config.roulette_id,
            "processed_count": self.processed_count,
            "state_revision": self.processed_count,
            "context_size": len(self.history),
            "last_result": last_spin.as_dict() if last_spin else None,
            "suggestion": suggestion,
            "decision": "BET" if suggestion else "NO_BET",
            "reason": "signal_active" if suggestion else "no_active_signal",
            "active_signals": [signal.as_dict() for signal in self.ledger.active],
            "recent_results": [spin.as_dict() for spin in reversed(list(self.history)[-20:])],
            "metrics": build_metrics(
                signals=self.ledger.signals,
                decisions=list(self.decisions),
                accepted_spins=self.prospective_spins,
                duplicate_events=self.duplicate_events,
                archived_signals=self.archived_signal_metrics,
            ),
        }

    def reset_prospective_metrics(self) -> None:
        """End bootstrap without presenting historical replay as live results."""

        self.ledger.signals = list(self.ledger.active)
        self.decisions.clear()
        self.prospective_spins = 0
        self.duplicate_events = 0
        self.archived_signal_metrics = {}

    def to_state_dict(self) -> dict[str, Any]:
        return {
            "version": self.config.version,
            "config_fingerprint": self.config.fingerprint,
            "processed_count": self.processed_count,
            "history": [spin.as_dict() for spin in self.history],
            "signals": [signal.as_dict() for signal in self.ledger.signals],
            "seen_identity_keys": list(self._seen_order),
            "decisions": list(self.decisions),
            "prospective_spins": self.prospective_spins,
            "duplicate_events": self.duplicate_events,
            "archived_signal_metrics": self.archived_signal_metrics,
        }

    @classmethod
    def from_state_dict(
        cls,
        raw: Mapping[str, Any],
        config: BehaviorLabConfig,
        *,
        rules: Sequence[BehaviorRule] | None = None,
        resolved_signal_retention: int | None = None,
        identity_retention: int | None = None,
    ) -> "BehaviorEngine":
        if raw.get("config_fingerprint") != config.fingerprint:
            raise ValueError("estado foi produzido por outra configuracao")
        history = [Spin.from_raw(item, expected_roulette_id=config.roulette_id) for item in raw.get("history", [])]
        signals = [Signal.from_dict(item) for item in raw.get("signals", [])]
        return cls(
            config,
            rules=rules,
            history=history,
            signals=signals,
            processed_count=int(raw.get("processed_count", len(history))),
            seen_identity_keys=raw.get("seen_identity_keys", ()),
            decisions=raw.get("decisions", ()),
            prospective_spins=int(raw.get("prospective_spins", 0)),
            duplicate_events=int(raw.get("duplicate_events", 0)),
            resolved_signal_retention=resolved_signal_retention,
            archived_signal_metrics=raw.get("archived_signal_metrics", {}),
            identity_retention=identity_retention,
        )
