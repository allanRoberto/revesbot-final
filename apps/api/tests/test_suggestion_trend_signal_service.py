from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytest

from api.services import suggestion_trend_signal_service as svc


# ---------------------------------------------------------------------------
# Pure-function tests
# ---------------------------------------------------------------------------


def test_detect_trend_direction_basic() -> None:
    assert svc.detect_trend_direction([1, 12, 23]) == "descida"
    assert svc.detect_trend_direction([23, 12, 1]) == "subida"
    assert svc.detect_trend_direction([15, 15, 15]) == "lateral"
    assert svc.detect_trend_direction([5]) == "lateral"
    assert svc.detect_trend_direction([]) == "lateral"


def test_compute_bet_window_descida_clamps_at_top() -> None:
    out = svc.compute_bet_window(predicted=20, direction="descida", window_size=7)
    assert out == {"low": 20, "high": 26}

    clamped = svc.compute_bet_window(predicted=33, direction="descida", window_size=7)
    # high would be 39; must clamp so window stays size 7 inside [1,36]
    assert clamped == {"low": 30, "high": 36}


def test_compute_bet_window_subida_clamps_at_bottom() -> None:
    out = svc.compute_bet_window(predicted=20, direction="subida", window_size=7)
    assert out == {"low": 14, "high": 20}

    clamped = svc.compute_bet_window(predicted=3, direction="subida", window_size=7)
    # low would be -3; must clamp keeping size 7
    assert clamped == {"low": 1, "high": 7}


def test_find_historical_next_ranks_with_tolerance() -> None:
    items = [
        {"hit_rank": 9},   # 0 noise
        {"hit_rank": 2},   # 1 ── window [1..3] ─
        {"hit_rank": 14},  # 2
        {"hit_rank": 21},  # 3 ─ next of window [1..3]: items[4]
        {"hit_rank": 28},  # 4 ← historical "next" → 28
        {"hit_rank": 7},   # 5 noise
        {"hit_rank": 4},   # 6 ── window [6..8] ─
        {"hit_rank": 11},  # 7
        {"hit_rank": 22},  # 8 ─ next: items[9]
        {"hit_rank": 30},  # 9 ← historical "next" → 30
        {"hit_rank": 1},   # 10 current_seq[0]
        {"hit_rank": 12},  # 11 current_seq[1]
        {"hit_rank": 13},  # 12 current_seq[2] (ignored by find_historical: it filters j+n <= seq_start)
    ]
    # current_seq = [1, 12, 23]; seq_start index = 10 (so j+n must be <= 10)
    matches = svc.find_historical_next_ranks(items, current_seq_start=10, current_seq=[1, 12, 23], tolerance=3)
    assert sorted(matches) == [28, 30]


def test_find_historical_next_ranks_rejects_out_of_tolerance() -> None:
    items = [
        {"hit_rank": 5},
        {"hit_rank": 18},
        {"hit_rank": 30},  # window [0..2]: deltas (4,6,7) -> rejected at tol=3
        {"hit_rank": 25},  # would be next but pattern didn't match
    ]
    matches = svc.find_historical_next_ranks(items, current_seq_start=3, current_seq=[1, 12, 23], tolerance=3)
    assert matches == []


def test_get_numbers_for_window_handles_indexing() -> None:
    ranking = list(range(1, 37))  # ranking[0]=1 ... ranking[35]=36
    nums = svc.get_numbers_for_window(ranking, low=29, high=35)
    assert nums == [29, 30, 31, 32, 33, 34, 35]
    assert svc.get_numbers_for_window(ranking, low=1, high=3) == [1, 2, 3]
    assert svc.get_numbers_for_window([], low=1, high=3) == []


def test_median_simple() -> None:
    assert svc.median([28, 30]) == 29.0
    assert svc.median([28, 30, 32]) == 30.0
    assert svc.median([]) is None


# ---------------------------------------------------------------------------
# Helpers for end-to-end scenarios
# ---------------------------------------------------------------------------


def _make_item(idx: int, hit_rank: Optional[int], ranking: Optional[List[int]] = None) -> Dict[str, Any]:
    if ranking is None:
        ranking = list(range(1, 37))
    return {
        "snapshot_id": f"snap-{idx}",
        "anchor_history_id": f"hist-{idx}",
        "anchor_number": (idx % 36),
        "anchor_timestamp_utc": datetime(2026, 5, 6, 12, 0, idx, tzinfo=timezone.utc),
        "next_history_id": f"hist-{idx + 1}",
        "next_number": ((idx + 1) % 36),
        "next_timestamp_utc": datetime(2026, 5, 6, 12, 0, idx + 1, tzinfo=timezone.utc),
        "hit_rank": hit_rank,
        "ranking_full": list(ranking),
    }


def _build_descida_items_with_fresh_anchor() -> List[Dict[str, Any]]:
    """Two historical matches for sequence [1,12,23], plus a fresh anchor at the end."""
    ranks: List[Optional[int]] = [
        9,    # 0 noise
        2,    # 1 ── window [1..3]
        14,   # 2
        21,   # 3
        28,   # 4 ← historical next
        7,    # 5 noise
        4,    # 6 ── window [6..8]
        11,   # 7
        22,   # 8
        30,   # 9 ← historical next
        18,   # 10 noise
        15,   # 11 noise
        1,    # 12 current_seq[0]
        12,   # 13 current_seq[1]
        23,   # 14 current_seq[2]
        None, # 15 fresh anchor (no outcome yet)
    ]
    return [_make_item(i, r) for i, r in enumerate(ranks)]


class _UpsertResult:
    def __init__(self, upserted_id: Any) -> None:
        self.upserted_id = upserted_id


class _Cursor:
    def __init__(self, docs: List[Dict[str, Any]]) -> None:
        self._docs = list(docs)

    def sort(self, key: str, direction: int) -> "_Cursor":
        reverse = direction < 0
        try:
            self._docs.sort(key=lambda d: d.get(key) or datetime.min.replace(tzinfo=timezone.utc), reverse=reverse)
        except Exception:
            pass
        return self

    def limit(self, n: int) -> "_Cursor":
        self._docs = self._docs[: int(n)]
        return self

    async def to_list(self, length: Optional[int] = None) -> List[Dict[str, Any]]:
        return [deepcopy(d) for d in self._docs]


class _FakeSignalsColl:
    def __init__(self) -> None:
        self.docs: Dict[str, Dict[str, Any]] = {}

    def _matches(self, doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
        for k, v in query.items():
            if doc.get(k) != v:
                return False
        return True

    async def find_one(self, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        for doc in self.docs.values():
            if self._matches(doc, query):
                return deepcopy(doc)
        return None

    def find(self, query: Dict[str, Any]) -> _Cursor:
        return _Cursor([d for d in self.docs.values() if self._matches(d, query)])

    async def update_one(
        self,
        query: Dict[str, Any],
        update: Dict[str, Any],
        upsert: bool = False,
    ) -> _UpsertResult:
        target_id = None
        for _id, doc in self.docs.items():
            if self._matches(doc, query):
                target_id = _id
                break

        if target_id is None and upsert:
            new_doc: Dict[str, Any] = {}
            new_doc.update(update.get("$setOnInsert", {}))
            new_doc.update(update.get("$set", {}))
            new_id = query.get("_id") or new_doc.get("_id") or f"auto-{len(self.docs)}"
            new_doc["_id"] = new_id
            self.docs[new_id] = new_doc
            return _UpsertResult(upserted_id=new_id)

        if target_id is not None:
            doc = self.docs[target_id]
            for k, v in (update.get("$set") or {}).items():
                doc[k] = v
            # $setOnInsert deliberately ignored on existing doc
        return _UpsertResult(upserted_id=None)


def _install_mocks(
    monkeypatch,
    *,
    items: List[Dict[str, Any]],
    config: Dict[str, Any],
    fake_coll: _FakeSignalsColl,
) -> None:
    async def _no_op() -> None:
        return None

    async def _config() -> Dict[str, Any]:
        return deepcopy(config)

    async def _snap_config() -> Dict[str, Any]:
        return {"config_id": "snap"}

    async def _timeline(**_kwargs: Any) -> Dict[str, Any]:
        return {"items": deepcopy(items), "summary": {}}

    monkeypatch.setattr(svc, "ensure_suggestion_trend_indexes", _no_op)
    monkeypatch.setattr(svc, "get_or_create_trend_strategy_config", _config)
    monkeypatch.setattr(svc, "get_or_create_global_suggestion_snapshot_config", _snap_config)
    monkeypatch.setattr(svc, "build_suggestion_snapshot_config_key", lambda _doc: "test-key")
    monkeypatch.setattr(svc, "build_suggestion_snapshot_rank_timeline", _timeline)
    monkeypatch.setattr(svc, "suggestion_trend_signals_coll", fake_coll)


# ---------------------------------------------------------------------------
# End-to-end scenarios
# ---------------------------------------------------------------------------


def test_process_skips_when_disabled(monkeypatch) -> None:
    coll = _FakeSignalsColl()
    items = _build_descida_items_with_fresh_anchor()
    config = {"enabled": False, "steps": 3, "tolerance": 3, "window_size": 7, "max_attempts": 4, "history_lookback": 200}
    _install_mocks(monkeypatch, items=items, config=config, fake_coll=coll)

    outcome = asyncio.run(svc.process_trend_signal_for_roulette("rul-A"))
    assert outcome == {"skipped": "disabled"}
    assert coll.docs == {}


def test_process_creates_pending_signal_with_correct_window(monkeypatch) -> None:
    coll = _FakeSignalsColl()
    items = _build_descida_items_with_fresh_anchor()
    config = {"enabled": True, "steps": 3, "tolerance": 3, "window_size": 7, "max_attempts": 4, "history_lookback": 200}
    _install_mocks(monkeypatch, items=items, config=config, fake_coll=coll)

    outcome = asyncio.run(svc.process_trend_signal_for_roulette("rul-A"))

    assert outcome["created_signal_id"] is not None
    assert len(coll.docs) == 1
    sig = next(iter(coll.docs.values()))
    assert sig["roulette_id"] == "rul-A"
    assert sig["status"] == "pending"
    assert sig["trend_direction"] == "descida"
    assert sig["current_sequence"] == [1, 12, 23]
    assert sig["historical_matches_count"] == 2
    assert sorted(sig["historical_match_next_ranks"]) == [28, 30]
    assert sig["predicted_rank"] == 29
    assert sig["rank_low"] == 29 and sig["rank_high"] == 35
    assert sig["initial_bet_numbers"] == [29, 30, 31, 32, 33, 34, 35]
    assert sig["anchor_history_id"] == "hist-15"
    assert sig["attempts"] == []


def test_process_is_idempotent_for_same_anchor(monkeypatch) -> None:
    coll = _FakeSignalsColl()
    items = _build_descida_items_with_fresh_anchor()
    config = {"enabled": True, "steps": 3, "tolerance": 3, "window_size": 7, "max_attempts": 4, "history_lookback": 200}
    _install_mocks(monkeypatch, items=items, config=config, fake_coll=coll)

    asyncio.run(svc.process_trend_signal_for_roulette("rul-A"))
    asyncio.run(svc.process_trend_signal_for_roulette("rul-A"))

    assert len(coll.docs) == 1


def test_process_advances_pending_signal_to_won_on_attempt_one(monkeypatch) -> None:
    """First call creates pending; we then resolve items[15] with a hit and re-run."""

    coll = _FakeSignalsColl()
    items = _build_descida_items_with_fresh_anchor()
    config = {"enabled": True, "steps": 3, "tolerance": 3, "window_size": 7, "max_attempts": 4, "history_lookback": 200}
    _install_mocks(monkeypatch, items=items, config=config, fake_coll=coll)

    asyncio.run(svc.process_trend_signal_for_roulette("rul-A"))

    # Simulate next spin landing inside window [29..35]: items[15].hit_rank = 32, append a new fresh anchor
    items[15]["hit_rank"] = 32
    items.append(_make_item(16, hit_rank=None))
    _install_mocks(monkeypatch, items=items, config=config, fake_coll=coll)

    asyncio.run(svc.process_trend_signal_for_roulette("rul-A"))

    sig = next(iter(coll.docs.values()))
    assert sig["status"] == "won"
    assert sig["winning_attempt"] == 1
    assert sig["attempts_used"] == 1
    assert sig["attempts"][0]["hit"] is True
    assert sig["attempts"][0]["hit_rank"] == 32
    # PL = 36 - 1*7 = 29 (one chip wins 35:1, six lose at 1 each)
    assert sig["pl_chips"] == 29


def test_process_marks_signal_as_lost_after_max_attempts(monkeypatch) -> None:
    coll = _FakeSignalsColl()
    items = _build_descida_items_with_fresh_anchor()
    config = {"enabled": True, "steps": 3, "tolerance": 3, "window_size": 7, "max_attempts": 4, "history_lookback": 200}
    _install_mocks(monkeypatch, items=items, config=config, fake_coll=coll)
    asyncio.run(svc.process_trend_signal_for_roulette("rul-A"))

    # Fill 4 attempts all OUT of [29..35]
    miss_ranks = [5, 4, 8, 6]
    for offset, miss in enumerate(miss_ranks):
        items[15 + offset]["hit_rank"] = miss
        if 15 + offset + 1 >= len(items):
            items.append(_make_item(15 + offset + 1, hit_rank=None))

    _install_mocks(monkeypatch, items=items, config=config, fake_coll=coll)
    asyncio.run(svc.process_trend_signal_for_roulette("rul-A"))

    sig = next(iter(coll.docs.values()))
    assert sig["status"] == "lost"
    assert sig["winning_attempt"] is None
    assert sig["attempts_used"] == 4
    assert all(att["hit"] is False for att in sig["attempts"])
    # PL = -4 * 7 = -28
    assert sig["pl_chips"] == -28


def test_process_does_not_create_second_signal_while_pending(monkeypatch) -> None:
    coll = _FakeSignalsColl()
    items = _build_descida_items_with_fresh_anchor()
    config = {"enabled": True, "steps": 3, "tolerance": 3, "window_size": 7, "max_attempts": 4, "history_lookback": 200}
    _install_mocks(monkeypatch, items=items, config=config, fake_coll=coll)
    asyncio.run(svc.process_trend_signal_for_roulette("rul-A"))

    # First attempt missed (out of window) -> still pending; new fresh anchor added.
    items[15]["hit_rank"] = 4
    items.append(_make_item(16, hit_rank=None))
    _install_mocks(monkeypatch, items=items, config=config, fake_coll=coll)

    asyncio.run(svc.process_trend_signal_for_roulette("rul-A"))

    assert len(coll.docs) == 1, "must not create a second signal while one is pending"
    sig = next(iter(coll.docs.values()))
    assert sig["status"] == "pending"
    assert sig["attempts_used"] == 1
    assert sig["attempts"][0]["hit"] is False
