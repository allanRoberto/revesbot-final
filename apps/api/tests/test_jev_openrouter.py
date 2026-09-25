from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from api.schemas.jev import GROUP_KEYS
from api.services.jev_openrouter import (
    OPENROUTER_SYSTEM_ONE_URL,
    JevConfigurationError,
    JevHTTPStatusError,
    JevInvalidResponseError,
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


def test_client_uses_system_one_once_with_six_questions_and_preserves_metadata() -> None:
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
    assert str(calls[0].url) == OPENROUTER_SYSTEM_ONE_URL
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
        return httpx.Response(429, json={"error": "limited"})

    with pytest.raises(JevHTTPStatusError) as status_error:
        asyncio.run(exercise(status_handler))
    assert status_error.value.provider_status == 429
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
