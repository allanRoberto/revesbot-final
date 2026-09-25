from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from api.schemas.jev import GROUP_KEYS
from api.services.jev_openrouter import (
    MAX_JEV_REQUEST_BYTES,
    OPENROUTER_DECISIONS_URL,
    JevConfigurationError,
    JevHTTPStatusError,
    JevInvalidResponseError,
    JevRequestTooLargeError,
    JevTimeoutError,
    OpenRouterJevClient,
    validate_jev_response,
)


def _response_payload(values=None):
    values = values or [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
    return {
        "id": "gen-1",
        "model": "typesafe/jev-1.13-20260917",
        "provider": "TypeSafe",
        "answers": {
            group_id: {"type": "noul", "noul": values[index]}
            for index, group_id in enumerate(GROUP_KEYS)
        },
        "usage": {"input_tokens": 50, "output_tokens": 6, "cost": 0},
    }


def test_client_uses_decisions_api_once_with_six_questions_and_preserves_metadata() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=_response_payload())

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport_client:
            client = OpenRouterJevClient(
                api_key="test-secret", model="typesafe/jev-1.13", client=transport_client
            )
            return await client.analyze(
                state={"history": [1, 2, 3]},
                questions={group_id: {"type": "noul"} for group_id in GROUP_KEYS},
            )

    result = asyncio.run(run())
    assert len(calls) == 1
    assert str(calls[0].url) == OPENROUTER_DECISIONS_URL
    assert str(calls[0].url) == "https://openrouter.ai/api/alpha/decisions"
    assert calls[0].headers["authorization"] == "Bearer test-secret"
    sent = json.loads(calls[0].content)
    assert sent["model"] == "typesafe/jev-1.13"
    assert list(sent["questions"]) == list(GROUP_KEYS)
    assert list(result.probabilities.values()) == [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
    assert result.raw["provider"] == "TypeSafe"
    assert result.raw["usage"]["cost"] == 0
    assert result.returned_model == "typesafe/jev-1.13-20260917"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["answers"].pop("grupo_6"),
        lambda payload: payload["answers"]["grupo_1"].update(type="choice"),
        lambda payload: payload["answers"]["grupo_1"].update(noul=True),
        lambda payload: payload["answers"]["grupo_1"].update(noul="0.5"),
        lambda payload: payload["answers"]["grupo_1"].update(noul=float("nan")),
        lambda payload: payload["answers"]["grupo_1"].update(noul=float("inf")),
        lambda payload: payload["answers"]["grupo_1"].update(noul=-0.01),
        lambda payload: payload["answers"]["grupo_1"].update(noul=1.01),
    ],
)
def test_response_validation_rejects_partial_or_invalid_answers(mutate) -> None:
    payload = _response_payload()
    mutate(payload)
    with pytest.raises(JevInvalidResponseError):
        validate_jev_response(payload)


def test_response_sanitizer_removes_unexpected_secret_fields_only() -> None:
    payload = _response_payload()
    payload["authorization"] = "Bearer leaked"
    payload["usage"]["input_tokens"] = 123
    validated = validate_jev_response(payload)
    assert "authorization" not in validated.raw
    assert validated.raw["usage"]["input_tokens"] == 123


def test_absent_model_and_cost_are_not_invented() -> None:
    payload = _response_payload()
    payload.pop("model")
    payload["usage"].pop("cost")
    validated = validate_jev_response(payload)
    assert validated.returned_model is None
    assert "model" not in validated.raw
    assert "cost" not in validated.raw["usage"]


def test_http_error_invalid_json_and_timeout_have_no_retry() -> None:
    async def exercise(handler):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport_client:
            client = OpenRouterJevClient(api_key="key", model="typesafe/jev-1.13", client=transport_client)
            return await client.analyze(state={"history": [1]}, questions={group_id: {} for group_id in GROUP_KEYS})

    status_calls = 0

    def status_handler(_request):
        nonlocal status_calls
        status_calls += 1
        return httpx.Response(
            429,
            json={
                "error": {"message": "limited", "authorization": "Bearer leaked"}
            },
        )

    with pytest.raises(JevHTTPStatusError) as status_error:
        asyncio.run(exercise(status_handler))
    assert status_error.value.provider_status == 429
    assert "limited" in status_error.value.provider_detail
    assert "leaked" not in status_error.value.provider_detail
    assert status_calls == 1

    with pytest.raises(JevInvalidResponseError):
        asyncio.run(exercise(lambda _request: httpx.Response(200, content=b"not-json")))

    timeout_calls = 0

    def timeout_handler(request):
        nonlocal timeout_calls
        timeout_calls += 1
        raise httpx.ReadTimeout("timeout", request=request)

    with pytest.raises(JevTimeoutError):
        asyncio.run(exercise(timeout_handler))
    assert timeout_calls == 1


def test_missing_key_stops_before_any_request() -> None:
    client = OpenRouterJevClient(api_key=None, model="typesafe/jev-1.13")
    with pytest.raises(JevConfigurationError):
        asyncio.run(client.analyze(state={}, questions={}))


def test_oversized_payload_stops_before_any_request() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=_response_payload())

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport_client:
            client = OpenRouterJevClient(
                api_key="key", model="typesafe/jev-1.13", client=transport_client
            )
            await client.analyze(
                state={"oversized": "x" * MAX_JEV_REQUEST_BYTES},
                questions={group_id: {"type": "noul"} for group_id in GROUP_KEYS},
            )

    with pytest.raises(JevRequestTooLargeError) as error:
        asyncio.run(run())
    assert error.value.request_bytes > error.value.maximum_bytes
    assert calls == []


def test_client_validates_the_dynamic_ranking_question_set_exactly() -> None:
    question_keys = ("numero_00", "numero_01", "relacao_17_00")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "answers": {
                    key: {"type": "noul", "noul": (index + 1) / 10}
                    for index, key in enumerate(question_keys)
                }
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport_client:
            client = OpenRouterJevClient(
                api_key="key", model="typesafe/jev-1.13", client=transport_client
            )
            return await client.analyze(
                state={"latest": 17},
                questions={key: {"type": "noul"} for key in question_keys},
            )

    result = asyncio.run(run())
    assert tuple(result.probabilities) == question_keys

    extra = _response_payload()
    extra["answers"]["unexpected"] = {"type": "noul", "noul": 0.5}
    with pytest.raises(JevInvalidResponseError):
        validate_jev_response(extra)


def test_response_validation_accepts_choice_score_and_noul_together() -> None:
    questions = {
        "numero_00": {"type": "noul"},
        "proxima_rodada": {"type": "choice", "criteria": {"0": "zero", "1": "one"}},
        "relacao_17_00": {"type": "score", "criteria": ["weak", "medium", "strong"]},
    }
    payload = {
        "answers": {
            "numero_00": {"type": "noul", "noul": 0.2},
            "proxima_rodada": {
                "type": "choice",
                "choice": "0",
                "confidence": 0.7,
                "probabilities": {"0": 0.6, "1": 0.4},
            },
            "relacao_17_00": {
                "type": "score",
                "score": 1.5,
                "confidence": 0.8,
                "probabilities": {"0": 0.1, "1": 0.3, "2": 0.6},
                "legend": {"0": "weak", "1": "medium", "2": "strong"},
            },
        }
    }
    result = validate_jev_response(payload, expected_questions=questions)
    assert result.probabilities == {"numero_00": 0.2}
    assert result.choices["proxima_rodada"].choice == "0"
    assert result.scores["relacao_17_00"].score == 1.5


def test_choice_confidence_can_be_optional_for_probability_only_consumers() -> None:
    questions = {
        "proxima_rodada": {"type": "choice", "criteria": {"0": "zero", "1": "one"}}
    }
    payload = {
        "answers": {
            "proxima_rodada": {
                "type": "choice",
                "choice": "0",
                "probabilities": {"0": 0.6, "1": 0.4},
            }
        }
    }

    with pytest.raises(JevInvalidResponseError, match="confiança"):
        validate_jev_response(payload, expected_questions=questions)

    result = validate_jev_response(
        payload,
        expected_questions=questions,
        require_choice_confidence=False,
    )
    assert result.choices["proxima_rodada"].confidence is None
    assert result.choices["proxima_rodada"].probabilities == {"0": 0.6, "1": 0.4}


def test_choice_distribution_normalizes_only_small_rounding_drift() -> None:
    questions = {
        "proxima_rodada": {"type": "choice", "criteria": {"0": "zero", "1": "one"}}
    }
    payload = {
        "answers": {
            "proxima_rodada": {
                "type": "choice",
                "choice": "0",
                "confidence": 0.7,
                "probabilities": {"0": 0.6004, "1": 0.4},
            }
        }
    }

    result = validate_jev_response(payload, expected_questions=questions)
    assert sum(result.choices["proxima_rodada"].probabilities.values()) == pytest.approx(1.0)

    payload["answers"]["proxima_rodada"]["probabilities"] = {"0": 0.61, "1": 0.4}
    with pytest.raises(JevInvalidResponseError, match="soma 1.010000"):
        validate_jev_response(payload, expected_questions=questions)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["answers"]["proxima_rodada"]["probabilities"].update({"0": 0.8}),
        lambda payload: payload["answers"]["proxima_rodada"].update(choice="2"),
        lambda payload: payload["answers"]["relacao_17_00"].update(score=4),
        lambda payload: payload["answers"]["relacao_17_00"]["probabilities"].pop("3"),
    ],
)
def test_response_validation_rejects_invalid_choice_or_score(mutate) -> None:
    questions = {
        "proxima_rodada": {"type": "choice", "criteria": {"0": "zero", "1": "one"}},
        "relacao_17_00": {"type": "score", "criteria": ["a", "b", "c", "d"]},
    }
    payload = {
        "answers": {
            "proxima_rodada": {
                "type": "choice",
                "choice": "0",
                "confidence": 0.7,
                "probabilities": {"0": 0.6, "1": 0.4},
            },
            "relacao_17_00": {
                "type": "score",
                "score": 2.5,
                "confidence": 0.8,
                "probabilities": {"0": 0.1, "1": 0.2, "2": 0.3, "3": 0.4},
                "legend": {"0": "a", "1": "b", "2": "c", "3": "d"},
            },
        }
    }
    mutate(payload)
    with pytest.raises(JevInvalidResponseError):
        validate_jev_response(payload, expected_questions=questions)
