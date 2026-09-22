from __future__ import annotations

from copy import deepcopy
from itertools import permutations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pymongo.errors import PyMongoError

from api.routes.triple_context_ranking import get_catalog_db, router


ACTIVE = "triple_context_active_v1"
BUILDS = "triple_context_builds_v1"
RANKINGS = "triple_context_rankings_v1"
ROULETTE = "pragmatic-auto-roulette"


def _matches(document, query):
    return all(document.get(key) == value for key, value in query.items())


class FakeCollection:
    def __init__(self, name, documents, calls, error=None):
        self.name = name
        self.documents = documents
        self.calls = calls
        self.error = error

    async def find_one(self, query, projection=None):
        self.calls.append((self.name, deepcopy(query), deepcopy(projection)))
        if self.error is not None:
            raise self.error
        return next((deepcopy(row) for row in self.documents if _matches(row, query)), None)


class FakeDB:
    def __init__(self, documents, *, error_collection=None, error=None):
        self.calls = []
        self.collections = {
            name: FakeCollection(
                name,
                rows,
                self.calls,
                error if name == error_collection else None,
            )
            for name, rows in documents.items()
        }

    def __getitem__(self, name):
        return self.collections[name]


def _direction(depth, seed, *, zero=False):
    return {
        "depth": depth,
        "context_events": 0 if zero else seed + 100,
        "complete_occurrences": 0 if zero else seed + 10,
        "position_counts": [0 if zero else seed + position for position in range(depth)],
        "ranking": [
            {
                "number": number,
                "score": 0.0 if zero else float(seed * 100 + 37 - number) / 4,
                "direct_hits": 0 if zero else seed + number,
            }
            for number in range(37)
        ],
    }


def _documents(*, status="ready", zero=False):
    source = {
        "records": 200_000,
        "first_timestamp": "2026-07-23T00:00:00+00:00",
        "last_timestamp": "2026-09-21T23:59:59+00:00",
        "content_sha256": "must-not-be-returned",
        "source_snapshot": "/secret/server/path.jsonl.gz",
    }
    common = {
        "build_id": "build-19",
        "roulette_id": ROULETTE,
        "occurrences": 0 if zero else 16,
        "forward": _direction(20, 2, zero=zero),
        "backward": _direction(10, 7, zero=zero),
        "private_note": "must-not-be-returned",
    }
    return {
        ACTIVE: [{"_id": ROULETTE, "build_id": "build-19", "secret": "pointer-secret"}],
        BUILDS: [{
            "_id": "build-19",
            "roulette_id": ROULETTE,
            "status": status,
            "source": source,
            "secret": "manifest-secret",
        }],
        RANKINGS: [
            {**deepcopy(common), "mode": "ordered", "key": "18,14,34",
             "combination": [18, 14, 34]},
            {**deepcopy(common), "mode": "unordered", "key": "14,18,34",
             "combination": [14, 18, 34], "permutation_counts": []},
        ],
    }


def _client(db):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_catalog_db] = lambda: db
    return TestClient(app)


def _get(client, *, ordered, direction, numbers="34,14,18", input_order=None):
    params = {"numbers": numbers, "ordered": str(ordered).lower(), "direction": direction}
    if input_order is not None:
        params["input_order"] = input_order
    return client.get("/api/triple-context-ranking", params=params)


@pytest.mark.parametrize("status", ["verified", "ready"])
@pytest.mark.parametrize("ordered, direction", [
    (True, "forward"), (True, "backward"),
    (False, "forward"), (False, "backward"),
])
def test_lookup_contract_for_both_modes_and_directions(status, ordered, direction):
    db = FakeDB(_documents(status=status))
    response = _get(_client(db), ordered=ordered, direction=direction)
    assert response.status_code == 200, response.text
    body = response.json()

    expected_combination = [18, 14, 34] if ordered else [14, 18, 34]
    expected_key = ",".join(map(str, expected_combination))
    expected_depth = 20 if direction == "forward" else 10
    expected_seed = 2 if direction == "forward" else 7
    assert body == {
        "roulette_id": ROULETTE,
        "requested_numbers": [34, 14, 18],
        "input_order": "latest_first",
        "ordered": ordered,
        "direction": direction,
        "combination": expected_combination,
        "key": expected_key,
        "build_id": "build-19",
        "occurrences": 16,
        "has_evidence": True,
        "depth": expected_depth,
        "context_events": expected_seed + 100,
        "complete_occurrences": expected_seed + 10,
        "position_counts": [expected_seed + i for i in range(expected_depth)],
        "ranking": [
            {"position": i + 1, "number": i,
             "score": float(expected_seed * 100 + 37 - i) / 4,
             "direct_hits": expected_seed + i}
            for i in range(37)
        ],
        "source": {
            "records": 200_000,
            "first_timestamp": "2026-07-23T00:00:00+00:00",
            "last_timestamp": "2026-09-21T23:59:59+00:00",
        },
    }
    assert [name for name, _, _ in db.calls] == [ACTIVE, BUILDS, RANKINGS]
    assert db.calls[0][1] == {"_id": ROULETTE}
    assert db.calls[1][1] == {"_id": "build-19", "roulette_id": ROULETTE}
    assert db.calls[2][1] == {
        "build_id": "build-19", "roulette_id": ROULETTE,
        "mode": "ordered" if ordered else "unordered", "key": expected_key,
    }
    projection = db.calls[2][2]
    assert projection is not None
    assert direction in projection and projection[direction]
    assert ("backward" if direction == "forward" else "forward") not in projection
    assert "private_note" not in response.text and "must-not-be-returned" not in response.text


def test_chronological_order_and_every_unordered_permutation():
    db = FakeDB(_documents())
    client = _client(db)
    chronological = _get(
        client, ordered=True, direction="forward", numbers="18,14,34",
        input_order="chronological",
    )
    assert chronological.status_code == 200
    assert chronological.json()["combination"] == [18, 14, 34]
    assert chronological.json()["requested_numbers"] == [18, 14, 34]

    for values in permutations((14, 18, 34)):
        response = _get(client, ordered=False, direction="forward",
                        numbers=",".join(map(str, values)))
        assert response.status_code == 200, response.text
        assert response.json()["combination"] == [14, 18, 34]
        assert response.json()["key"] == "14,18,34"


@pytest.mark.parametrize("params", [
    {},
    {"numbers": "1,2,3", "ordered": "true"},
    {"numbers": "1,2,3", "direction": "forward"},
    {"direction": "forward", "ordered": "true"},
    {"numbers": "1,2", "direction": "forward", "ordered": "true"},
    {"numbers": "1,2,3,4", "direction": "forward", "ordered": "true"},
    {"numbers": "1,1,2", "direction": "forward", "ordered": "true"},
    {"numbers": "-1,2,3", "direction": "forward", "ordered": "true"},
    {"numbers": "0,2,37", "direction": "forward", "ordered": "true"},
    {"numbers": "1.0,2,3", "direction": "forward", "ordered": "true"},
    {"numbers": "x,2,3", "direction": "forward", "ordered": "true"},
    {"numbers": "1,2,3", "direction": "sideways", "ordered": "true"},
    {"numbers": "1,2,3", "direction": "forward", "ordered": "maybe"},
    {"numbers": "1,2,3", "direction": "forward", "ordered": "true",
     "input_order": "unknown"},
])
def test_invalid_or_missing_parameters_return_422(params):
    response = _client(FakeDB(_documents())).get("/api/triple-context-ranking", params=params)
    assert response.status_code == 422


def test_zero_occurrence_document_is_a_success_without_evidence():
    response = _get(_client(FakeDB(_documents(zero=True))), ordered=True, direction="backward")
    assert response.status_code == 200
    body = response.json()
    assert body["occurrences"] == 0
    assert body["has_evidence"] is False
    assert len(body["ranking"]) == 37
    assert all(row["score"] == 0 and row["direct_hits"] == 0 for row in body["ranking"])


def test_evidence_is_directional_when_occurrence_has_no_forward_context():
    documents = _documents()
    for document in documents[RANKINGS]:
        document["occurrences"] = 1
        document["forward"] = _direction(20, 2, zero=True)
    client = _client(FakeDB(documents))

    forward = _get(client, ordered=True, direction="forward")
    backward = _get(client, ordered=True, direction="backward")

    assert forward.status_code == 200, forward.text
    assert forward.json()["occurrences"] == 1
    assert forward.json()["context_events"] == 0
    assert forward.json()["has_evidence"] is False
    assert backward.status_code == 200, backward.text
    assert backward.json()["occurrences"] == 1
    assert backward.json()["context_events"] > 0
    assert backward.json()["has_evidence"] is True


@pytest.mark.parametrize("case, status", [
    ("no_pointer", 404),
    ("no_manifest", 503),
    ("building", 503),
    ("failed", 503),
    ("no_ranking", 503),
])
def test_catalog_error_states_have_stable_public_status(case, status):
    documents = _documents(status=case if case in {"building", "failed"} else "ready")
    if case == "no_pointer":
        documents[ACTIVE] = []
    elif case == "no_manifest":
        documents[BUILDS] = []
    elif case == "no_ranking":
        documents[RANKINGS] = []
    response = _get(_client(FakeDB(documents)), ordered=True, direction="forward")
    assert response.status_code == status


@pytest.mark.parametrize("error", [
    PyMongoError("mongodb://user:secret@internal.example/TOKEN"),
    TimeoutError("secret-timeout-detail"),
])
def test_database_failures_return_sanitized_503(error):
    db = FakeDB(_documents(), error_collection=BUILDS, error=error)
    response = _get(_client(db), ordered=True, direction="forward")
    assert response.status_code == 503
    lowered = response.text.lower()
    assert "secret" not in lowered
    assert "token" not in lowered
    assert "mongodb://" not in lowered
