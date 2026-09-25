"""Async OpenRouter Decisions client with strict Jev response validation."""
from __future__ import annotations

import asyncio
import json
import math
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import httpx

from api.schemas.jev import GROUP_KEYS


OPENROUTER_DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
REQUEST_TIMEOUT_SECONDS = 30.0
MAX_JEV_REQUEST_BYTES = 64 * 1024
# Choice probabilities are currently returned rounded to hundredths. With 37
# roulette options the published values can legitimately total 0.99 or 1.01.
# A 2% cap accepts that presentation loss while still rejecting materially
# incomplete or malformed distributions; accepted values are normalized below.
DISTRIBUTION_SUM_ABS_TOLERANCE = 2e-2
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


class JevRequestTooLargeError(JevOpenRouterError):
    def __init__(self, request_bytes: int, maximum_bytes: int) -> None:
        super().__init__(
            f"O payload Jev tem {request_bytes} bytes; o limite seguro é {maximum_bytes}."
        )
        self.request_bytes = request_bytes
        self.maximum_bytes = maximum_bytes


class JevHTTPStatusError(JevOpenRouterError):
    def __init__(self, provider_status: int, provider_detail: str | None = None) -> None:
        super().__init__(f"OpenRouter respondeu com HTTP {provider_status}")
        self.provider_status = provider_status
        self.provider_detail = provider_detail


@dataclass(frozen=True)
class ValidatedChoiceAnswer:
    choice: str
    probabilities: dict[str, float]
    confidence: float | None


@dataclass(frozen=True)
class ValidatedScoreAnswer:
    score: float
    probabilities: dict[str, float]
    confidence: float
    legend: dict[str, Any]


@dataclass(frozen=True)
class ValidatedJevResponse:
    raw: dict[str, Any]
    probabilities: dict[str, float]
    returned_model: str | None
    latency_ms: int
    choices: dict[str, ValidatedChoiceAnswer] = field(default_factory=dict)
    scores: dict[str, ValidatedScoreAnswer] = field(default_factory=dict)


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


def _provider_error_detail(response: httpx.Response) -> str | None:
    try:
        decoded: Any = json.loads(
            response.content.decode("utf-8"),
            parse_constant=_reject_nonstandard_number,
        )
        sanitized = _sanitize_external_value(decoded)
        serialized = json.dumps(sanitized, ensure_ascii=False, allow_nan=False)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        return None
    if not serialized:
        return None
    return serialized[:1000]


def validate_jev_response(
    payload: Any,
    *,
    latency_ms: int = 0,
    expected_noul_keys: Sequence[str] = GROUP_KEYS,
    expected_questions: Mapping[str, Any] | None = None,
    require_choice_confidence: bool = True,
) -> ValidatedJevResponse:
    if not isinstance(payload, dict):
        raise JevInvalidResponseError("A resposta do Jev não é um objeto JSON.")
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        raise JevInvalidResponseError("A resposta do Jev não contém answers válido.")

    if expected_questions is None:
        expected_keys = tuple(expected_noul_keys)
        questions: dict[str, Any] = {
            question_id: {"type": "noul"} for question_id in expected_keys
        }
    else:
        questions = dict(expected_questions)
        expected_keys = tuple(questions)
    if not expected_keys or len(expected_keys) != len(set(expected_keys)):
        raise JevInvalidResponseError("A lista de perguntas esperadas é inválida.")
    if set(answers) != set(expected_keys):
        raise JevInvalidResponseError("A resposta do Jev não corresponde às perguntas enviadas.")

    probabilities: dict[str, float] = {}
    choices: dict[str, ValidatedChoiceAnswer] = {}
    scores: dict[str, ValidatedScoreAnswer] = {}
    for question_id in expected_keys:
        question = questions.get(question_id)
        if not isinstance(question, dict):
            raise JevInvalidResponseError(f"A pergunta esperada {question_id} é inválida.")
        question_type = question.get("type")
        answer = answers.get(question_id)
        if not isinstance(answer, dict):
            raise JevInvalidResponseError(f"A resposta do Jev não contém {question_id}.")
        if answer.get("type") != question_type:
            raise JevInvalidResponseError(
                f"A resposta de {question_id} não corresponde ao tipo enviado."
            )

        if question_type == "noul":
            probability = answer.get("noul")
            if isinstance(probability, bool) or not isinstance(probability, (int, float)):
                raise JevInvalidResponseError(f"A probabilidade de {question_id} não é numérica.")
            numeric_probability = float(probability)
            if not math.isfinite(numeric_probability) or not 0 <= numeric_probability <= 1:
                raise JevInvalidResponseError(
                    f"A probabilidade de {question_id} está fora do intervalo permitido."
                )
            probabilities[question_id] = numeric_probability
            continue

        if question_type == "choice":
            criteria = question.get("criteria")
            if not isinstance(criteria, dict) or not criteria:
                raise JevInvalidResponseError(f"Os critérios de {question_id} são inválidos.")
            option_keys = tuple(str(key) for key in criteria)
            choice = answer.get("choice")
            if not isinstance(choice, str) or choice not in option_keys:
                raise JevInvalidResponseError(f"A escolha de {question_id} é inválida.")
            answer_probabilities = _validate_distribution(
                answer.get("probabilities"), option_keys, question_id
            )
            raw_confidence = answer.get("confidence")
            confidence = (
                _validate_unit_interval(raw_confidence, question_id, "confiança")
                if raw_confidence is not None
                else None
            )
            if require_choice_confidence and confidence is None:
                raise JevInvalidResponseError(
                    f"A confiança de {question_id} não foi retornada."
                )
            choices[question_id] = ValidatedChoiceAnswer(
                choice=choice,
                probabilities=answer_probabilities,
                confidence=confidence,
            )
            continue

        if question_type == "score":
            criteria = question.get("criteria")
            if not isinstance(criteria, list) or not 2 <= len(criteria) <= 10:
                raise JevInvalidResponseError(f"Os critérios de {question_id} são inválidos.")
            score = answer.get("score")
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                raise JevInvalidResponseError(f"O score de {question_id} não é numérico.")
            numeric_score = float(score)
            if not math.isfinite(numeric_score) or not 0 <= numeric_score <= len(criteria) - 1:
                raise JevInvalidResponseError(f"O score de {question_id} está fora do intervalo.")
            level_keys = tuple(str(index) for index in range(len(criteria)))
            answer_probabilities = _validate_distribution(
                answer.get("probabilities"), level_keys, question_id
            )
            confidence = _validate_unit_interval(
                answer.get("confidence"), question_id, "confiança"
            )
            legend = answer.get("legend")
            if not isinstance(legend, dict):
                raise JevInvalidResponseError(f"A legenda de {question_id} é inválida.")
            scores[question_id] = ValidatedScoreAnswer(
                score=numeric_score,
                probabilities=answer_probabilities,
                confidence=confidence,
                legend=_sanitize_external_value(
                    {str(key): value for key, value in legend.items()}
                ),
            )
            continue

        raise JevInvalidResponseError(f"O tipo da pergunta {question_id} não é suportado.")

    returned_model = payload.get("model")
    if returned_model is not None and not isinstance(returned_model, str):
        raise JevInvalidResponseError("O identificador de modelo retornado é inválido.")

    sanitized = _sanitize_external_value(payload)
    return ValidatedJevResponse(
        raw=sanitized,
        probabilities=probabilities,
        returned_model=returned_model,
        latency_ms=latency_ms,
        choices=choices,
        scores=scores,
    )


def _validate_unit_interval(value: Any, question_id: str, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JevInvalidResponseError(f"A {label} de {question_id} não é numérica.")
    numeric = float(value)
    if not math.isfinite(numeric) or not 0 <= numeric <= 1:
        raise JevInvalidResponseError(f"A {label} de {question_id} está fora do intervalo.")
    return numeric


def _validate_distribution(
    value: Any, expected_keys: Sequence[str], question_id: str
) -> dict[str, float]:
    if not isinstance(value, dict) or set(value) != set(expected_keys):
        raise JevInvalidResponseError(
            f"A distribuição de probabilidades de {question_id} é inválida."
        )
    distribution = {
        key: _validate_unit_interval(value[key], question_id, f"probabilidade {key}")
        for key in expected_keys
    }
    total = sum(distribution.values())
    if not math.isclose(
        total,
        1.0,
        rel_tol=0.0,
        abs_tol=DISTRIBUTION_SUM_ABS_TOLERANCE,
    ):
        raise JevInvalidResponseError(
            f"A distribuição de probabilidades de {question_id} soma {total:.6f}, não 1."
        )
    # The Decisions API can round each option independently. Keep the strict
    # per-option/key checks above, but normalize the bounded rounding drift so
    # ranking comparisons use a proper distribution.
    if total != 1.0:
        distribution = {key: probability / total for key, probability in distribution.items()}
    return distribution


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

    async def _request(self, client: httpx.AsyncClient, payload: bytes) -> httpx.Response:
        return await client.post(
            OPENROUTER_DECISIONS_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            content=payload,
            follow_redirects=False,
        )

    async def analyze(
        self,
        *,
        state: Mapping[str, Any],
        questions: Mapping[str, Any],
        require_choice_confidence: bool = True,
    ) -> ValidatedJevResponse:
        if not self.api_key:
            raise JevConfigurationError("OPENROUTER_API_KEY não configurada.")
        if not self.model:
            raise JevConfigurationError("OPENROUTER_MODEL não configurado.")

        payload = {"model": self.model, "state": dict(state), "questions": dict(questions)}
        encoded_payload = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded_payload) > MAX_JEV_REQUEST_BYTES:
            raise JevRequestTooLargeError(len(encoded_payload), MAX_JEV_REQUEST_BYTES)
        started = time.perf_counter()
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
                if self._client is not None:
                    response = await self._request(self._client, encoded_payload)
                else:
                    timeout = httpx.Timeout(REQUEST_TIMEOUT_SECONDS)
                    async with httpx.AsyncClient(timeout=timeout) as client:
                        response = await self._request(client, encoded_payload)
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise JevTimeoutError("A chamada ao OpenRouter excedeu o limite de tempo.") from exc
        except httpx.RequestError as exc:
            raise JevConnectionError("A conexão com o OpenRouter foi interrompida.") from exc

        latency_ms = round((time.perf_counter() - started) * 1000)
        if not 200 <= response.status_code < 300:
            raise JevHTTPStatusError(
                response.status_code,
                provider_detail=_provider_error_detail(response),
            )

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
            expected_questions=questions,
            require_choice_confidence=require_choice_confidence,
        )
