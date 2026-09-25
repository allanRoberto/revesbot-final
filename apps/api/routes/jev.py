"""Protected HTML and JSON routes for manual Jev roulette analysis."""
from __future__ import annotations

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
from api.schemas.jev import (
    GROUP_KEYS,
    JevAnalysisRequest,
    JevEvaluationRequest,
    JevInputError,
    JevRankingRequest,
    parse_roulette_text,
)
from api.services.jev_history_service import (
    ROULETTE_SLUG,
    JevHistorySourceError,
    fetch_recent_history,
    utc_iso,
)
from api.services.jev_openrouter import (
    JevConfigurationError,
    JevConnectionError,
    JevHTTPStatusError,
    JevInvalidResponseError,
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


def _asset_version() -> str:
    digest = hashlib.sha256()
    for path in JEV_PAGE_ASSETS:
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def _max_history() -> int:
    return max(1, int(settings.jev_max_history))


def _max_body_bytes() -> int:
    return max(1, int(settings.jev_max_body_bytes))


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


def _map_openrouter_status(request: Request, status: int):
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
    if status == 413:
        return jev_http_error(
            request,
            status_code=422,
            code="openrouter_context_too_large",
            message="O contexto excedeu o limite do provedor. Reduza a quantidade de números.",
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
    except JevHTTPStatusError as exc:
        raise _map_openrouter_status(request, exc.provider_status) from exc
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
            "csrf_token": csrf_token,
            "max_history": maximum,
            "suggested_history": min(300, maximum),
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
    _user: str = Depends(require_jev_access),
    collection=Depends(get_jev_history_collection),
):
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
        result = await fetch_recent_history(collection, parsed_quantity)
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
    state = build_jev_state(history, statistics)
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
        "roulette_slug": ROULETTE_SLUG,
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
    ranking_payload = build_ranking_payload(history)
    catalog = ranking_payload["catalog"]
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

    warnings: list[str] = []
    if not catalog_results:
        warnings.append(
            "Nenhuma relação A → B atingiu os critérios mínimos para avaliação de relevância; "
            "o ranking ainda contém os 37 números e suas evidências descritivas."
        )
    regime_choice = jev_response.choices[REGIME_CHOICE_KEY]
    response_body: dict[str, Any] = {
        "analysis_id": analysis_id,
        "analysis_type": "number_ranking",
        "roulette_slug": ROULETTE_SLUG,
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
        "proxima_rodada": {
            "numero_escolhido": int(next_choice.choice),
            "confidence": next_choice.confidence,
            "probabilities": next_choice.probabilities,
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
