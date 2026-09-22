import asyncio
import json
import subprocess
from datetime import datetime, timedelta, timezone
from itertools import permutations
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pymongo.errors import PyMongoError

from api.routes import triple_context_backtest as route_module
from api.routes.triple_context_backtest import get_backtest_db, router
from api.services.triple_context_backtest_service import (
    CatalogNotFound, CatalogUnavailable, build_signals, normalize_history, ranking_quality,
    run_catalog_backtest,
)


ROULETTE = "pragmatic-auto-roulette"


class FakeCursor:
    def __init__(self, documents, calls):
        self.documents = documents
        self.calls = calls

    def sort(self, spec):
        self.calls.append(("sort", spec))
        return self

    def limit(self, value):
        self.calls.append(("limit", value))
        self.documents = self.documents[:value]
        return self

    def max_time_ms(self, value):
        self.calls.append(("max_time_ms", value))
        return self

    async def to_list(self, length):
        self.calls.append(("to_list", length))
        return self.documents[:length]


class FakeCollection:
    def __init__(self, name, documents, calls):
        self.name, self.documents, self.calls = name, documents, calls

    async def find_one(self, query, projection=None, sort=None):
        self.calls.append((self.name, "find_one", query, projection, sort))
        if self.name == "history" and sort:
            return {"_id": max(row["_id"] for row in self.documents)} if self.documents else None
        for row in self.documents:
            if _matches(row, query):
                return dict(row)
        return None

    def find(self, query, projection=None):
        self.calls.append((self.name, "find", query, projection))
        rows = [dict(row) for row in self.documents if _matches(row, query)]
        if self.name == "history":
            rows.sort(key=lambda row: (row["timestamp"], row["_id"]), reverse=True)
        return FakeCursor(rows, self.calls)


class FakeDB:
    def __init__(self, collections):
        self.calls = []
        self.collections = {name: FakeCollection(name, rows, self.calls)
                            for name, rows in collections.items()}

    def __getitem__(self, name):
        return self.collections[name]


def _matches(document, query):
    for key, expected in query.items():
        observed = document.get(key)
        if isinstance(expected, dict) and "$lte" in expected:
            if observed > expected["$lte"]:
                return False
        elif isinstance(expected, dict) and "$in" in expected:
            if observed not in expected["$in"]:
                return False
        elif observed != expected:
            return False
    return True


def _ranking(seed=0, events=10):
    order = list(range(37))
    order = order[seed:] + order[:seed]
    return [{"number": number, "score": float(37 - position),
             "direct_hits": events if position == 0 else 0}
            for position, number in enumerate(order)]


def _catalog_doc(key, combination, *, events=10, direction="forward", seed=0,
                 mode="ordered"):
    depth = 20 if direction == "forward" else 10
    document = {"build_id": "build-a", "roulette_id": ROULETTE,
            "mode": mode, "key": key, "combination": combination,
            "occurrences": 4, direction: {"depth": depth, "context_events": events,
                "complete_occurrences": min(4, events // depth),
                "position_counts": [events // depth + (index < events % depth)
                                    for index in range(depth)],
                "ranking": _ranking(seed, events)}}
    if mode == "unordered":
        document["permutation_counts"] = [
            {"combination": list(order), "occurrences": 4 if index == 0 else 0}
            for index, order in enumerate(permutations(combination))]
    return document


def _db(values, catalog, *, status="ready", active=True):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    history = [{"_id": i + 1, "value": value, "timestamp": start + timedelta(seconds=i * 30),
                "roulette_id": ROULETTE, "external_game_id": f"g{i}"}
               for i, value in enumerate(values)]
    return FakeDB({
        "triple_context_active_v1": ([{"_id": ROULETTE, "build_id": "build-a"}] if active else []),
        "triple_context_builds_v1": [{"_id": "build-a", "roulette_id": ROULETTE,
            "status": status, "source": {"records": 200000,
            "first_timestamp": "2025-01-01T00:00:00+00:00",
            "last_timestamp": "2025-12-31T00:00:00+00:00"}}],
        "triple_context_rankings_v1": catalog,
        "history": history,
    })


def _history_documents(values, *, gap_at=None):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    elapsed = 0
    documents = []
    for index, value in enumerate(values):
        elapsed += 360 if index == gap_at else 30
        documents.append({"_id": index + 1, "value": value,
                          "timestamp": start + timedelta(seconds=elapsed),
                          "roulette_id": ROULETTE, "external_game_id": f"game-{index}"})
    return list(reversed(documents))


def test_normalize_history_rejects_invalid_values_and_duplicate_external_ids():
    invalid = _history_documents([1, 2, 3])
    invalid[1]["value"] = True
    with pytest.raises(CatalogUnavailable, match="inválido"):
        normalize_history(invalid, 3)

    duplicate = _history_documents([1, 2, 3])
    duplicate[0]["external_game_id"] = duplicate[1]["external_game_id"]
    with pytest.raises(CatalogUnavailable, match="duplicados"):
        normalize_history(duplicate, 3)


def test_normalize_history_reports_gap_without_removing_or_reordering_rows():
    rows, source = normalize_history(_history_documents([3, 2, 1, 9], gap_at=2), 4)
    assert [row["value"] for row in rows] == [3, 2, 1, 9]
    assert source["records"] == 4
    assert source["records_discarded"] == 0
    assert source["gaps_over_300_seconds"] == 1
    assert source["maximum_gap_seconds"] == 360


@pytest.mark.parametrize("ordered,direction", [
    (True, "forward"), (True, "backward"),
    (False, "forward"), (False, "backward"),
])
def test_run_uses_chronological_key_requested_mode_side_and_top_k(ordered, direction):
    key = "3,2,1" if ordered else "1,2,3"
    combination = [3, 2, 1] if ordered else [1, 2, 3]
    mode = "ordered" if ordered else "unordered"
    document = _catalog_doc(key, combination, direction=direction, seed=9, mode=mode)
    db = _db([3, 2, 1, 9, 30], [document])
    # The catalog spans this historical signal, so the retrospective warning is required.
    db.collections["triple_context_builds_v1"].documents[0]["source"]["last_timestamp"] = (
        "2027-01-01T00:00:00+00:00")

    result = asyncio.run(run_catalog_backtest(
        db, history_limit=5, top_k=1, attempts=1, ordered=ordered, direction=direction))

    signal = result["signals"][0]
    assert signal["trio"] == [3, 2, 1]
    assert signal["key"] == key
    assert signal["selected_numbers"] == [9]
    assert signal["checked_numbers"] == [9]
    assert signal["status"] == "win"
    assert result["methodology"]["signals_with_potential_future_data"] == 1
    assert result["methodology"]["warning"] is not None
    ranking_call = next(call for call in db.calls
                        if call[0] == "triple_context_rankings_v1" and call[1] == "find")
    assert ranking_call[2]["mode"] == mode
    assert ranking_call[2]["key"] == {"$in": [key]}
    projection = ranking_call[3]
    assert direction in projection
    assert ("backward" if direction == "forward" else "forward") not in projection


def test_run_omits_temporal_warning_when_signals_are_after_catalog_period():
    document = _catalog_doc("3,2,1", [3, 2, 1], seed=9)
    result = asyncio.run(run_catalog_backtest(
        _db([3, 2, 1, 9], [document]), history_limit=4, top_k=1, attempts=1,
        ordered=True, direction="forward"))
    assert result["methodology"]["signals_with_potential_future_data"] == 0
    assert result["methodology"]["warning"] is None


def test_history_descending_is_restored_and_blocks_are_not_recompressed():
    # First block repeats and is skipped; the next block remains positions 3..5.
    documents = [_catalog_doc("3,4,5", [3, 4, 5], seed=5),
                 _catalog_doc("5,6,7", [5, 6, 7], seed=7)]
    db = _db([1, 1, 2, 3, 4, 5, 5, 6, 7], documents)
    result = asyncio.run(run_catalog_backtest(
        db, history_limit=9, top_k=2, attempts=2, ordered=True, direction="forward"))
    signals = result["signals"]
    assert signals[0]["trio"] == [1, 1, 2]
    assert signals[0]["status"] == "repeated_trio"
    assert signals[1]["trio"] == [3, 4, 5]
    assert signals[1]["trigger_position"] == 6
    assert signals[1]["selected_numbers"] == [5, 6]
    assert result["source"]["first_timestamp"] < result["source"]["last_timestamp"]
    assert result["config"]["sampling"] == "blocks_of_three"
    ranking_query = next(call[2] for call in db.calls
                         if call[0] == "triple_context_rankings_v1" and call[1] == "find")
    assert ranking_query["build_id"] == result["catalog"]["build_id"] == "build-a"


def test_run_can_prevent_overlapping_bets_without_removing_formed_signals():
    documents = [
        _catalog_doc("1,2,3", [1, 2, 3], seed=36),
        _catalog_doc("4,5,6", [4, 5, 6], seed=4),
        _catalog_doc("7,8,9", [7, 8, 9], seed=10),
    ]
    result = asyncio.run(run_catalog_backtest(
        _db([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 0], documents),
        history_limit=11, top_k=1, attempts=6, ordered=True, direction="forward",
        prevent_overlapping_bets=True))

    assert [signal["status"] for signal in result["signals"]] == [
        "loss", "overlap_skipped", "win"]
    assert result["summary"]["total_signals"] == 3
    assert result["summary"]["overlap_skipped"] == 1
    assert result["summary"]["evaluated"] == 2
    assert result["config"]["prevent_overlapping_bets"] is True
    assert "só começa após" in result["methodology"]["description"]


def test_build_signals_selects_requested_side_mode_and_top_k():
    rows = [{"value": value, "timestamp": f"t{i}", "source_id": str(i)}
            for i, value in enumerate([3, 2, 1])]
    document = _catalog_doc("1,2,3", [1, 2, 3], events=4, direction="backward",
                            seed=9, mode="unordered")
    unordered = {"1,2,3": document}
    signals = build_signals(rows, unordered, ordered=False, direction="backward", top_k=3)
    assert signals[0]["key"] == "1,2,3"
    assert signals[0]["selected_numbers"] == [9, 10, 11]
    assert signals[0]["context_events"] == 4
    assert signals[0]["quality"]["direct_lift"] == pytest.approx(37 / 3)
    assert signals[0]["quality"]["order_dominance"] == 1


def test_ranking_quality_normalizes_support_direct_hits_and_score_margins():
    document = _catalog_doc("1,2,3", [1, 2, 3], events=20, seed=7)
    side = document["forward"]
    quality = ranking_quality(
        document, side, side["ranking"], top_k=1, ordered=True)

    assert quality["occurrences"] == 4
    assert quality["context_coverage"] == pytest.approx(0.25)
    assert quality["complete_coverage"] == pytest.approx(0.25)
    assert quality["top_k_direct_hits"] == 20
    assert quality["direct_hit_rate"] == 1
    assert quality["direct_lift"] == 37
    assert quality["score_concentration"] == pytest.approx(37 / sum(range(1, 38)))
    assert quality["score_concentration_lift"] == pytest.approx(
        quality["score_concentration"] * 37)
    assert quality["cutoff_margin_per_event"] == pytest.approx(0.05)
    assert quality["leader_margin_per_event"] == pytest.approx(0.05)
    assert quality["order_dominance"] is None


def test_zero_evidence_is_skipped_and_missing_or_corrupt_catalog_fails():
    rows = [{"value": value, "timestamp": f"t{i}", "source_id": str(i)}
            for i, value in enumerate([1, 2, 3])]
    zero = _catalog_doc("1,2,3", [1, 2, 3], events=0)
    signal = build_signals(rows, {"1,2,3": zero}, ordered=True,
                           direction="forward", top_k=13)[0]
    assert signal["status"] == "no_evidence"
    assert signal["selected_numbers"] == []
    with pytest.raises(CatalogUnavailable, match="ausente"):
        build_signals(rows, {}, ordered=True, direction="forward", top_k=13)
    corrupt = _catalog_doc("1,2,3", [1, 2, 3])
    corrupt["forward"]["ranking"] = corrupt["forward"]["ranking"][:-1]
    with pytest.raises(CatalogUnavailable, match="inconsistente"):
        build_signals(rows, {"1,2,3": corrupt}, ordered=True,
                      direction="forward", top_k=13)


def _client(db=None):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_backtest_db] = lambda: db
    return TestClient(app)


def test_backtest_html_is_independent_of_mongo_and_has_versioned_controls_and_assets():
    response = _client(db=None).get("/backtest-trios")
    assert response.status_code == 200
    assert 'href="/static/css/triple_context_ranking.css?v=' in response.text
    assert 'href="/static/css/triple_context_backtest.css?v=' in response.text
    assert 'src="/static/js/pages/triple-context-backtest.js?v=' in response.text
    assert '{{ asset_version }}' not in response.text
    assert response.text.count('name="direction"') == 2
    assert 'name="direction" value="forward"' in response.text
    assert 'name="direction" value="backward"' in response.text
    assert response.text.count('name="ordered"') == 2
    assert 'name="ordered" value="true"' in response.text
    assert 'name="ordered" value="false"' in response.text
    assert 'name="prevent_overlapping_bets"' in response.text
    assert 'id="minimum-profit"' in response.text
    assert 'id="calculate-financial"' in response.text
    assert 'id="financial-projection-body"' in response.text
    assert 'id="financial-chart"' in response.text
    assert 'id="quality-report-heading"' in response.text
    assert 'id="quality-dimension"' in response.text
    assert 'id="quality-buckets-body"' in response.text
    assert "csv" not in response.text.lower()


def test_financial_progression_uses_fifty_cent_steps_and_recovers_previous_stakes():
    script_path = Path(__file__).parents[1] / "static/js/pages/triple-context-backtest.js"
    javascript = """
const { buildFinancialPlan } = require(process.argv[1]);
const plan = buildFinancialPlan(13, 3, 1000);
let unsupported;
try { buildFinancialPlan(36, 3, 1000); } catch (error) { unsupported = error.message; }
process.stdout.write(JSON.stringify({ plan, unsupported }));
"""
    result = subprocess.run(
        ["node", "-e", javascript, str(script_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["plan"]["rows"] == [
        {
            "attempt": 1,
            "stakePerNumberCents": 50,
            "attemptStakeCents": 650,
            "cumulativeStakeCents": 650,
            "profitIfHitCents": 1150,
        },
        {
            "attempt": 2,
            "stakePerNumberCents": 100,
            "attemptStakeCents": 1300,
            "cumulativeStakeCents": 1950,
            "profitIfHitCents": 1650,
        },
        {
            "attempt": 3,
            "stakePerNumberCents": 150,
            "attemptStakeCents": 1950,
            "cumulativeStakeCents": 3900,
            "profitIfHitCents": 1500,
        },
    ]
    assert payload["plan"]["maxExposureCents"] == 3900
    assert "top K entre 1 e 35" in payload["unsupported"]


@pytest.mark.parametrize("payload", [
    {"history_limit": 5}, {"history_limit": 50001}, {"top_k": 0}, {"top_k": 38},
    {"attempts": 0}, {"attempts": 101}, {"ordered": 1}, {"history_limit": True},
    {"prevent_overlapping_bets": 1},
    {"direction": "side"},
    {"extra": True},
])
def test_route_rejects_invalid_ranges_strict_bools_and_extra_fields(payload):
    assert _client().post("/api/triple-context-backtest", json=payload).status_code == 422


class FakeLock:
    def __init__(self, locked=False):
        self.busy, self.entered, self.exited = locked, False, False

    def locked(self):
        return self.busy

    async def __aenter__(self):
        self.entered = self.busy = True

    async def __aexit__(self, *_):
        self.exited, self.busy = True, False


@pytest.mark.parametrize("error,status", [
    (CatalogNotFound("missing"), 404),
    (CatalogUnavailable("catalog unavailable"), 503),
    (PyMongoError("mongodb://user:secret@internal"), 503),
])
def test_route_maps_read_errors_and_releases_lock(monkeypatch, error, status):
    lock = FakeLock()
    async def unavailable(*_args, **_kwargs):
        raise error
    monkeypatch.setattr(route_module, "_backtest_lock", lock)
    monkeypatch.setattr(route_module, "run_catalog_backtest", unavailable)
    response = _client(object()).post("/api/triple-context-backtest", json={})
    assert response.status_code == status
    assert lock.entered and lock.exited and not lock.locked()
    assert "secret" not in response.text.lower()


def test_route_returns_429_without_calling_service(monkeypatch):
    lock = FakeLock(locked=True)
    called = False
    async def should_not_run(*_args, **_kwargs):
        nonlocal called
        called = True
    monkeypatch.setattr(route_module, "_backtest_lock", lock)
    monkeypatch.setattr(route_module, "run_catalog_backtest", should_not_run)
    response = _client(object()).post("/api/triple-context-backtest", json={})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "5"
    assert not called


def test_route_timeout_is_504_and_releases_lock(monkeypatch):
    lock = FakeLock()
    async def slow(*_args, **_kwargs):
        import asyncio
        await asyncio.sleep(0.05)
    monkeypatch.setattr(route_module, "_backtest_lock", lock)
    monkeypatch.setattr(route_module, "BACKTEST_TIMEOUT_SECONDS", 0.001)
    monkeypatch.setattr(route_module, "run_catalog_backtest", slow)
    response = _client(object()).post("/api/triple-context-backtest", json={})
    assert response.status_code == 504
    assert lock.exited and not lock.locked()
