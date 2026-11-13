from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from contextual_ranking.search_client import PAGE_SEARCH_PARAMETERS, SearchError, VectorSearchClient

CUTOFF = datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)
STATIC = Path(__file__).resolve().parents[2] / "api" / "static" / "js"


def client_with(handler, token="segredo", sleeps=None):
    return VectorSearchClient(
        "http://vector.test/", token, client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=(sleeps if sleeps is not None else []).append,
    )


def test_sends_the_page_request_with_cutoff_and_token():
    seen = {}

    def handler(request):
        seen.update(url=str(request.url), auth=request.headers["authorization"],
                    body=json.loads(request.content))
        return httpx.Response(200, json={"total_matches": 7, "occurrences": [{
            "id": "a", "context": [1, 2, 3, 4], "following": [5, 6, 7, 8, 9],
            "preceding": [1, 2, 3, 4, 5], "preceding_complete": True,
            "preceding_lookup_status": "complete", "similarity": 0.9, "regions": {"big": True},
        }]})

    result = client_with(handler).search([23, 12, 32, 7], CUTOFF)
    assert seen["url"] == "http://vector.test/search"
    assert seen["auth"] == "Bearer segredo"
    assert seen["body"] == {"sequence": [23, 12, 32, 7], **PAGE_SEARCH_PARAMETERS,
                            "cutoff": "2026-11-13T15:00:00+00:00"}
    assert result == {"total_matches": 7, "occurrences": [{
        "id": "a", "context": [1, 2, 3, 4], "following": [5, 6, 7, 8, 9], "preceding": [1, 2, 3, 4, 5],
        "preceding_complete": True, "preceding_lookup_status": "complete", "similarity": 0.9,
        "context_end_at": None,
    }]}


def test_parameters_are_the_same_the_browser_page_sends():
    page = (STATIC / "pages" / "contextual-similarity.js").read_text(encoding="utf-8")
    model = (STATIC / "core" / "contextual-similarity-model.js").read_text(encoding="utf-8")
    assert f'rouletteId: "{PAGE_SEARCH_PARAMETERS["roulette_id"]}"' in model
    for name, value in PAGE_SEARCH_PARAMETERS.items():
        if name == "roulette_id":
            continue
        literal = json.dumps(value)
        assert f"{name}: {literal}" in page, name


def test_temporary_failures_are_retried_with_backoff():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"occurrences": []})

    sleeps = []
    assert client_with(handler, sleeps=sleeps).search([1, 2, 3, 4], CUTOFF) == {
        "occurrences": [], "total_matches": 0,
    }
    assert sleeps == [1.0, 2.0]


def test_rejected_query_is_not_retried():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(422, json={"detail": "inválida"})

    with pytest.raises(SearchError):
        client_with(handler).search([1, 2, 3, 4], CUTOFF)
    assert len(calls) == 1


def test_single_attempt_gives_up_immediately():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503)

    with pytest.raises(SearchError):
        client_with(handler).search([1, 2, 3, 4], CUTOFF, attempts=1)
    assert len(calls) == 1


def test_missing_token_never_calls_the_service():
    def handler(request):
        raise AssertionError("a busca não deveria ser chamada")

    client = client_with(handler, token="  ")
    assert client.configured is False
    with pytest.raises(SearchError):
        client.search([1, 2, 3, 4], CUTOFF)


def test_naive_cutoff_is_sent_as_utc():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"occurrences": []})

    client_with(handler).search([1, 2, 3, 4], datetime(2026, 11, 13, 15, 0))
    assert bodies[0]["cutoff"] == "2026-11-13T15:00:00+00:00"
