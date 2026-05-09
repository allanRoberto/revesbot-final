from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
APPS_DIR = ROOT / "apps"
if str(APPS_DIR) not in sys.path:
    sys.path.insert(0, str(APPS_DIR))


class _DummyCollection:
    def __getattr__(self, name: str):
        raise RuntimeError(f"Unexpected DB access in unit test: {name}")


def _load_service_module():
    sentinel = object()
    module_names = ("bson", "api.core.db", "api.routes.patterns")
    originals = {name: sys.modules.get(name, sentinel) for name in module_names}

    bson_module = types.ModuleType("bson")

    class ObjectId:
        pass

    bson_module.ObjectId = ObjectId
    sys.modules["bson"] = bson_module

    db_module = types.ModuleType("api.core.db")
    db_module.history_coll = _DummyCollection()
    db_module.suggestion_snapshot_configs_coll = _DummyCollection()
    db_module.suggestion_snapshots_coll = _DummyCollection()
    sys.modules["api.core.db"] = db_module

    patterns_module = types.ModuleType("api.routes.patterns")

    class FinalSuggestionRequest:
        pass

    async def _compute_final_suggestion(*args, **kwargs):
        raise RuntimeError("Unexpected final suggestion call in unit test")

    patterns_module.FinalSuggestionRequest = FinalSuggestionRequest
    patterns_module._compute_final_suggestion = _compute_final_suggestion
    sys.modules["api.routes.patterns"] = patterns_module

    spec = importlib.util.spec_from_file_location(
        "_suggestion_snapshot_service_under_test",
        APPS_DIR / "api" / "services" / "suggestion_snapshot_service.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        for name, original in originals.items():
            if original is sentinel:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
    return module


service = _load_service_module()


def _item_for_hit(rank: int) -> dict:
    ranking = list(range(37))
    return {
        "hit_rank": rank,
        "plot_rank": rank,
        "ranking_full": ranking,
        "next_number": ranking[rank - 1],
    }


def test_optimized_ranking_uses_depth() -> None:
    ranking = list(range(1, 38))

    depth_5 = service._build_optimized_ranking(ranking, 5)
    depth_8 = service._build_optimized_ranking(ranking, 8)
    depth_10 = service._build_optimized_ranking(ranking, 10)

    assert depth_5[:5] == [37, 36, 35, 34, 33]
    assert depth_8[:8] == [37, 36, 35, 34, 33, 32, 31, 30]
    assert depth_10[:10] == [37, 36, 35, 34, 33, 32, 31, 30, 29, 28]
    assert len({tuple(depth_5), tuple(depth_8), tuple(depth_10)}) == 3


def test_inversion_mapping_has_no_rank_collisions() -> None:
    for depth in service.STRATEGY_DEPTH_OPTIONS:
        mapped = [service._invert_rank_zones(rank, depth) for rank in range(1, 38)]
        assert sorted(mapped) == list(range(1, 38))


def test_current_hit_rank_does_not_cancel_walk_forward_decision() -> None:
    items = [_item_for_hit(1), _item_for_hit(10), _item_for_hit(1)]

    service._apply_inversion_strategy(items)

    assert items[2]["strategy_triggered"] is True
    assert items[2]["strategy_invert_depth"] == service.STRATEGY_SMALL_EDGE_SIZE
    assert items[2]["strategy_mode"] == "inverted_extremes"


def test_confidence_preview_uses_zone_mapping_not_arithmetic_mirror() -> None:
    items = [_item_for_hit(1), _item_for_hit(10), _item_for_hit(1)]

    service._apply_inversion_strategy(items)

    assert items[2]["strategy_inverted_rank_preview"] == service._invert_rank_zones(10, 5)
    assert items[2]["strategy_inverted_rank_preview"] != 38 - 10


def test_rolling_zigzag_gate_is_directional() -> None:
    after_top = service._resolve_rolling_zigzag_gate(
        [35, 2, 34, 3, 33, 4, 32, 5],
        top_end=10,
        bottom_start=28,
    )
    after_bottom = service._resolve_rolling_zigzag_gate(
        [2, 35, 3, 34, 4, 33, 5, 32],
        top_end=10,
        bottom_start=28,
    )

    assert after_top["active"] is True
    assert after_top["action"] == "invert"
    assert after_bottom["active"] is True
    assert after_bottom["action"] == "keep_normal"
