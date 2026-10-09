"""Protected HTML and JSON routes for manual Jev roulette analysis."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from api.core.config import settings
from api.core.runtime_db import history_coll
from api.helpers.active_roulettes import ACTIVE_ROULETTES
from api.schemas.jev import (
    GROUP_KEYS,
    JevAnalysisRequest,
    JevBacktestStartRequest,
    JevBacktestStepRequest,
    JevEvaluationRequest,
    JevInputError,
    JevRankingRequest,
    parse_roulette_text,
    validate_roulette_slug,
)
from api.services.jev_backtest import (
    OBSERVATION_HORIZON,
    JevBacktestError,
    JevBacktestNotFoundError,
    build_backtest_job,
    build_original_jev_step_payload,
    create_backtest,
    load_backtest,
    public_backtest,
    record_failure,
    record_success,
    required_history_size,
    save_backtest_step,
    select_chips,
    step_window,
)
from api.services.jev_confidence import (
    JevConfidenceError,
    assess_top_k_confidence,
    extract_top_k_features,
    load_persisted_confidence_samples,
)
from api.services.jev_adaptive_ranking import (
    JevAdaptiveRankingError,
    build_live_adaptive_report,
    extract_adaptive_snapshot,
    load_adaptive_samples,
    predict_adaptive_ranking,
    replay_adaptive_samples,
)
from api.services.jev_history_service import (
    ROULETTE_SLUG,
    JevHistorySourceError,
    fetch_recent_history,
    utc_iso,
)
from api.services.jev_meta_ranking import build_meta_rankings
from api.services.jev_openrouter import (
    JevConfigurationError,
    JevConnectionError,
    JevHTTPStatusError,
    JevInvalidResponseError,
    JevRequestTooLargeError,
    JevTimeoutError,
    OpenRouterJevClient,
    ValidatedJevResponse,
)
from api.services.jev_evaluation import JevEvaluationError, evaluate_saved_ranking
from api.services.jev_persistence import (
    JevInvalidRecordError,
    JevRecordNotFoundError,
    load_analysis,
    persist_analysis,
    persist_evaluation,
)
from api.services.jev_ranking import (
    NEXT_SPIN_CHOICE_KEY,
    NUMBER_KEYS,
    REGIME_CHOICE_KEY,
    ROULETTE_NUMBERS,
    SINGLE_NUMBER_BASELINE,
    SINGLE_SPIN_BASELINE,
    build_ranking_payload,
    number_key,
)
from api.services.jev_security import (
    CSRF_COOKIE,
    jev_http_error,
    new_csrf_token,
    request_id_for,
    require_jev_access,
    require_jev_csrf,
)
from api.services.jev_statistics import (
    FORECAST_HORIZON_SPINS,
    build_jev_questions,
    build_jev_state,
    calculate_all_group_statistics,
)


router = APIRouter(tags=["jev"])
API_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=API_DIR / "templates")
JEV_PAGE_ASSETS = (
    API_DIR / "static/css/jev.css",
    API_DIR / "static/js/pages/jev.js",
)
_POSITIVE_ASCII_INTEGER = re.compile(r"[0-9]+\Z", re.ASCII)
_backtest_locks: dict[str, asyncio.Lock] = {}


def _asset_version() -> str:
    digest = hashlib.sha256()
    for path in JEV_PAGE_ASSETS:
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def _max_history() -> int:
    return max(1, int(settings.jev_max_history))


def _max_body_bytes() -> int:
    return max(1, int(settings.jev_max_body_bytes))


def _max_backtest_calls() -> int:
    return max(1, int(settings.jev_backtest_max_calls))


def get_jev_history_collection():
    return history_coll


def get_jev_client() -> OpenRouterJevClient:
    return OpenRouterJevClient(
        api_key=settings.openrouter_api_key,
        model=settings.openrouter_model,
    )


def _headers(request: Request) -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "Pragma": "no-cache",
        "X-Request-ID": request_id_for(request),
    }


def _json_response(request: Request, content: dict[str, Any], status_code: int = 200) -> JSONResponse:
    return JSONResponse(content=content, status_code=status_code, headers=_headers(request))


async def _read_json_body(request: Request) -> Any:
    maximum = _max_body_bytes()
    content_length = request.headers.get("Content-Length")
    if content_length and content_length.isdigit() and int(content_length) > maximum:
        raise jev_http_error(
            request,
            status_code=413,
            code="jev_body_too_large",
            message=f"O corpo da solicitação excede o limite de {maximum} bytes.",
        )

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > maximum:
            raise jev_http_error(
                request,
                status_code=413,
                code="jev_body_too_large",
                message=f"O corpo da solicitação excede o limite de {maximum} bytes.",
            )
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise jev_http_error(
            request,
            status_code=400,
            code="jev_invalid_json",
            message="O corpo da solicitação não contém JSON válido.",
        ) from exc


def _map_openrouter_status(request: Request, status: int, provider_detail: str | None = None):
    if status in {401, 403}:
        return jev_http_error(
            request,
            status_code=502,
            code="openrouter_credentials_error",
            message="O OpenRouter recusou as credenciais configuradas no servidor.",
        )
    if status == 402:
        return jev_http_error(
            request,
            status_code=402,
            code="openrouter_balance_error",
            message="O OpenRouter informou saldo ou crédito insuficiente para a análise.",
        )
    if status == 429:
        return jev_http_error(
            request,
            status_code=429,
            code="openrouter_rate_limit",
            message="O limite de solicitações do OpenRouter foi atingido. Tente novamente mais tarde.",
        )
    if status == 413 or (status == 400 and "max_tokens_exceeded" in (provider_detail or "")):
        return jev_http_error(
            request,
            status_code=422,
            code="openrouter_context_too_large",
            message="O contexto excedeu o limite do Jev. Reduza a quantidade de números.",
        )
    return jev_http_error(
        request,
        status_code=502,
        code="openrouter_http_error",
        message=f"O OpenRouter recusou a análise (status externo {status}).",
    )


def _parse_history(request: Request, historico_texto: str) -> list[int]:
    try:
        history = parse_roulette_text(historico_texto)
    except JevInputError as exc:
        raise jev_http_error(
            request,
            status_code=422,
            code="jev_invalid_history",
            message=str(exc),
        ) from exc
    if not history:
        raise jev_http_error(
            request,
            status_code=422,
            code="jev_empty_history",
            message="O histórico não pode estar vazio.",
        )
    if len(history) > _max_history():
        raise jev_http_error(
            request,
            status_code=422,
            code="jev_history_too_long",
            message=f"O histórico excede o limite de {_max_history()} números.",
        )
    return history


async def _call_jev(
    request: Request,
    client: OpenRouterJevClient,
    *,
    state: dict[str, Any],
    questions: dict[str, Any],
) -> ValidatedJevResponse:
    try:
        return await client.analyze(state=state, questions=questions)
    except JevConfigurationError as exc:
        raise jev_http_error(
            request,
            status_code=503,
            code="openrouter_not_configured",
            message="A chave do OpenRouter não foi configurada no servidor.",
        ) from exc
    except JevTimeoutError as exc:
        raise jev_http_error(
            request,
            status_code=504,
            code="openrouter_timeout",
            message=(
                "A análise excedeu 30 segundos. O resultado e eventual custo remoto podem ser "
                "indeterminados; a solicitação não será reenviada automaticamente."
            ),
        ) from exc
    except JevConnectionError as exc:
        raise jev_http_error(
            request,
            status_code=502,
            code="openrouter_connection_error",
            message=(
                "A conexão com o OpenRouter foi interrompida. O resultado e eventual custo remoto "
                "podem ser indeterminados; a solicitação não será reenviada automaticamente."
            ),
        ) from exc
    except JevRequestTooLargeError as exc:
        raise jev_http_error(
            request,
            status_code=422,
            code="jev_payload_too_large",
            message=(
                "O contexto calculado excedeu o limite seguro do Jev. "
                "Reduza a quantidade de números analisados."
            ),
        ) from exc
    except JevHTTPStatusError as exc:
        logging.warning(
            "OpenRouter recusou a análise Jev status=%s request_id=%s detail=%s",
            exc.provider_status,
            request_id_for(request),
            exc.provider_detail or "não informado",
        )
        raise _map_openrouter_status(
            request,
            exc.provider_status,
            exc.provider_detail,
        ) from exc
    except JevInvalidResponseError as exc:
        raise jev_http_error(
            request,
            status_code=502,
            code="openrouter_invalid_response",
            message="O Jev retornou uma resposta inválida ou incompleta.",
        ) from exc


@router.get("/jev", response_class=HTMLResponse)
async def jev_page(request: Request, _user: str = Depends(require_jev_access)):
    csrf_token = new_csrf_token()
    maximum = _max_history()
    response = templates.TemplateResponse(
        request=request,
        name="jev.html",
        context={
            "asset_version": _asset_version(),
            "jev_roulettes": [{"slug": item["slug"], "name": item["name"]} for item in ACTIVE_ROULETTES],
            "jev_default_roulette_slug": ROULETTE_SLUG,
            "csrf_token": csrf_token,
            "max_history": maximum,
            "suggested_history": min(300, maximum),
            "max_backtest_calls": _max_backtest_calls(),
            "suggested_backtest_calls": min(1_000, _max_backtest_calls()),
            "jev_input_price_per_million": float(settings.jev_input_price_per_million),
        },
        headers=_headers(request),
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        secure=request.url.scheme == "https",
        httponly=False,
        samesite="strict",
        path="/",
    )
    return response


@router.get("/api/jev/historico")
async def jev_history(
    request: Request,
    quantidade: str = Query("300"),
    roulette_slug: str = Query(ROULETTE_SLUG),
    _user: str = Depends(require_jev_access),
    collection=Depends(get_jev_history_collection),
):
    try:
        validate_roulette_slug(roulette_slug)
    except ValueError as exc:
        raise jev_http_error(
            request, status_code=422, code="jev_invalid_roulette", message=str(exc)
        ) from exc
    maximum = _max_history()
    if not _POSITIVE_ASCII_INTEGER.fullmatch(quantidade):
        raise jev_http_error(
            request,
            status_code=422,
            code="jev_invalid_quantity",
            message="Quantidade deve ser um inteiro positivo.",
        )
    try:
        parsed_quantity = int(quantidade)
    except ValueError as exc:
        raise jev_http_error(
            request,
            status_code=422,
            code="jev_invalid_quantity",
            message=f"Quantidade deve estar entre 1 e {maximum}.",
        ) from exc
    if parsed_quantity < 1 or parsed_quantity > maximum:
        raise jev_http_error(
            request,
            status_code=422,
            code="jev_invalid_quantity",
            message=f"Quantidade deve estar entre 1 e {maximum}.",
        )
    try:
        result = await fetch_recent_history(collection, parsed_quantity, roulette_slug=roulette_slug)
    except JevHistorySourceError as exc:
        raise jev_http_error(
            request,
            status_code=503,
            code="jev_history_unavailable",
            message=str(exc),
        ) from exc
    return _json_response(request, result)


@router.post("/api/jev/analisar")
async def jev_analyze(
    request: Request,
    _user: str = Depends(require_jev_access),
    _csrf: None = Depends(require_jev_csrf),
    client: OpenRouterJevClient = Depends(get_jev_client),
):
    raw_body = await _read_json_body(request)
    try:
        payload = JevAnalysisRequest.model_validate(raw_body)
    except ValidationError as exc:
        raise jev_http_error(
            request,
            status_code=422,
            code="jev_invalid_input",
            message="Histórico ou grupos inválidos. Revise os seis grupos e use somente inteiros de 0 a 36.",
        ) from exc

    history = _parse_history(request, payload.historico_texto)

    groups = {group_id: list(payload.grupos[group_id]) for group_id in GROUP_KEYS}
    statistics = calculate_all_group_statistics(history, groups)
    state = build_jev_state(history, statistics, roulette_slug=payload.roulette_slug)
    questions = build_jev_questions(groups)
    jev_payload = {"model": client.model, "state": state, "questions": questions}

    analysis_id = str(uuid4())
    requested_at = utc_iso(datetime.now(timezone.utc))
    jev_response = await _call_jev(request, client, state=state, questions=questions)

    responded_at = utc_iso(datetime.now(timezone.utc))
    results = [
        {
            "grupo": group_id,
            "numeros": groups[group_id],
            "estimativa_jev_nao_validada": jev_response.probabilities[group_id],
            "probabilidade_base": statistics[group_id]["fair_independent_baseline"],
        }
        for group_id in GROUP_KEYS
    ]
    response_body: dict[str, Any] = {
        "analysis_id": analysis_id,
        "roulette_slug": payload.roulette_slug,
        "history_order": "oldest_to_newest",
        "historico_utilizado": history,
        "quantidade_analisada": len(history),
        "ultimo_numero": history[-1],
        "forecast_horizon_spins": FORECAST_HORIZON_SPINS,
        "modelo_solicitado": client.model,
        "modelo_retornado": jev_response.returned_model,
        "solicitado_em": requested_at,
        "respondido_em": responded_at,
        "latencia_ms": jev_response.latency_ms,
        "resultados": results,
        "resposta_jev": jev_response.raw,
        "avisos": [],
    }
    audit_record = {
        **response_body,
        "grupos": groups,
        "estatisticas": statistics,
        "payload_jev": jev_payload,
    }
    try:
        await persist_analysis(audit_record, settings.jev_results_dir)
    except Exception:
        logging.exception("Falha ao registrar análise Jev %s", analysis_id)
        response_body["avisos"].append(
            "A análise foi concluída, mas não foi possível gravar o registro privado no servidor."
        )

    return _json_response(request, response_body)


@router.post("/api/jev/backtest/iniciar")
async def jev_backtest_start(
    request: Request,
    _user: str = Depends(require_jev_access),
    _csrf: None = Depends(require_jev_csrf),
    collection=Depends(get_jev_history_collection),
    client: OpenRouterJevClient = Depends(get_jev_client),
):
    raw_body = await _read_json_body(request)
    try:
        payload = JevBacktestStartRequest.model_validate(raw_body)
    except ValidationError as exc:
        raise jev_http_error(
            request,
            status_code=422,
            code="jev_invalid_backtest_configuration",
            message="Configuração de backtest inválida.",
        ) from exc
    if not payload.confirm_paid_run:
        raise jev_http_error(
            request,
            status_code=422,
            code="jev_backtest_confirmation_required",
            message="Confirme que este backtest realizará chamadas pagas ao Jev.",
        )
    maximum_calls = _max_backtest_calls()
    if payload.history_points > maximum_calls:
        raise jev_http_error(
            request,
            status_code=422,
            code="jev_backtest_too_many_calls",
            message=f"O backtest aceita no máximo {maximum_calls} chamadas por execução.",
        )
    required = required_history_size(
        payload.history_points,
        payload.context_numbers,
        payload.attempts,
        OBSERVATION_HORIZON,
    )
    if required > _max_history():
        raise jev_http_error(
            request,
            status_code=422,
            code="jev_backtest_history_too_large",
            message=(
                f"A configuração exige {required} números, acima do limite de "
                f"{_max_history()}. Reduza pontos, contexto ou tentativas."
            ),
        )
    try:
        fetched = await fetch_recent_history(collection, required, roulette_slug=payload.roulette_slug)
    except JevHistorySourceError as exc:
        raise jev_http_error(
            request,
            status_code=503,
            code="jev_history_unavailable",
            message=str(exc),
        ) from exc
    history = fetched["historico"]
    if len(history) != required:
        raise jev_http_error(
            request,
            status_code=422,
            code="jev_backtest_insufficient_history",
            message=(
                f"A fonte retornou {len(history)} números, mas esta configuração "
                f"exige {required}."
            ),
        )
    backtest_id = str(uuid4())
    created_at = utc_iso(datetime.now(timezone.utc))
    try:
        job = build_backtest_job(
            backtest_id=backtest_id,
            history=history,
            history_points=payload.history_points,
            context_numbers=payload.context_numbers,
            chip_count=payload.chip_count,
            attempts=payload.attempts,
            signal_mode=payload.signal_mode,
            observation_horizon=OBSERVATION_HORIZON,
            requested_model=client.model,
            created_at=created_at,
            history_fetched_at=fetched["buscado_em"],
            roulette_slug=payload.roulette_slug,
        )
        await create_backtest(job, settings.jev_results_dir)
    except (JevBacktestError, OSError) as exc:
        logging.exception("Falha ao criar backtest Jev %s", backtest_id)
        raise jev_http_error(
            request,
            status_code=500,
            code="jev_backtest_create_error",
            message="Não foi possível criar o registro privado do backtest.",
        ) from exc
    return _json_response(request, public_backtest(job), status_code=201)


@router.get("/api/jev/backtest/{backtest_id}")
async def jev_backtest_status(
    backtest_id: str,
    request: Request,
    _user: str = Depends(require_jev_access),
):
    try:
        job = await load_backtest(backtest_id, settings.jev_results_dir)
    except JevBacktestNotFoundError as exc:
        raise jev_http_error(
            request,
            status_code=404,
            code="jev_backtest_not_found",
            message="O backtest informado não foi encontrado.",
        ) from exc
    except JevBacktestError as exc:
        raise jev_http_error(
            request,
            status_code=422,
            code="jev_invalid_backtest",
            message=str(exc),
        ) from exc
    return _json_response(request, public_backtest(job))


@router.post("/api/jev/backtest/proximo")
async def jev_backtest_next(
    request: Request,
    _user: str = Depends(require_jev_access),
    _csrf: None = Depends(require_jev_csrf),
    client: OpenRouterJevClient = Depends(get_jev_client),
):
    raw_body = await _read_json_body(request)
    try:
        payload = JevBacktestStepRequest.model_validate(raw_body)
    except ValidationError as exc:
        raise jev_http_error(
            request,
            status_code=422,
            code="jev_invalid_backtest_step",
            message="Identificador ou etapa de backtest inválidos.",
        ) from exc

    lock = _backtest_locks.setdefault(payload.backtest_id, asyncio.Lock())
    async with lock:
        try:
            job = await load_backtest(payload.backtest_id, settings.jev_results_dir)
        except JevBacktestNotFoundError as exc:
            raise jev_http_error(
                request,
                status_code=404,
                code="jev_backtest_not_found",
                message="O backtest informado não foi encontrado.",
            ) from exc
        except JevBacktestError as exc:
            raise jev_http_error(
                request,
                status_code=422,
                code="jev_invalid_backtest",
                message=str(exc),
            ) from exc

        next_step = int(job["progress"]["next_step"])
        if payload.expected_step < next_step:
            response = public_backtest(job)
            response["idempotent_replay"] = True
            return _json_response(request, response)
        if payload.expected_step > next_step:
            raise jev_http_error(
                request,
                status_code=409,
                code="jev_backtest_step_conflict",
                message=f"A próxima etapa esperada é {next_step}.",
            )
        if next_step >= int(job["progress"]["total_calls"]):
            return _json_response(request, public_backtest(job))

        try:
            history, future, observation = step_window(job, next_step)
            jev_payload = build_original_jev_step_payload(
                history, roulette_slug=job.get("roulette_slug", ROULETTE_SLUG)
            )
        except JevBacktestError as exc:
            raise jev_http_error(
                request,
                status_code=422,
                code="jev_invalid_backtest",
                message=str(exc),
            ) from exc

        try:
            jev_response = await client.analyze(
                state=jev_payload["state"],
                questions=jev_payload["questions"],
                require_choice_confidence=False,
            )
        except JevConfigurationError as exc:
            raise jev_http_error(
                request,
                status_code=503,
                code="openrouter_not_configured",
                message="A chave do OpenRouter não foi configurada no servidor.",
            ) from exc
        except JevRequestTooLargeError as exc:
            raise jev_http_error(
                request,
                status_code=422,
                code="jev_payload_too_large",
                message="O contexto calculado excedeu o limite seguro do Jev.",
            ) from exc
        except JevHTTPStatusError as exc:
            logging.warning(
                "OpenRouter recusou etapa de backtest Jev status=%s backtest_id=%s step=%s",
                exc.provider_status,
                payload.backtest_id,
                next_step,
            )
            raise _map_openrouter_status(
                request, exc.provider_status, exc.provider_detail
            ) from exc
        except (JevTimeoutError, JevConnectionError, JevInvalidResponseError) as exc:
            if isinstance(exc, JevTimeoutError):
                code = "openrouter_timeout"
                message = "A chamada excedeu 30 segundos; o custo remoto pode ser indeterminado."
            elif isinstance(exc, JevConnectionError):
                code = "openrouter_connection_error"
                message = "A conexão foi interrompida; o custo remoto pode ser indeterminado."
            else:
                code = "openrouter_invalid_response"
                message = (
                    "O Jev retornou uma resposta inválida ou incompleta. "
                    f"Detalhe de validação: {exc}"
                )
                logging.warning(
                    "Resposta inválida em etapa de backtest Jev "
                    "backtest_id=%s step=%s reason=%s",
                    payload.backtest_id,
                    next_step,
                    exc,
                )
            step_record = record_failure(job, step=next_step, code=code, message=message)
            await save_backtest_step(job, step_record, settings.jev_results_dir)
            return _json_response(request, public_backtest(job))

        try:
            next_choice = jev_response.choices[NEXT_SPIN_CHOICE_KEY]
            confidence_features = extract_top_k_features(
                next_choice.probabilities,
                jev_payload["walk_forward"],
                top_k=int(job["configuration"]["chip_count"]),
            )
            confidence_features["context_sha256"] = jev_payload["state"]["history_context"][
                "full_history_sha256"
            ]
            confidence_assessment = assess_top_k_confidence(
                confidence_features,
                job.get("confidence_samples", []),
                top_k=int(job["configuration"]["chip_count"]),
                attempts=int(job["configuration"]["attempts"]),
                model=str(job["requested_model"]),
                roulette_slug=job.get("roulette_slug", ROULETTE_SLUG),
            )
            adaptive_snapshot = extract_adaptive_snapshot(
                jev_payload, next_choice.probabilities
            )
            adaptive_prediction = predict_adaptive_ranking(
                adaptive_snapshot,
                job.get("adaptive_state"),
                top_k=int(job["configuration"]["chip_count"]),
            )
            selected = select_chips(
                next_choice.probabilities,
                int(job["configuration"]["chip_count"]),
            )
            step_record = record_success(
                job,
                step=next_step,
                selected_numbers=selected,
                future_numbers=future,
                observation_numbers=observation,
                returned_model=jev_response.returned_model,
                latency_ms=jev_response.latency_ms,
                raw_response=jev_response.raw,
                confidence_features=confidence_features,
                confidence_assessment=confidence_assessment,
                adaptive_snapshot=adaptive_snapshot,
                adaptive_prediction=adaptive_prediction,
            )
            await save_backtest_step(job, step_record, settings.jev_results_dir)
        except (
            JevBacktestError, JevConfidenceError, JevAdaptiveRankingError,
            KeyError, OSError,
        ) as exc:
            logging.exception(
                "Falha ao registrar etapa de backtest Jev %s/%s",
                payload.backtest_id,
                next_step,
            )
            raise jev_http_error(
                request,
                status_code=500,
                code="jev_backtest_step_error",
                message="A etapa foi chamada, mas não pôde ser registrada com segurança.",
            ) from exc
        return _json_response(request, public_backtest(job))


@router.post("/api/jev/ranking")
async def jev_ranking(
    request: Request,
    _user: str = Depends(require_jev_access),
    _csrf: None = Depends(require_jev_csrf),
    client: OpenRouterJevClient = Depends(get_jev_client),
):
    raw_body = await _read_json_body(request)
    try:
        payload = JevRankingRequest.model_validate(raw_body)
    except ValidationError as exc:
        raise jev_http_error(
            request,
            status_code=422,
            code="jev_invalid_input",
            message="Histórico inválido para o ranking. Use somente inteiros de 0 a 36.",
        ) from exc

    history = _parse_history(request, payload.historico_texto)
    ranking_payload = build_ranking_payload(history, roulette_slug=payload.roulette_slug)
    catalog = ranking_payload["catalog"]
    walk_forward = ranking_payload["walk_forward"]
    state = ranking_payload["state"]
    questions = ranking_payload["questions"]
    jev_payload = {"model": client.model, "state": state, "questions": questions}

    analysis_id = str(uuid4())
    requested_at = utc_iso(datetime.now(timezone.utc))
    jev_response = await _call_jev(request, client, state=state, questions=questions)
    responded_at = utc_iso(datetime.now(timezone.utc))

    candidates_by_target = {
        candidate["target_number"]: candidate for candidate in catalog["candidates"]
    }
    catalog_results = []
    for candidate in catalog["candidates"]:
        score_answer = jev_response.scores[candidate["question_id"]]
        catalog_results.append(
            {
                **candidate,
                "qualidade_jev": {
                    "score": score_answer.score,
                    "score_normalizado": score_answer.score / 3,
                    "confidence": score_answer.confidence,
                    "probabilities": score_answer.probabilities,
                    "legend": score_answer.legend,
                },
            }
        )
    pattern_quality_by_target = {
        item["target_number"]: item["qualidade_jev"] for item in catalog_results
    }
    relations_by_target = {
        relation["target_number"]: relation for relation in catalog["relations"]
    }

    next_choice = jev_response.choices[NEXT_SPIN_CHOICE_KEY]
    immediate_ranking = sorted(
        (
            {
                "numero": number,
                "probabilidade": next_choice.probabilities[str(number)],
                "probabilidade_base": SINGLE_SPIN_BASELINE,
                "diferenca_da_base": (
                    next_choice.probabilities[str(number)] - SINGLE_SPIN_BASELINE
                ),
            }
            for number in ROULETTE_NUMBERS
        ),
        key=lambda item: (-item["probabilidade"], item["numero"]),
    )
    for position, result in enumerate(immediate_ranking, start=1):
        result["posicao"] = position
    immediate_by_number = {item["numero"]: item for item in immediate_ranking}

    unordered_ranking: list[dict[str, Any]] = []
    for number in ROULETTE_NUMBERS:
        probability = jev_response.probabilities[number_key(number)]
        candidate = candidates_by_target.get(number)
        patterns = []
        if candidate is not None:
            patterns.append(
                {
                    "relation_id": candidate["relation_id"],
                    "classification": candidate["classification"],
                    "deterministic_strength": candidate["deterministic_strength"],
                    "qualidade_jev": next(
                        item["qualidade_jev"]
                        for item in catalog_results
                        if item["target_number"] == number
                    ),
                }
            )
        unordered_ranking.append(
            {
                "numero": number,
                "estimativa_jev_nao_validada": probability,
                "probabilidade_base": SINGLE_NUMBER_BASELINE,
                "diferenca_da_base": probability - SINGLE_NUMBER_BASELINE,
                "lift_jev_sobre_base": probability / SINGLE_NUMBER_BASELINE,
                "probabilidade_proxima_rodada": immediate_by_number[number]["probabilidade"],
                "posicao_proxima_rodada": immediate_by_number[number]["posicao"],
                "relacao_do_ultimo_numero": relations_by_target[number],
                "padroes_associados": patterns,
            }
        )
    ordered_ranking = sorted(
        unordered_ranking,
        key=lambda item: (-item["estimativa_jev_nao_validada"], item["numero"]),
    )
    for position, result in enumerate(ordered_ranking, start=1):
        result["posicao"] = position

    regime_choice = jev_response.choices[REGIME_CHOICE_KEY]
    meta = build_meta_rankings(
        walk_forward=walk_forward,
        jev_three_spin_probabilities={
            number: jev_response.probabilities[number_key(number)]
            for number in ROULETTE_NUMBERS
        },
        jev_next_spin_probabilities={
            number: next_choice.probabilities[str(number)] for number in ROULETTE_NUMBERS
        },
        pattern_quality_by_target=pattern_quality_by_target,
        regime=regime_choice.choice,
    )

    try:
        confidence_features = extract_top_k_features(
            next_choice.probabilities,
            walk_forward,
            top_k=payload.confidence_top_k,
        )
        confidence_features["context_sha256"] = state["history_context"]["full_history_sha256"]
        confidence_samples = await asyncio.to_thread(
            load_persisted_confidence_samples,
            settings.jev_results_dir,
            top_k=payload.confidence_top_k,
            attempts=payload.confidence_attempts,
            model=client.model,
            roulette_slug=payload.roulette_slug,
        )
        top_k_confidence = assess_top_k_confidence(
            confidence_features,
            confidence_samples,
            top_k=payload.confidence_top_k,
            attempts=payload.confidence_attempts,
            model=client.model,
            roulette_slug=payload.roulette_slug,
        )
    except (JevConfidenceError, OSError) as exc:
        logging.warning("Falha ao calcular confiança top-N analysis_id=%s: %s", analysis_id, exc)
        top_k_confidence = {
            "schema_version": "jev-top-k-confidence-v1",
            "roulette_slug": payload.roulette_slug,
            "top_k": payload.confidence_top_k,
            "attempts": payload.confidence_attempts,
            "selected_numbers": [
                item["numero"] for item in immediate_ranking[:payload.confidence_top_k]
            ],
            "sample_count": 0,
            "status": "unavailable",
            "decision": "no_entry",
            "calibrated_probability": None,
            "conservative_lower_bound": None,
            "reason": "A confiança não pôde ser calculada com segurança.",
        }

    try:
        adaptive_snapshot = extract_adaptive_snapshot(
            ranking_payload, next_choice.probabilities
        )
        adaptive_samples = await asyncio.to_thread(
            load_adaptive_samples,
            settings.jev_results_dir,
            model=client.model,
            roulette_slug=payload.roulette_slug,
        )
        adaptive_state, adaptive_training = await asyncio.to_thread(
            replay_adaptive_samples,
            adaptive_samples,
            top_k=payload.confidence_top_k,
        )
        adaptive_prediction = predict_adaptive_ranking(
            adaptive_snapshot,
            adaptive_state,
            top_k=payload.confidence_top_k,
        )
        adaptive_report = build_live_adaptive_report(
            adaptive_prediction, adaptive_training
        )
    except (JevAdaptiveRankingError, OSError) as exc:
        logging.warning("Falha ao calcular ranking adaptativo analysis_id=%s: %s", analysis_id, exc)
        adaptive_report = {
            "schema_version": "jev-adaptive-softmax-v1",
            "status": "unavailable",
            "reason": "O ranking adaptativo não pôde ser calculado com segurança.",
            "sample_count": 0,
            "top_k": payload.confidence_top_k,
            "jev_selected_numbers": [
                item["numero"] for item in immediate_ranking[:payload.confidence_top_k]
            ],
            "adaptive_selected_numbers": [],
            "maintained_numbers": [],
            "added_numbers": [],
            "removed_numbers": [],
            "adaptive_ranking": [],
            "training_metrics": {},
        }

    warnings: list[str] = []
    if not catalog_results:
        warnings.append(
            "Nenhuma relação A → B atingiu os critérios mínimos para avaliação de relevância; "
            "o ranking ainda contém os 37 números e suas evidências descritivas."
        )
    if not meta["signal"]["available"]:
        warnings.append(meta["signal"]["reason"])
    response_body: dict[str, Any] = {
        "analysis_id": analysis_id,
        "analysis_type": "number_ranking",
        "roulette_slug": payload.roulette_slug,
        "history_order": "oldest_to_newest",
        "historico_utilizado": history,
        "historico_contexto_enviado": state["history_context"],
        "quantidade_analisada": len(history),
        "ultimo_numero": history[-1],
        "forecast_horizon_spins": FORECAST_HORIZON_SPINS,
        "modelo_solicitado": client.model,
        "modelo_retornado": jev_response.returned_model,
        "solicitado_em": requested_at,
        "respondido_em": responded_at,
        "latencia_ms": jev_response.latency_ms,
        "ranking": ordered_ranking,
        "ranking_proxima_rodada": immediate_ranking,
        "ranking_meta": meta["ranking_tres_rodadas"],
        "ranking_meta_proxima_rodada": meta["ranking_proxima_rodada"],
        "sinal_meta": meta["signal"],
        "confianca_top_n": top_k_confidence,
        "ranking_adaptativo": adaptive_report,
        "validacao_walk_forward": {
            "version": walk_forward["version"],
            "method": walk_forward["method"],
            "minimum_training_support": walk_forward["minimum_training_support"],
            "maximum_recent_samples_per_model": walk_forward[
                "maximum_recent_samples_per_model"
            ],
        },
        "proxima_rodada": {
            "numero_escolhido": int(next_choice.choice),
            "confidence": next_choice.confidence,
            "probabilities": next_choice.probabilities,
        },
        "proxima_rodada_meta": {
            "numero_escolhido": meta["ranking_proxima_rodada"][0]["numero"],
            "probabilidade": meta["ranking_proxima_rodada"][0]["probabilidade_meta"],
            "confiabilidade_meta": meta["ranking_proxima_rodada"][0]["confiabilidade_meta"],
            "status_validacao": meta["ranking_proxima_rodada"][0]["status_validacao"],
        },
        "regime_atual": {
            "choice": regime_choice.choice,
            "confidence": regime_choice.confidence,
            "probabilities": regime_choice.probabilities,
        },
        "catalogo_padroes": catalog_results,
        "resposta_jev": jev_response.raw,
        "avisos": warnings,
    }
    audit_record = {
        **response_body,
        "catalogo_relacoes": catalog,
        "catalogo_walk_forward": walk_forward,
        "payload_jev": jev_payload,
        "expected_number_questions": list(NUMBER_KEYS),
    }
    try:
        await persist_analysis(audit_record, settings.jev_results_dir)
    except Exception:
        logging.exception("Falha ao registrar ranking Jev %s", analysis_id)
        response_body["avisos"].append(
            "O ranking foi concluído, mas não foi possível gravar o registro privado no servidor."
        )

    return _json_response(request, response_body)


@router.post("/api/jev/avaliar")
async def jev_evaluate(
    request: Request,
    _user: str = Depends(require_jev_access),
    _csrf: None = Depends(require_jev_csrf),
):
    raw_body = await _read_json_body(request)
    try:
        payload = JevEvaluationRequest.model_validate(raw_body)
    except ValidationError as exc:
        raise jev_http_error(
            request,
            status_code=422,
            code="jev_invalid_evaluation_input",
            message="Identificador ou resultados reais inválidos.",
        ) from exc

    try:
        actual_results = parse_roulette_text(
            payload.resultados_reais_texto, field_name="Resultados reais"
        )
    except JevInputError as exc:
        raise jev_http_error(
            request,
            status_code=422,
            code="jev_invalid_actual_results",
            message=str(exc),
        ) from exc
    if len(actual_results) != FORECAST_HORIZON_SPINS:
        raise jev_http_error(
            request,
            status_code=422,
            code="jev_invalid_actual_results_count",
            message="Informe exatamente os três resultados reais seguintes, na ordem.",
        )

    try:
        analysis = await load_analysis(payload.analysis_id, settings.jev_results_dir)
    except JevRecordNotFoundError as exc:
        raise jev_http_error(
            request,
            status_code=404,
            code="jev_ranking_not_found",
            message="O ranking informado não foi encontrado.",
        ) from exc
    except JevInvalidRecordError as exc:
        raise jev_http_error(
            request,
            status_code=422,
            code="jev_invalid_saved_ranking",
            message="O registro salvo não é um ranking válido.",
        ) from exc

    try:
        metrics = evaluate_saved_ranking(analysis, actual_results)
    except JevEvaluationError as exc:
        raise jev_http_error(
            request,
            status_code=422,
            code="jev_invalid_saved_ranking",
            message=str(exc),
        ) from exc

    evaluated_at = utc_iso(datetime.now(timezone.utc))
    evaluation_record = {
        "evaluation_id": str(uuid4()),
        "analysis_id": payload.analysis_id,
        "analysis_type": "number_ranking_evaluation",
        "roulette_slug": analysis.get("roulette_slug", ROULETTE_SLUG),
        "avaliado_em": evaluated_at,
        **metrics,
    }
    response_body = {**evaluation_record, "avisos": []}
    try:
        await persist_evaluation(evaluation_record, settings.jev_results_dir)
    except Exception:
        logging.exception("Falha ao registrar avaliação Jev %s", evaluation_record["evaluation_id"])
        response_body["avisos"].append(
            "A avaliação foi calculada, mas não foi possível gravar o registro privado no servidor."
        )
    return _json_response(request, response_body)
