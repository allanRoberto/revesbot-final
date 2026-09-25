"""Async OpenRouter System One client with strict Jev response validation."""
from __future__ import annotations

import asyncio
import json
import math
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import httpx

from api.schemas.jev import GROUP_KEYS


OPENROUTER_SYSTEM_ONE_URL = "https://openrouter.ai/api/v1/systemone"
REQUEST_TIMEOUT_SECONDS = 30.0
_SENSITIVE_RESPONSE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "access_token",
    "refresh_token",
    "secret",
    "password",
}


class JevOpenRouterError(RuntimeError):
    """Base class for safe, classified OpenRouter failures."""


class JevConfigurationError(JevOpenRouterError):
    pass


class JevTimeoutError(JevOpenRouterError):
    pass


class JevConnectionError(JevOpenRouterError):
    pass


class JevInvalidResponseError(JevOpenRouterError):
    pass


class JevHTTPStatusError(JevOpenRouterError):
    def __init__(self, provider_status: int) -> None:
        super().__init__(f"OpenRouter respondeu com HTTP {provider_status}")
        self.provider_status = provider_status


@dataclass(frozen=True)
class ValidatedJevResponse:
    raw: dict[str, Any]
    probabilities: dict[str, float]
    returned_model: str | None
    latency_ms: int


def _reject_nonstandard_number(value: str) -> None:
    raise ValueError(f"Número JSON não finito: {value}")


def _sanitize_external_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _sanitize_external_value(item)
            for key, item in value.items()
            if str(key).lower() not in _SENSITIVE_RESPONSE_KEYS
        }
    if isinstance(value, list):
        return [_sanitize_external_value(item) for item in value]
    return value


def validate_jev_response(
    payload: Any,
    *,
    latency_ms: int = 0,
    expected_noul_keys: Sequence[str] = GROUP_KEYS,
) -> ValidatedJevResponse:
    if not isinstance(payload, dict):
        raise JevInvalidResponseError("A resposta do Jev não é um objeto JSON.")
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        raise JevInvalidResponseError("A resposta do Jev não contém answers válido.")

    expected_keys = tuple(expected_noul_keys)
    if not expected_keys or len(expected_keys) != len(set(expected_keys)):
        raise JevInvalidResponseError("A lista de perguntas esperadas é inválida.")
    if set(answers) != set(expected_keys):
        raise JevInvalidResponseError("A resposta do Jev não corresponde às perguntas enviadas.")

    probabilities: dict[str, float] = {}
    for question_id in expected_keys:
        answer = answers.get(question_id)
        if not isinstance(answer, dict):
            raise JevInvalidResponseError(f"A resposta do Jev não contém {question_id}.")
        if answer.get("type") != "noul":
            raise JevInvalidResponseError(f"A resposta de {question_id} não é do tipo noul.")
        probability = answer.get("noul")
        if isinstance(probability, bool) or not isinstance(probability, (int, float)):
            raise JevInvalidResponseError(f"A probabilidade de {question_id} não é numérica.")
        numeric_probability = float(probability)
        if not math.isfinite(numeric_probability) or not 0 <= numeric_probability <= 1:
            raise JevInvalidResponseError(
                f"A probabilidade de {question_id} está fora do intervalo permitido."
            )
        probabilities[question_id] = numeric_probability

    returned_model = payload.get("model")
    if returned_model is not None and not isinstance(returned_model, str):
        raise JevInvalidResponseError("O identificador de modelo retornado é inválido.")

    sanitized = _sanitize_external_value(payload)
    return ValidatedJevResponse(
        raw=sanitized,
        probabilities=probabilities,
        returned_model=returned_model,
        latency_ms=latency_ms,
    )


class OpenRouterJevClient:
    """One-request Jev client. It never retries a paid inference."""

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key or ""
        self.model = model
        self._client = client

    async def _request(self, client: httpx.AsyncClient, payload: Mapping[str, Any]) -> httpx.Response:
        return await client.post(
            OPENROUTER_SYSTEM_ONE_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=dict(payload),
            follow_redirects=False,
        )

    async def analyze(
        self,
        *,
        state: Mapping[str, Any],
        questions: Mapping[str, Any],
    ) -> ValidatedJevResponse:
        if not self.api_key:
            raise JevConfigurationError("OPENROUTER_API_KEY não configurada.")
        if not self.model:
            raise JevConfigurationError("OPENROUTER_MODEL não configurado.")

        payload = {"model": self.model, "state": dict(state), "questions": dict(questions)}
        started = time.perf_counter()
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
                if self._client is not None:
                    response = await self._request(self._client, payload)
                else:
                    timeout = httpx.Timeout(REQUEST_TIMEOUT_SECONDS)
                    async with httpx.AsyncClient(timeout=timeout) as client:
                        response = await self._request(client, payload)
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise JevTimeoutError("A chamada ao OpenRouter excedeu o limite de tempo.") from exc
        except httpx.RequestError as exc:
            raise JevConnectionError("A conexão com o OpenRouter foi interrompida.") from exc

        latency_ms = round((time.perf_counter() - started) * 1000)
        if not 200 <= response.status_code < 300:
            raise JevHTTPStatusError(response.status_code)

        try:
            decoded = json.loads(
                response.content.decode("utf-8"),
                parse_constant=_reject_nonstandard_number,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise JevInvalidResponseError("O OpenRouter retornou JSON inválido.") from exc
        return validate_jev_response(
            decoded,
            latency_ms=latency_ms,
            expected_noul_keys=tuple(questions),
        )
