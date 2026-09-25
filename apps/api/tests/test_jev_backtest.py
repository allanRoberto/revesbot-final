from __future__ import annotations

import base64
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.core.config import settings
from api.routes import jev as jev_route
from api.services.jev_backtest import (
    build_backtest_job,
    evaluate_observation,
    evaluate_step,
    record_success,
    required_history_size,
    select_chips,
    step_window,
)
from api.services.jev_openrouter import ValidatedChoiceAnswer, ValidatedJevResponse
from api.services.jev_ranking import NEXT_SPIN_CHOICE_KEY


AUTHORIZATION = "Basic " + base64.b64encode(b"admin:secret").decode("ascii")
AUTH_HEADERS = {"Authorization": AUTHORIZATION}


class FakeCursor:
    def __init__(self, documents):
        self.documents = list(documents)

    def sort(self, *_args, **_kwargs):
        return self

    def limit(self, amount):
        self.documents = self.documents[:amount]
        return self

    async def to_list(self, length=None):
        return self.documents[:length]


class FakeCollection:
    def __init__(self, oldest_to_newest):
        self.documents = [{"value": value} for value in reversed(oldest_to_newest)]

    def find(self, query, projection):
        assert query == {"roulette_id": "pragmatic-auto-roulette"}
        assert projection == {"value": 1, "timestamp": 1}
        return FakeCursor(self.documents)


class FakeBacktestJevClient:
    model = "typesafe/jev-1.13"

    def __init__(self):
        self.calls = []

    async def analyze(self, *, state, questions, require_choice_confidence=True):
        self.calls.append(
            {
                "state": state,
                "questions": questions,
                "require_choice_confidence": require_choice_confidence,
            }
        )
        probabilities = {str(number): 0.0 for number in range(37)}
        probabilities["0"] = 0.6
        probabilities["1"] = 0.4
        return ValidatedJevResponse(
            raw={
                "model": "typesafe/jev-1.13-test",
                "answers": {},
                "usage": {"input_tokens": 1000, "cost": 0.000042},
            },
            probabilities={},
            returned_model="typesafe/jev-1.13-test",
            latency_ms=4,
            choices={
                NEXT_SPIN_CHOICE_KEY: ValidatedChoiceAnswer(
                    choice="0", confidence=0.6, probabilities=probabilities
                )
            },
        )


def _job(history, *, signal_mode="overlapping", history_points=2, attempts=3):
    return build_backtest_job(
        backtest_id=str(uuid4()),
        history=history,
        history_points=history_points,
        context_numbers=50,
        chip_count=2,
        attempts=attempts,
        requested_model="typesafe/jev-1.13",
        created_at="2026-09-25T12:00:00Z",
        history_fetched_at="2026-09-25T12:00:00Z",
        signal_mode=signal_mode,
    )


def test_backtest_windows_never_include_future_in_jev_history() -> None:
    history = [index % 37 for index in range(required_history_size(2, 50, 3))]
    assert len(history) == 61
    job = _job(history)

    first_history, first_future, first_observation = step_window(job, 0)
    second_history, second_future, second_observation = step_window(job, 1)

    assert first_history == history[:50]
    assert first_future == history[50:53]
    assert first_observation == history[50:60]
    assert second_history == history[1:51]
    assert second_future == history[51:54]
    assert second_observation == history[51:61]


def test_selection_evaluation_and_real_cost_projection() -> None:
    probabilities = {str(number): 0.0 for number in range(37)}
    probabilities.update({"0": 0.4, "12": 0.3, "7": 0.2})
    selected = select_chips(probabilities, 3)
    assert selected == [0, 12, 7]
    assert evaluate_step(selected, [5, 12, 0]) == {
        "hit": True,
        "first_hit_attempt": 2,
        "hit_number": 12,
    }

    observation = [0, 5, 12, 0, 7, 12, 8, 9, 0, 3]
    assert evaluate_observation([0, 12], observation) == {
        "horizon": 10,
        "hit_count": 5,
        "hit_attempts": [1, 3, 4, 6, 9],
        "hit_numbers": [0, 12, 0, 12, 0],
        "has_any_hit": True,
        "has_multiple_hits": True,
        "hit_within_first_3": True,
        "has_hit_after_attempt_3": True,
    }

    job = _job([5] * 61)
    record_success(
        job,
        step=0,
        selected_numbers=selected[:2],
        future_numbers=[5, 12, 0],
        observation_numbers=observation,
        returned_model="typesafe/jev-1.13-test",
        latency_ms=10,
        raw_response={"usage": {"input_tokens": 1000, "cost": 0.000042}},
    )
    assert job["metrics"]["accuracy"] == 1.0
    assert job["metrics"]["hits_by_attempt"]["2"] == 1
    observed = job["metrics"]["observation"]
    assert observed["total_hits"] == 5
    assert observed["average_hits_per_signal"] == 5.0
    assert observed["signals_with_multiple_hits_rate"] == 1.0
    assert observed["hit_occurrences_by_attempt"]["6"] == 1
    assert observed["hit_count_distribution"]["5"] == 1
    early = observed["early_win_within_3"]
    assert early["repeat_rate"] == 1.0
    assert early["hit_after_attempt_3_rate"] == 1.0
    assert early["initial_hits_total"] == 2
    assert early["average_initial_hits_per_eligible_signal"] == 2.0
    assert early["signals_with_multiple_hits_within_3"] == 1
    assert early["multiple_hits_within_3_rate"] == 1.0
    assert early["initial_hit_count_distribution"] == {"1": 0, "2": 1, "3": 0}
    assert early["hits_after_attempt_3_total"] == 3
    assert early["average_hits_after_attempt_3_per_eligible_signal"] == 3.0
    assert early["hit_occurrences_after_attempt_3_by_attempt"]["4"] == 1
    assert early["hit_occurrences_after_attempt_3_by_attempt"]["6"] == 1
    assert early["hit_occurrences_after_attempt_3_by_attempt"]["9"] == 1
    assert early["hit_rate_after_attempt_3_by_attempt"]["4"] == 1.0
    assert early["first_hit_after_attempt_3_by_attempt"]["4"] == 1
    assert job["usage"]["projected_cost_per_1000_calls_usd"] == 0.042


def test_early_win_metrics_separate_attempts_one_to_three_from_four_to_ten() -> None:
    job = _job(
        [5] * required_history_size(3, 50, 3),
        history_points=3,
    )
    observations = [
        [0, 5, 6, 0, 7, 0, 8, 9, 10, 11],
        [5, 0, 0, 7, 8, 9, 0, 11, 12, 13],
        [5, 6, 7, 8, 0, 9, 10, 11, 12, 13],
    ]

    for step, observation in enumerate(observations):
        record_success(
            job,
            step=step,
            selected_numbers=[0, 1],
            future_numbers=observation[:3],
            observation_numbers=observation,
            returned_model="typesafe/jev-1.13-test",
            latency_ms=10,
            raw_response={"usage": {}},
        )

    early = job["metrics"]["observation"]["early_win_within_3"]
    assert early["eligible_signals"] == 2
    assert early["initial_hits_total"] == 3
    assert early["average_initial_hits_per_eligible_signal"] == 1.5
    assert early["signals_with_multiple_hits_within_3"] == 1
    assert early["multiple_hits_within_3_rate"] == 0.5
    assert early["initial_hit_count_distribution"] == {"1": 1, "2": 1, "3": 0}
    assert early["signals_with_hit_after_attempt_3"] == 2
    assert early["hit_after_attempt_3_rate"] == 1.0
    assert early["hits_after_attempt_3_total"] == 3
    assert early["average_hits_after_attempt_3_per_eligible_signal"] == 1.5
    assert early["hit_occurrences_after_attempt_3_by_attempt"]["4"] == 1
    assert early["hit_occurrences_after_attempt_3_by_attempt"]["5"] == 0
    assert early["hit_occurrences_after_attempt_3_by_attempt"]["6"] == 1
    assert early["hit_occurrences_after_attempt_3_by_attempt"]["7"] == 1
    assert early["hit_rate_after_attempt_3_by_attempt"]["4"] == 0.5
    assert early["hit_rate_after_attempt_3_by_attempt"]["5"] == 0.0
    assert early["first_hit_after_attempt_3_by_attempt"]["4"] == 1
    assert early["first_hit_after_attempt_3_by_attempt"]["7"] == 1


def test_sequential_mode_waits_for_primary_signal_resolution_but_observes_ten() -> None:
    job = _job(
        [5] * required_history_size(10, 50, 3),
        signal_mode="sequential",
        history_points=10,
    )
    first = record_success(
        job,
        step=0,
        selected_numbers=[0, 1],
        future_numbers=[5, 0, 7],
        observation_numbers=[5, 0, 7, 0, 8, 9, 0, 11, 12, 13],
        returned_model="typesafe/jev-1.13-test",
        latency_ms=10,
        raw_response={"usage": {}},
    )
    assert first["timeline_advance"] == 2
    assert first["observation"]["hit_attempts"] == [2, 4, 7]
    assert job["progress"]["next_step"] == 2

    second = record_success(
        job,
        step=2,
        selected_numbers=[0, 1],
        future_numbers=[5, 6, 7],
        observation_numbers=[5, 6, 7, 0, 8, 9, 0, 11, 12, 13],
        returned_model="typesafe/jev-1.13-test",
        latency_ms=10,
        raw_response={"usage": {}},
    )
    assert second["timeline_advance"] == 3
    assert second["observation"]["hit_attempts"] == [4, 7]
    assert job["progress"]["next_step"] == 5
    assert job["progress"]["attempted_calls"] == 2
    assert job["metrics"]["hits"] == 1
    assert job["metrics"]["misses"] == 1
    assert job["metrics"]["observation"]["total_hits"] == 5


def test_backtest_routes_run_one_paid_call_per_idempotent_step(monkeypatch, tmp_path) -> None:
    history = [5] * 50 + [0, 7, 8, 9] + [5] * 7
    collection = FakeCollection(history)
    jev_client = FakeBacktestJevClient()
    monkeypatch.setattr(settings, "jev_panel_user", "admin")
    monkeypatch.setattr(settings, "jev_panel_password", "secret")
    monkeypatch.setattr(settings, "jev_max_history", 10_000)
    monkeypatch.setattr(settings, "jev_max_body_bytes", 262_144)
    monkeypatch.setattr(settings, "jev_backtest_max_calls", 10)
    monkeypatch.setattr(settings, "jev_results_dir", str(tmp_path))
    app = FastAPI()
    app.include_router(jev_route.router)
    app.dependency_overrides[jev_route.get_jev_history_collection] = lambda: collection
    app.dependency_overrides[jev_route.get_jev_client] = lambda: jev_client
    client = TestClient(app)
    page = client.get("/jev", headers=AUTH_HEADERS)
    csrf = client.cookies.get("jev_csrf")
    paid_headers = {**AUTH_HEADERS, "X-CSRF-Token": csrf}

    started = client.post(
        "/api/jev/backtest/iniciar",
        headers=paid_headers,
        json={
            "history_points": 2,
            "context_numbers": 50,
            "chip_count": 2,
            "attempts": 3,
            "confirm_paid_run": True,
        },
    )
    assert page.status_code == 200
    assert started.status_code == 201
    body = started.json()
    assert "history_snapshot" not in body
    assert body["configuration"]["signal_mode"] == "overlapping"
    assert body["configuration"]["observation_horizon"] == 10
    backtest_id = body["backtest_id"]

    first = client.post(
        "/api/jev/backtest/proximo",
        headers=paid_headers,
        json={"backtest_id": backtest_id, "expected_step": 0},
    )
    assert first.status_code == 200
    assert first.json()["metrics"]["accuracy"] == 1.0
    assert first.json()["metrics"]["observation"]["signals"] == 1
    assert first.json()["usage"]["projected_cost_per_1000_calls_usd"] == 0.042
    assert set(jev_client.calls[0]["questions"]) == {NEXT_SPIN_CHOICE_KEY}
    assert jev_client.calls[0]["require_choice_confidence"] is False

    replay = client.post(
        "/api/jev/backtest/proximo",
        headers=paid_headers,
        json={"backtest_id": backtest_id, "expected_step": 0},
    )
    assert replay.json()["idempotent_replay"] is True
    assert len(jev_client.calls) == 1

    second = client.post(
        "/api/jev/backtest/proximo",
        headers=paid_headers,
        json={"backtest_id": backtest_id, "expected_step": 1},
    )
    assert second.json()["status"] == "completed"
    assert second.json()["metrics"]["hits"] == 1
    assert second.json()["metrics"]["misses"] == 1
    assert len(jev_client.calls) == 2
