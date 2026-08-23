from datetime import datetime, timedelta, timezone

from apps.monitoring.patterns import load_pattern
from apps.monitoring.patterns.core.contracts import Spin
from apps.monitoring.patterns.core.runtime import (
    PatternRuntime,
    apply_spin_to_signal,
    build_signal_document,
)


def _spins(raw):
    now = datetime(2026, 8, 22, 16, 0, tzinfo=timezone.utc)
    return [
        Spin(
            history_id=f"history-{index}",
            source_id=index,
            roulette_id="pragmatic-auto-roulette",
            value=value,
            timestamp=now - timedelta(seconds=40 * index),
        )
        for index, value in enumerate(raw)
    ]


def test_loader_keeps_implementations_independent_and_extensible():
    nera = load_pattern("nera")
    hope = load_pattern("last-hope")

    assert nera.definition.key == "nera"
    assert hope.definition.key == "last_hope"
    assert type(nera.engine) is not type(hope.engine)
    assert len(nera.definition.roulette_ids) == 24
    assert len(hope.definition.roulette_ids) == 24
    assert nera.definition.default_chip_profile == (2.5, 1.5, 1.5, 1.0)


def test_nera_reference_sequence_preserves_original_selection():
    raw = [
        6, 13, 19, 15, 23, 18, 16, 24, 11, 32, 5, 12, 21, 17, 16, 17,
        33, 9, 14, 4, 25, 2, 31, 3, 4, 31, 8, 20, 9, 29, 16, 3, 29, 29,
        21, 14, 18, 16, 33, 19, 32, 6, 31, 22, 30, 29, 27, 18, 26, 31,
        22, 10, 2, 28, 5, 14, 0, 30, 17, 6, 28, 22, 3, 22, 26, 24, 2,
        17, 6, 1, 26, 32, 2, 33, 12, 6, 4, 16, 29, 5, 12, 19, 25, 29,
        34, 25, 4, 1, 14, 13, 5, 25, 22, 17, 19, 20, 31, 15, 31, 0, 36,
        16, 36, 16, 3, 14, 2, 26, 22, 23, 21, 11, 25, 2, 23, 8, 30, 6,
        14, 19,
    ]
    loaded = load_pattern("nera")
    candidate = loaded.engine.analyze(
        _spins(raw), roulette_id="pragmatic-auto-roulette", payout=36
    )

    assert candidate is not None
    assert candidate.trigger_number == 6
    assert candidate.target_name == "Alvo 1"
    assert candidate.bet_numbers == (0, 1, 2, 3, 6, 9, 10, 11, 20, 22, 30, 33)
    assert candidate.details["valid_falls"] == [41, 68, 75]


def test_last_hope_reference_sequence_preserves_hot_context():
    raw = [
        31, 15, 9, 21, 22, 22, 20, 26, 2, 29, 14, 3, 2, 9, 30, 23, 26,
        13, 2, 30, 13, 29, 17, 1, 27, 3, 7, 22, 29, 29, 29, 11, 13, 5,
        25, 20, 33, 7, 36, 27, 18, 7, 26, 29, 33, 21, 27, 31, 24, 15,
        20, 10, 19, 9, 24, 13, 30, 27, 21, 11, 13, 34, 0, 12, 32, 22, 36,
        14, 36, 7, 33, 28, 20, 15, 26, 3, 18, 30, 28, 4, 8, 32, 27, 11,
        12, 20, 34, 8, 18, 6, 19, 33, 2, 10, 17, 25, 2, 28, 35, 7, 36,
        23, 28, 18, 34, 0, 0, 3, 36, 26, 23, 19, 3, 29, 14, 31, 36, 5,
        0, 22,
    ]
    loaded = load_pattern("last_hope")
    candidate = loaded.engine.analyze(
        _spins(raw), roulette_id="pragmatic-auto-roulette", payout=36
    )

    assert candidate is not None
    assert candidate.bet_numbers == (0, 20, 22, 29, 36)
    assert candidate.details["timeframe"] == 200
    assert candidate.details["library_pattern"] == "QQQ"
    assert candidate.details["score"] == 0.82


def test_nera_waiting_spins_do_not_consume_attempts_and_are_idempotent():
    loaded = load_pattern("nera")
    trigger = _spins([6])[0]
    candidate = type("Candidate", (), {
        "trigger_number": 6,
        "bet_numbers": (0, 6),
        "target_name": "Teste",
        "details": {},
        "runtime": {"delay_remaining": 2, "delay_triggered": True, "last_observed_number": 6},
    })()
    signal = build_signal_document(
        loaded=loaded,
        pattern_id="pattern-nera",
        roulette_id=trigger.roulette_id,
        trigger=trigger,
        candidate=candidate,
        eligible_hour=True,
    )
    next_spin = Spin(
        "next", 2, trigger.roulette_id, 9, trigger.timestamp + timedelta(seconds=40)
    )

    signal, changed = apply_spin_to_signal(loaded, signal, next_spin)
    signal, duplicate_changed = apply_spin_to_signal(loaded, signal, next_spin)

    assert changed is True
    assert duplicate_changed is False
    assert signal["attempts"] == []
    assert len(signal["waiting_spins"]) == 1
    assert signal["runtime"]["delay_remaining"] == 2


def test_attempt_finance_uses_real_number_count_and_profile():
    loaded = load_pattern("last_hope")
    trigger = _spins([31])[0]
    candidate = type("Candidate", (), {
        "trigger_number": 31,
        "bet_numbers": (0, 20, 22, 27, 29),
        "target_name": "Teste",
        "details": {},
        "runtime": {},
    })()
    signal = build_signal_document(
        loaded=loaded,
        pattern_id="pattern-hope",
        roulette_id=trigger.roulette_id,
        trigger=trigger,
        candidate=candidate,
        eligible_hour=True,
    )
    miss = Spin("miss", 2, trigger.roulette_id, 1, trigger.timestamp + timedelta(seconds=40))
    hit = Spin("hit", 3, trigger.roulette_id, 20, trigger.timestamp + timedelta(seconds=80))

    signal, _ = apply_spin_to_signal(loaded, signal, miss)
    signal, _ = apply_spin_to_signal(loaded, signal, hit)

    assert signal["status"] == "won"
    assert signal["won_at_attempt"] == 2
    assert signal["financial"]["total_wagered"] == 20.0
    assert signal["financial"]["gross_return"] == 54.0
    assert signal["financial"]["net_profit"] == 34.0


def test_restart_normalizes_naive_mongo_state_timestamp():
    loaded = load_pattern("nera")
    naive_timestamp = datetime(2026, 8, 22, 16, 0)

    class FakeRepository:
        def ensure_indexes(self):
            pass

        def upsert_definition(self, definition):
            return {"_id": "pattern-nera"}

        def acquire_lease(self, pattern_key, owner, *, ttl_seconds):
            return True

        def load_state(self, pattern_key, roulette_id):
            return {
                "last_history_id": "stored-cursor",
                "last_history_timestamp": naive_timestamp,
            }

        def load_active_signal(self, pattern_key, roulette_id):
            return None

        def save_state(self, document):
            pass

        def dashboard_snapshot(self, pattern_key):
            return {"pattern_key": pattern_key}

    class FakeHistorySource:
        calls = 0

        def ending_at(self, roulette_id, source_id, timestamp, limit):
            assert timestamp.tzinfo is not None
            assert timestamp.utcoffset() == timedelta(0)
            self.calls += 1
            return [
                Spin(
                    history_id=f"history-{roulette_id}",
                    source_id=source_id,
                    roulette_id=roulette_id,
                    value=1,
                    timestamp=timestamp,
                )
            ]

    history_source = FakeHistorySource()
    runtime = PatternRuntime(
        loaded=loaded,
        repository=FakeRepository(),
        history_source=history_source,
    )

    runtime.initialize()

    assert history_source.calls == len(loaded.definition.roulette_ids)
    assert all(
        context.last_timestamp.tzinfo is not None
        for context in runtime.tables.values()
    )
