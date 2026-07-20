from datetime import datetime, timezone

from apps.signals.orbit_engine.shadow_worker import (
    ShadowWorkerSettings,
    advance_trial_document,
    main,
)


def test_shadow_worker_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ORBIT_SHADOW_ENABLED", raising=False)
    assert ShadowWorkerSettings.from_env().enabled is False
    assert main() == 0


def test_shadow_worker_defaults_to_three_roulettes_and_ten_attempts(monkeypatch):
    monkeypatch.delenv("ORBIT_ROULETTE_IDS", raising=False)
    monkeypatch.delenv("ORBIT_MAX_ATTEMPTS", raising=False)

    settings = ShadowWorkerSettings.from_env()

    assert len(settings.roulette_ids) == 3
    assert settings.max_attempts == 10
    assert settings.history_limit == 600


def test_trial_advancement_locks_first_hits_and_resolves_at_ten():
    trial = {
        "top9": [7, 8, 9],
        "top12": [7, 8, 9, 10],
        "attempt_numbers": [1] * 9,
        "attempt_history_ids": [f"old-{index}" for index in range(9)],
        "attempt_timestamps_utc": [datetime.now(timezone.utc)] * 9,
        "attempts_observed": 9,
        "top9_first_hit_attempt": None,
        "top12_first_hit_attempt": 4,
    }

    payload = advance_trial_document(
        trial,
        number=7,
        history_id="new-spin",
        timestamp=datetime.now(timezone.utc),
        max_attempts=10,
    )

    assert payload is not None
    assert payload["attempts_observed"] == 10
    assert payload["top9_first_hit_attempt"] == 10
    assert payload["top12_first_hit_attempt"] == 4
    assert payload["status"] == "resolved"
    assert "resolved_at_utc" in payload


def test_trial_advancement_is_idempotent_for_same_history_id():
    trial = {
        "top9": [7],
        "top12": [7],
        "attempt_numbers": [7],
        "attempt_history_ids": ["same-spin"],
        "attempts_observed": 1,
    }

    assert advance_trial_document(
        trial,
        number=7,
        history_id="same-spin",
        timestamp=datetime.now(timezone.utc),
        max_attempts=10,
    ) is None
