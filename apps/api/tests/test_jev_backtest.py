from __future__ import annotations

import base64
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.core.config import settings
from api.routes import jev as jev_route
from api.services.jev_backtest import (
    build_backtest_job,
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


def _job(history):
    return build_backtest_job(
        backtest_id=str(uuid4()),
        history=history,
        history_points=2,
        context_numbers=50,
        chip_count=2,
        attempts=3,
        requested_model="typesafe/jev-1.13",
        created_at="2026-09-25T12:00:00Z",
        history_fetched_at="2026-09-25T12:00:00Z",
    )


def test_backtest_windows_never_include_future_in_jev_history() -> None:
    history = list(range(37)) + list(range(17))
    assert len(history) == required_history_size(2, 50, 3)
    job = _job(history)

    first_history, first_future = step_window(job, 0)
    second_history, second_future = step_window(job, 1)

    assert first_history == history[:50]
    assert first_future == history[50:53]
    assert second_history == history[1:51]
    assert second_future == history[51:54]


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

    job = _job([5] * 54)
    record_success(
        job,
        step=0,
        selected_numbers=selected[:2],
        future_numbers=[5, 12, 0],
        returned_model="typesafe/jev-1.13-test",
        latency_ms=10,
        raw_response={"usage": {"input_tokens": 1000, "cost": 0.000042}},
    )
    assert job["metrics"]["accuracy"] == 1.0
    assert job["metrics"]["hits_by_attempt"]["2"] == 1
    assert job["usage"]["projected_cost_per_1000_calls_usd"] == 0.042


def test_backtest_routes_run_one_paid_call_per_idempotent_step(monkeypatch, tmp_path) -> None:
    history = [5] * 50 + [0, 7, 8, 9]
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
    backtest_id = body["backtest_id"]

    first = client.post(
        "/api/jev/backtest/proximo",
        headers=paid_headers,
        json={"backtest_id": backtest_id, "expected_step": 0},
    )
    assert first.status_code == 200
    assert first.json()["metrics"]["accuracy"] == 1.0
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
