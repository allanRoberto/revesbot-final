from __future__ import annotations

from dataclasses import dataclass

from behavior_lab.config import BehaviorLabConfig
from behavior_lab.contracts import RuleProposal, SignalStatus
from behavior_lab.engine import BehaviorEngine


@dataclass
class OneShotRule:
    target: int = 7
    name: str = "one_shot_test"

    def detect(self, history, config):
        if len(history) != 1:
            return None
        return RuleProposal(
            rule=self.name,
            targets=(self.target,),
            exhausted_targets=(),
            evidence={"test": True},
        )


@dataclass
class EverySpinRule:
    target: int = 7
    name: str = "every_spin_test"

    def detect(self, history, config):
        return RuleProposal(
            rule=self.name,
            targets=(self.target,),
            exhausted_targets=(),
            evidence={"test": True},
        )


def _event(value: int, event_id: str) -> dict:
    return {
        "slug": "pragmatic-auto-roulette",
        "result": value,
        "full_result": {
            "_id": f"mongo-{event_id}",
            "external_game_id": event_id,
            "timestamp": f"2026-09-11T00:00:{event_id[-2:].zfill(2)}+00:00",
        },
    }


def test_signal_starts_only_after_trigger_spin() -> None:
    engine = BehaviorEngine(BehaviorLabConfig(), rules=[OneShotRule(target=7)])
    trigger = engine.process(_event(7, "01"))
    signal = engine.ledger.active[0]
    assert trigger.activated_signal_ids == (signal.signal_id,)
    assert signal.attempts == 0
    assert signal.status == SignalStatus.ACTIVE

    engine.process(_event(7, "02"))
    assert signal.status == SignalStatus.WON
    assert signal.attempts == 1


def test_equal_numeric_results_with_different_ids_consume_two_attempts() -> None:
    engine = BehaviorEngine(BehaviorLabConfig(), rules=[OneShotRule()])
    engine.process(_event(1, "01"))
    signal = engine.ledger.active[0]

    assert engine.process(_event(0, "02")).accepted is True
    assert engine.process(_event(0, "03")).accepted is True
    assert signal.attempts == 2
    assert engine.process(_event(0, "03")).duplicate is True
    assert signal.attempts == 2
    assert engine.processed_count == 3


def test_numbers_without_event_ids_are_never_value_deduplicated() -> None:
    engine = BehaviorEngine(BehaviorLabConfig(), rules=[])
    assert engine.process(14).accepted
    assert engine.process(14).accepted
    assert engine.processed_count == 2


def test_backtest_identity_deduplication_has_no_silent_window() -> None:
    engine = BehaviorEngine(BehaviorLabConfig(), rules=[])
    original = _event(14, "original")
    assert engine.process(original).accepted
    for index in range(2_100):
        assert engine.process(_event(index % 37, f"unique-{index:04d}")).accepted
    assert engine.process(original).duplicate


def test_tenth_spin_can_still_win() -> None:
    engine = BehaviorEngine(BehaviorLabConfig(), rules=[OneShotRule(target=7)])
    engine.process(_event(1, "01"))
    signal = engine.ledger.active[0]
    for index in range(2, 11):
        engine.process(_event(0, str(index).zfill(2)))
    assert signal.attempts == 9
    assert signal.status == SignalStatus.ACTIVE
    engine.process(_event(7, "11"))
    assert signal.attempts == 10
    assert signal.status == SignalStatus.WON


def test_tenth_miss_loses_and_short_end_is_censored() -> None:
    engine = BehaviorEngine(BehaviorLabConfig(), rules=[OneShotRule(target=7)])
    engine.process(_event(1, "01"))
    lost = engine.ledger.active[0]
    for index in range(2, 12):
        engine.process(_event(0, str(index).zfill(2)))
    assert lost.attempts == 10
    assert lost.status == SignalStatus.LOST

    another = BehaviorEngine(BehaviorLabConfig(), rules=[OneShotRule(target=7)])
    another.process(_event(1, "21"))
    another.process(_event(0, "22"))
    signal = another.ledger.active[0]
    another.ledger.censor_active(1)
    assert signal.status == SignalStatus.CENSORED
    assert signal.attempts == 1


def test_engine_state_roundtrip_preserves_dedupe_and_attempts() -> None:
    config = BehaviorLabConfig()
    engine = BehaviorEngine(config, rules=[OneShotRule()])
    engine.process(_event(1, "01"))
    engine.process(_event(0, "02"))
    restored = BehaviorEngine.from_state_dict(engine.to_state_dict(), config, rules=[OneShotRule()])
    signal = restored.ledger.active[0]
    assert signal.attempts == 1
    assert restored.process(_event(0, "02")).duplicate
    assert signal.attempts == 1


def test_live_retention_archives_resolved_signals_without_losing_metrics() -> None:
    config = BehaviorLabConfig()
    retained = BehaviorEngine(
        config,
        rules=[EverySpinRule()],
        resolved_signal_retention=3,
    )
    reference = BehaviorEngine(config, rules=[EverySpinRule()])
    for index in range(25):
        event = _event(0, str(index).zfill(2))
        retained.process(event)
        reference.process(event)

    retained_metrics = retained.snapshot()["metrics"]["signals"]
    reference_metrics = reference.snapshot()["metrics"]["signals"]
    assert retained_metrics["activated"] == reference_metrics["activated"] == 25
    assert retained_metrics["active"] == reference_metrics["active"] == 10
    assert retained_metrics["lost"] == reference_metrics["lost"] == 15
    assert retained_metrics["archived_records"] == 12
    assert len(retained.ledger.signals) == 13

    restored = BehaviorEngine.from_state_dict(
        retained.to_state_dict(),
        config,
        rules=[EverySpinRule()],
        resolved_signal_retention=3,
    )
    assert restored.snapshot()["metrics"]["signals"] == retained_metrics
