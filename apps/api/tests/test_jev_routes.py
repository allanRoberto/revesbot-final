from __future__ import annotations

import base64
import re
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.core.config import settings
from api.routes import jev as jev_route
from api.schemas.jev import GROUP_KEYS
from api.services.jev_openrouter import (
    JevHTTPStatusError,
    JevRequestTooLargeError,
    ValidatedChoiceAnswer,
    ValidatedJevResponse,
    ValidatedScoreAnswer,
)
from api.services.jev_ranking import (
    NEXT_SPIN_CHOICE_KEY,
    NUMBER_KEYS,
    REGIME_CHOICE_KEY,
)


AUTHORIZATION = "Basic " + base64.b64encode(b"admin:secret").decode("ascii")
AUTH_HEADERS = {"Authorization": AUTHORIZATION}


def _groups() -> dict[str, list[int]]:
    return {
        "grupo_1": [1, 2, 3, 4, 5, 6],
        "grupo_2": [7, 8, 9, 10, 11, 12],
        "grupo_3": [13, 14, 15, 16, 17, 18],
        "grupo_4": [19, 20, 21, 22, 23, 24],
        "grupo_5": [25, 26, 27, 28, 29, 30],
        "grupo_6": [31, 32, 33, 34, 35, 36],
    }


def _payload(history: str = "1, 7, 0, 2, 8, 3") -> dict:
    return {
        "history_order": "oldest_to_newest",
        "historico_texto": history,
        "grupos": _groups(),
    }


class FakeCursor:
    def __init__(self, documents):
        self.documents = documents

    def sort(self, *_args, **_kwargs):
        return self

    def limit(self, amount):
        self.documents = self.documents[:amount]
        return self

    async def to_list(self, length=None):
        return self.documents[:length]


class FakeCollection:
    def __init__(self, documents, *, roulette_slug="pragmatic-auto-roulette"):
        self.documents = list(documents)
        self.roulette_slug = roulette_slug
        self.calls = 0

    def find(self, query, projection):
        self.calls += 1
        assert query == {"roulette_id": self.roulette_slug}
        assert projection == {"value": 1, "timestamp": 1}
        return FakeCursor(list(self.documents))


class FakeJevClient:
    model = "typesafe/jev-1.13"

    def __init__(self):
        self.calls = []

    async def analyze(self, *, state, questions):
        self.calls.append({"state": state, "questions": questions})
        raw = {
            "id": "gen-test",
            "model": "typesafe/jev-1.13-returned",
            "provider": "TypeSafe",
            "answers": {
                group_id: {"type": "noul", "noul": (index + 1) / 10}
                for index, group_id in enumerate(GROUP_KEYS)
            },
            "usage": {"cost": 0},
        }
        return ValidatedJevResponse(
            raw=raw,
            probabilities={group_id: (index + 1) / 10 for index, group_id in enumerate(GROUP_KEYS)},
            returned_model="typesafe/jev-1.13-returned",
            latency_ms=12,
        )


class FakeRankingJevClient:
    model = "typesafe/jev-1.13"

    def __init__(self):
        self.calls = []

    async def analyze(self, *, state, questions):
        self.calls.append({"state": state, "questions": questions})
        probabilities = {
            question_id: (
                0.99
                if question_id == "numero_00"
                else 0.50 - int(question_id.removeprefix("numero_")) / 1000
            )
            for question_id in NUMBER_KEYS
        }
        next_probabilities = {str(number): (0.20 if number == 0 else 0.80 / 36) for number in range(37)}
        regime_probabilities = {
            "neutral": 0.1,
            "frequency_concentration": 0.1,
            "transition_driven": 0.6,
            "gap_driven": 0.1,
            "unstable": 0.1,
        }
        score_keys = [key for key, question in questions.items() if question["type"] == "score"]
        scores = {
            key: ValidatedScoreAnswer(
                score=2.4,
                confidence=0.8,
                probabilities={"0": 0.05, "1": 0.10, "2": 0.35, "3": 0.50},
                legend={"0": "insuficiente", "1": "fraca", "2": "consistente", "3": "forte"},
            )
            for key in score_keys
        }
        return ValidatedJevResponse(
            raw={
                "id": "gen-ranking-test",
                "model": "typesafe/jev-1.13-returned",
                "provider": "TypeSafe",
                "answers": {key: {"type": "noul", "noul": value} for key, value in probabilities.items()},
                "usage": {"cost": 0},
            },
            probabilities=probabilities,
            returned_model="typesafe/jev-1.13-returned",
            latency_ms=18,
            choices={
                NEXT_SPIN_CHOICE_KEY: ValidatedChoiceAnswer(
                    choice="0", confidence=0.7, probabilities=next_probabilities
                ),
                REGIME_CHOICE_KEY: ValidatedChoiceAnswer(
                    choice="transition_driven", confidence=0.6, probabilities=regime_probabilities
                ),
            },
            scores=scores,
        )


class OversizedPayloadJevClient:
    model = "typesafe/jev-1.13"

    async def analyze(self, *, state, questions):
        raise JevRequestTooLargeError(70_000, 65_536)


class ProviderContextLimitJevClient:
    model = "typesafe/jev-1.13"

    async def analyze(self, *, state, questions):
        raise JevHTTPStatusError(
            400,
            provider_detail='{"error":{"message":"max_tokens_exceeded"}}',
        )


def _app(monkeypatch, *, collection=None, jev_client=None, public_access=False) -> FastAPI:
    monkeypatch.setattr(settings, "jev_public_access", public_access)
    monkeypatch.setattr(settings, "jev_panel_user", "admin")
    monkeypatch.setattr(settings, "jev_panel_password", "secret")
    monkeypatch.setattr(settings, "jev_max_history", 10_000)
    monkeypatch.setattr(settings, "jev_max_body_bytes", 262_144)
    monkeypatch.setattr(settings, "openrouter_api_key", "not-used-in-tests")
    app = FastAPI()
    app.include_router(jev_route.router)
    if collection is not None:
        app.dependency_overrides[jev_route.get_jev_history_collection] = lambda: collection
    if jev_client is not None:
        app.dependency_overrides[jev_route.get_jev_client] = lambda: jev_client
    return app


def _csrf(client: TestClient) -> str:
    response = client.get("/jev", headers=AUTH_HEADERS)
    assert response.status_code == 200
    return client.cookies.get("jev_csrf")


def test_page_is_protected_empty_and_does_not_call_history_or_openrouter(monkeypatch) -> None:
    collection = FakeCollection([])
    jev_client = FakeJevClient()
    client = TestClient(_app(monkeypatch, collection=collection, jev_client=jev_client))

    assert client.get("/jev").status_code == 401
    response = client.get("/jev", headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert 'id="history-input"' in response.text
    assert 'id="reverse-history"' in response.text
    assert re.search(r'<textarea\b[^>]*\bid="history-input"', response.text)
    assert ">1, 7, 0" not in response.text
    assert "OPENROUTER_API_KEY" not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert collection.calls == 0
    assert jev_client.calls == []


def test_missing_panel_configuration_blocks_only_feature_routes(monkeypatch) -> None:
    monkeypatch.setattr(settings, "jev_public_access", False)
    monkeypatch.setattr(settings, "jev_panel_user", None)
    monkeypatch.setattr(settings, "jev_panel_password", None)
    app = FastAPI()
    app.include_router(jev_route.router)
    app.get("/health")(lambda: {"ok": True})
    client = TestClient(app)

    blocked = client.get("/jev")
    assert blocked.status_code == 503
    assert blocked.json()["detail"]["code"] == "jev_access_not_configured"
    assert client.get("/health").json() == {"ok": True}


@pytest.mark.parametrize(
    "authorization",
    [None, "Basic !!!", "Basic " + base64.b64encode(b"missing-colon").decode("ascii"), AUTHORIZATION],
)
def test_public_page_ignores_credentials_and_does_not_call_provider(monkeypatch, authorization) -> None:
    collection = FakeCollection([])
    jev_client = FakeJevClient()
    app = _app(monkeypatch, collection=collection, jev_client=jev_client, public_access=True)
    monkeypatch.setattr(settings, "jev_panel_user", None)
    monkeypatch.setattr(settings, "jev_panel_password", None)
    client = TestClient(app)

    headers = {"Authorization": authorization} if authorization else {}
    response = client.get("/jev", headers=headers)

    assert response.status_code == 200
    assert 'id="history-input"' in response.text
    assert client.cookies.get("jev_csrf")
    assert "www-authenticate" not in response.headers
    assert response.headers["cache-control"] == "no-store"
    assert collection.calls == 0
    assert jev_client.calls == []


def test_public_history_works_without_authentication(monkeypatch) -> None:
    collection = FakeCollection([{"value": 3}, {"value": 7}, {"value": 1}])
    client = TestClient(_app(monkeypatch, collection=collection, public_access=True))

    response = client.get("/api/jev/historico?quantidade=3")

    assert response.status_code == 200
    assert response.json()["historico"] == [1, 7, 3]
    assert response.headers["cache-control"] == "no-store"
    assert collection.calls == 1


@pytest.mark.parametrize(
    ("csrf_case", "expected_code"),
    [
        ("missing", "jev_csrf_invalid"),
        ("mismatch", "jev_csrf_invalid"),
        ("cross-site", "jev_cross_site_request"),
        ("invalid-origin", "jev_origin_invalid"),
    ],
)
def test_public_analysis_keeps_csrf_protection(monkeypatch, csrf_case, expected_code) -> None:
    jev_client = FakeJevClient()
    client = TestClient(_app(monkeypatch, jev_client=jev_client, public_access=True))
    assert client.get("/jev").status_code == 200
    csrf = client.cookies.get("jev_csrf")
    headers = {"X-CSRF-Token": csrf}
    if csrf_case == "missing":
        headers = {}
    elif csrf_case == "mismatch":
        headers["X-CSRF-Token"] = "wrong-token"
    elif csrf_case == "cross-site":
        headers["Sec-Fetch-Site"] = "cross-site"
    else:
        headers["Origin"] = "https://other.example"

    response = client.post("/api/jev/analisar", headers=headers, json=_payload())

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == expected_code
    assert jev_client.calls == []


def test_public_analysis_with_csrf_works_without_login(monkeypatch) -> None:
    jev_client = FakeJevClient()
    app = _app(monkeypatch, jev_client=jev_client, public_access=True)
    monkeypatch.setattr(settings, "jev_panel_user", None)
    monkeypatch.setattr(settings, "jev_panel_password", None)
    saved = []

    async def fake_persist(record, results_dir):
        saved.append(record)

    monkeypatch.setattr(jev_route, "persist_analysis", fake_persist)
    client = TestClient(app)
    assert client.get("/jev").status_code == 200
    response = client.post(
        "/api/jev/analisar",
        headers={"X-CSRF-Token": client.cookies.get("jev_csrf")},
        json=_payload(),
    )

    assert response.status_code == 200
    assert response.json()["historico_utilizado"] == [1, 7, 0, 2, 8, 3]
    assert len(jev_client.calls) == 1
    assert len(saved) == 1


def test_history_route_uses_fixed_table_order_and_no_store(monkeypatch) -> None:
    timestamp = datetime(2026, 9, 25, 15, 0, tzinfo=timezone.utc)
    collection = FakeCollection(
        [{"value": 3, "timestamp": timestamp}, {"value": 7}, {"value": 1}]
    )
    client = TestClient(_app(monkeypatch, collection=collection))
    response = client.get("/api/jev/historico?quantidade=3", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json()["roulette_slug"] == "pragmatic-auto-roulette"
    assert response.json()["historico"] == [1, 7, 3]
    assert response.json()["ultimo_resultado_em"] == "2026-09-25T15:00:00Z"
    assert response.headers["cache-control"] == "no-store"
    assert collection.calls == 1


def test_history_quantity_validation_happens_before_source(monkeypatch) -> None:
    collection = FakeCollection([])
    client = TestClient(_app(monkeypatch, collection=collection))
    for value in ("0", "-1", "1.5", "+1", "10001", "true"):
        response = client.get(
            f"/api/jev/historico?quantidade={value}", headers=AUTH_HEADERS
        )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "jev_invalid_quantity"
    assert collection.calls == 0


@pytest.mark.parametrize("roulette_slug", ["pragmatic-auto-roulette", "pragmatic-mega-roulette"])
def test_analysis_uses_edited_text_and_never_queries_history(monkeypatch, roulette_slug) -> None:
    collection = FakeCollection([{"value": 36}])
    jev_client = FakeJevClient()
    app = _app(monkeypatch, collection=collection, jev_client=jev_client)

    saved = []

    async def fake_persist(record, results_dir):
        saved.append((record, results_dir))

    monkeypatch.setattr(jev_route, "persist_analysis", fake_persist)
    client = TestClient(app)
    csrf = _csrf(client)
    response = client.post(
        "/api/jev/analisar",
        headers={**AUTH_HEADERS, "X-CSRF-Token": csrf},
        json={**_payload("9, 7, 7, 0"), "roulette_slug": roulette_slug},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["roulette_slug"] == roulette_slug
    assert jev_client.calls[0]["state"]["roulette_slug"] == roulette_slug
    assert saved[0][0]["roulette_slug"] == roulette_slug
    assert body["historico_utilizado"] == [9, 7, 7, 0]
    assert body["ultimo_numero"] == 0
    assert body["quantidade_analisada"] == 4
    assert body["modelo_solicitado"] == "typesafe/jev-1.13"
    assert body["modelo_retornado"] == "typesafe/jev-1.13-returned"
    assert body["resposta_jev"]["usage"]["cost"] == 0
    assert collection.calls == 0
    assert len(jev_client.calls) == 1
    assert jev_client.calls[0]["state"]["history"] == [9, 7, 7, 0]
    assert len(jev_client.calls[0]["questions"]) == 6
    assert len(saved) == 1
    assert saved[0][0]["payload_jev"]["model"] == "typesafe/jev-1.13"


def test_csrf_body_limit_and_invalid_input_stop_before_paid_call(monkeypatch) -> None:
    jev_client = FakeJevClient()
    app = _app(monkeypatch, jev_client=jev_client)
    client = TestClient(app)
    csrf = _csrf(client)

    no_csrf = client.post("/api/jev/analisar", headers=AUTH_HEADERS, json=_payload())
    assert no_csrf.status_code == 403
    assert no_csrf.json()["detail"]["code"] == "jev_csrf_invalid"

    bad_order = _payload()
    bad_order["history_order"] = "newest_to_oldest"
    invalid = client.post(
        "/api/jev/analisar",
        headers={**AUTH_HEADERS, "X-CSRF-Token": csrf},
        json=bad_order,
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["code"] == "jev_invalid_input"

    monkeypatch.setattr(settings, "jev_max_body_bytes", 100)
    oversized = client.post(
        "/api/jev/analisar",
        headers={
            **AUTH_HEADERS,
            "X-CSRF-Token": csrf,
            "Content-Type": "application/json",
        },
        content=b"{" + b" " * 200 + b"}",
    )
    assert oversized.status_code == 413
    assert oversized.json()["detail"]["code"] == "jev_body_too_large"
    assert jev_client.calls == []


def test_missing_openrouter_key_does_not_break_page_or_history(monkeypatch) -> None:
    collection = FakeCollection([])
    app = _app(monkeypatch, collection=collection)
    monkeypatch.setattr(settings, "openrouter_api_key", None)
    client = TestClient(app)
    csrf = _csrf(client)

    history = client.get("/api/jev/historico?quantidade=1", headers=AUTH_HEADERS)
    analysis = client.post(
        "/api/jev/analisar",
        headers={**AUTH_HEADERS, "X-CSRF-Token": csrf},
        json=_payload(),
    )
    assert history.status_code == 200
    assert analysis.status_code == 503
    assert analysis.json()["detail"]["code"] == "openrouter_not_configured"


def test_local_and_provider_context_limits_return_specific_errors(monkeypatch) -> None:
    for jev_client, expected_code in (
        (OversizedPayloadJevClient(), "jev_payload_too_large"),
        (ProviderContextLimitJevClient(), "openrouter_context_too_large"),
    ):
        client = TestClient(_app(monkeypatch, jev_client=jev_client))
        csrf = _csrf(client)
        response = client.post(
            "/api/jev/analisar",
            headers={**AUTH_HEADERS, "X-CSRF-Token": csrf},
            json=_payload(),
        )

        assert response.status_code == 422
        assert response.json()["detail"]["code"] == expected_code


def test_persistence_failure_returns_analysis_warning_without_second_call(monkeypatch) -> None:
    jev_client = FakeJevClient()
    app = _app(monkeypatch, jev_client=jev_client)

    async def fail_persist(_record, _results_dir):
        raise OSError("disk full")

    monkeypatch.setattr(jev_route, "persist_analysis", fail_persist)
    client = TestClient(app)
    csrf = _csrf(client)
    response = client.post(
        "/api/jev/analisar",
        headers={**AUTH_HEADERS, "X-CSRF-Token": csrf},
        json=_payload(),
    )

    assert response.status_code == 200
    assert len(response.json()["avisos"]) == 1
    assert len(jev_client.calls) == 1


@pytest.mark.parametrize("roulette_slug", ["pragmatic-auto-roulette", "pragmatic-mega-roulette"])
def test_ranking_includes_zero_all_numbers_and_pull_catalog(monkeypatch, roulette_slug) -> None:
    jev_client = FakeRankingJevClient()
    app = _app(monkeypatch, jev_client=jev_client)
    saved = []

    async def fake_persist(record, results_dir):
        saved.append((record, results_dir))

    monkeypatch.setattr(jev_route, "persist_analysis", fake_persist)
    client = TestClient(app)
    csrf = _csrf(client)
    history = ", ".join(
        str(value) for _ in range(40) for value in (17, 0, 1, 2)
    ) + ", 17"
    response = client.post(
        "/api/jev/ranking",
        headers={**AUTH_HEADERS, "X-CSRF-Token": csrf},
        json={"history_order": "oldest_to_newest", "historico_texto": history, "roulette_slug": roulette_slug},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["roulette_slug"] == roulette_slug
    assert jev_client.calls[0]["state"]["task"]["roulette_slug"] == roulette_slug
    assert body["confianca_top_n"]["roulette_slug"] == roulette_slug
    assert saved[0][0]["roulette_slug"] == roulette_slug
    assert body["analysis_type"] == "number_ranking"
    assert len(body["ranking"]) == 37
    assert {item["numero"] for item in body["ranking"]} == set(range(37))
    assert body["ranking"][0]["numero"] == 0
    assert body["ranking"][0]["posicao"] == 1
    assert len(body["ranking_proxima_rodada"]) == 37
    assert body["ranking_proxima_rodada"][0]["numero"] == 0
    assert len(body["ranking_meta"]) == 37
    assert len(body["ranking_meta_proxima_rodada"]) == 37
    assert {item["numero"] for item in body["ranking_meta"]} == set(range(37))
    assert sum(
        item["probabilidade_meta"] for item in body["ranking_meta_proxima_rodada"]
    ) == pytest.approx(1)
    assert body["sinal_meta"]["status"] in {
        "validated", "experimental", "no_reliable_signal"
    }
    assert body["confianca_top_n"]["top_k"] == 6
    assert body["confianca_top_n"]["attempts"] == 1
    assert body["confianca_top_n"]["decision"] == "no_entry"
    assert body["confianca_top_n"]["status"] == "insufficient"
    assert body["ranking_adaptativo"]["status"] == "warming_up"
    assert body["ranking_adaptativo"]["sample_count"] == 0
    assert body["ranking_adaptativo"]["jev_selected_numbers"] == [0, 1, 2, 3, 4, 5]
    assert body["ranking_adaptativo"]["adaptive_selected_numbers"] == [0, 1, 2, 3, 4, 5]
    assert body["proxima_rodada_meta"]["numero_escolhido"] in range(37)
    assert body["validacao_walk_forward"]["version"] == "source_conditioned_v1"
    assert body["proxima_rodada"]["numero_escolhido"] == 0
    assert body["regime_atual"]["choice"] == "transition_driven"
    assert body["ultimo_numero"] == 17
    assert body["historico_contexto_enviado"]["latest_observed_number"] == 17
    assert any(item["target_number"] == 0 for item in body["catalogo_padroes"])
    assert body["catalogo_padroes"][0]["qualidade_jev"]["score"] == 2.4
    assert len(jev_client.calls) == 1
    assert tuple(jev_client.calls[0]["questions"])[:37] == NUMBER_KEYS
    assert jev_client.calls[0]["state"]["task"]["include_zero"] is True
    assert len(saved) == 1
    assert saved[0][0]["analysis_type"] == "number_ranking"


def test_invalid_ranking_stops_before_paid_call(monkeypatch) -> None:
    jev_client = FakeRankingJevClient()
    client = TestClient(_app(monkeypatch, jev_client=jev_client))
    csrf = _csrf(client)

    no_csrf = client.post(
        "/api/jev/ranking",
        headers=AUTH_HEADERS,
        json={"history_order": "oldest_to_newest", "historico_texto": "17, 0"},
    )
    assert no_csrf.status_code == 403
    assert no_csrf.json()["detail"]["code"] == "jev_csrf_invalid"

    response = client.post(
        "/api/jev/ranking",
        headers={**AUTH_HEADERS, "X-CSRF-Token": csrf},
        json={"history_order": "oldest_to_newest", "historico_texto": "17, invalid"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "jev_invalid_history"
    assert jev_client.calls == []


@pytest.mark.parametrize("roulette_slug", ["pragmatic-auto-roulette", "pragmatic-mega-roulette"])
def test_manual_evaluation_uses_saved_ranking_without_paid_call(monkeypatch, roulette_slug) -> None:
    jev_client = FakeRankingJevClient()
    app = _app(monkeypatch, jev_client=jev_client)
    saved_rankings = []
    saved_evaluations = []

    async def capture_ranking(record, _results_dir):
        saved_rankings.append(record)

    async def load_ranking(analysis_id, _results_dir):
        assert analysis_id == saved_rankings[0]["analysis_id"]
        return saved_rankings[0]

    async def capture_evaluation(record, _results_dir):
        saved_evaluations.append(record)

    monkeypatch.setattr(jev_route, "persist_analysis", capture_ranking)
    monkeypatch.setattr(jev_route, "load_analysis", load_ranking)
    monkeypatch.setattr(jev_route, "persist_evaluation", capture_evaluation)
    client = TestClient(app)
    csrf = _csrf(client)
    history = ", ".join(str(value) for _ in range(40) for value in (17, 0, 1, 2)) + ", 17"
    ranking_response = client.post(
        "/api/jev/ranking",
        headers={**AUTH_HEADERS, "X-CSRF-Token": csrf},
        json={"history_order": "oldest_to_newest", "historico_texto": history, "roulette_slug": roulette_slug},
    )
    evaluation_response = client.post(
        "/api/jev/avaliar",
        headers={**AUTH_HEADERS, "X-CSRF-Token": csrf},
        json={
            "analysis_id": ranking_response.json()["analysis_id"],
            "resultados_reais_texto": "0, 1, 2",
        },
    )

    assert evaluation_response.status_code == 200
    body = evaluation_response.json()
    assert body["roulette_slug"] == roulette_slug
    assert saved_evaluations[0]["roulette_slug"] == roulette_slug
    assert body["metrica_proxima_rodada"]["acertou_escolha"] is True
    assert body["metricas_tres_rodadas"]["acertos_por_corte"]["top_1"] is True
    assert len(saved_evaluations) == 1
    assert len(jev_client.calls) == 1


def test_manual_evaluation_requires_exactly_three_results(monkeypatch) -> None:
    client = TestClient(_app(monkeypatch))
    csrf = _csrf(client)
    response = client.post(
        "/api/jev/avaliar",
        headers={**AUTH_HEADERS, "X-CSRF-Token": csrf},
        json={
            "analysis_id": "8f3bbcf2-11dc-4f50-aec5-4ff9001e7502",
            "resultados_reais_texto": "0, 1",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "jev_invalid_actual_results_count"


def test_history_route_uses_selected_table_and_rejects_unknown_before_query(monkeypatch) -> None:
    slug = "pragmatic-mega-roulette"
    collection = FakeCollection([{"value": 12}, {"value": 29}], roulette_slug=slug)
    client = TestClient(_app(monkeypatch, collection=collection))
    response = client.get(
        f"/api/jev/historico?quantidade=2&roulette_slug={slug}", headers=AUTH_HEADERS
    )
    assert response.status_code == 200
    assert response.json()["roulette_slug"] == slug
    assert response.json()["historico"] == [29, 12]
    invalid = client.get(
        "/api/jev/historico?quantidade=2&roulette_slug=unknown", headers=AUTH_HEADERS
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["code"] == "jev_invalid_roulette"
    assert collection.calls == 1


@pytest.mark.parametrize("route, payload", [
    ("analisar", _payload()),
    ("ranking", {"history_order": "oldest_to_newest", "historico_texto": "1,2,3"}),
    ("backtest/iniciar", {"history_points": 1, "context_numbers": 50, "chip_count": 6,
                          "attempts": 1, "confirm_paid_run": True}),
])
def test_unknown_table_is_rejected_before_paid_calls_or_history(monkeypatch, route, payload) -> None:
    collection = FakeCollection([])
    jev_client = FakeJevClient()
    client = TestClient(_app(monkeypatch, collection=collection, jev_client=jev_client))
    csrf = _csrf(client)
    response = client.post(
        f"/api/jev/{route}",
        headers={**AUTH_HEADERS, "X-CSRF-Token": csrf},
        json={**payload, "roulette_slug": "unknown"},
    )
    assert response.status_code == 422
    assert collection.calls == 0
    assert jev_client.calls == []
