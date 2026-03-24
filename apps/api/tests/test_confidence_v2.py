from __future__ import annotations

import json

from api.patterns.engine import PatternEngine
from api.services.confidence_calibration import ConfidenceCalibrationStore


SAFE_NUMBERS = [1, 2, 3, 4, 6, 7, 8, 9, 11, 12, 13, 14, 15, 17, 18, 19, 20, 21, 22, 23, 25, 26, 27, 28]


def _history_from_timeline(timeline: list[int]) -> list[int]:
    return list(reversed(timeline))


def _timeline_with_repeat(base: int, filler: list[int]) -> list[int]:
    return [base, base, *filler]


class _StubCalibration:
    def calibrate(self, score: int) -> dict:
        return {
            "score": 67,
            "bucket": "60-69",
            "hit_rate": 0.71,
            "promptness_score": 62.0,
            "reliability": 0.9,
            "signals": 190,
            "avg_first_hit_attempt": 3.2,
            "attempt_rates": {
                "hit@1": 0.22,
                "hit@2": 0.44,
                "hit@4": 0.71,
                "hit@8": 0.79,
                "hit@10": 0.83,
            },
        }


def test_confidence_calibration_store_uses_bucket_hit_rate_and_reliability(tmp_path) -> None:
    config = {
        "version": "1.0.0",
        "mode": "shadow",
        "bucket_signal_target": 150,
        "source": {"type": "snapshot_cache", "details": {}},
        "buckets": {
            "50-59": {
                "signals": 180,
                "hit_rate": 0.74,
                "promptness_score": 58.0,
                "avg_first_hit_attempt": 3.5,
                "hit@1": 0.18,
                "hit@2": 0.39,
                "hit@4": 0.74,
                "hit@8": 0.82,
                "hit@10": 0.84,
                "reliability": 0.8,
            }
        },
    }
    path = tmp_path / "confidence_v2_calibration.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    store = ConfidenceCalibrationStore(config_path=path)
    calibrated = store.calibrate(54)

    assert calibrated["bucket"] == "50-59"
    assert calibrated["hit_rate"] == 0.74
    assert calibrated["promptness_score"] == 58.0
    assert calibrated["reliability"] == 0.8
    assert calibrated["avg_first_hit_attempt"] == 3.5
    assert calibrated["attempt_rates"]["hit@2"] == 0.39
    assert calibrated["score"] == 57


def test_confidence_v2_merge_is_stable_without_legacy_overlap() -> None:
    merged = PatternEngine._merge_confidence_v2(
        structural_score=62,
        legacy_score=0,
        suggestion=[5, 10, 24],
        legacy_numbers=[],
    )

    assert merged["score"] == 62
    assert merged["api_weight"] == 1.0
    assert merged["legacy_weight"] == 0.0
    assert merged["overlap_ratio"] == 0.0


def test_engine_evaluate_exposes_v2_shadow_breakdown_fields(tmp_path) -> None:
    definition = {
        "id": "exact_repeat_delayed_entry",
        "name": "Exact Repeat Delayed Entry",
        "kind": "positive",
        "version": "1.0.0",
        "active": True,
        "priority": 102,
        "weight": 4.2,
        "evaluator": "exact_repeat_delayed_entry",
        "max_numbers": 16,
        "params": {
            "attempts_per_count": 3,
            "cancel_lookback": 4,
            "base_score": 1.0,
            "near_neighbor_score": 0.9,
            "far_neighbor_score": 0.75,
            "zero_score": 0.7,
        },
    }
    (tmp_path / "exact_repeat_delayed_entry.json").write_text(json.dumps(definition), encoding="utf-8")

    engine = PatternEngine(patterns_dir=tmp_path)
    engine._confidence_calibration = _StubCalibration()

    history = _history_from_timeline(_timeline_with_repeat(24, SAFE_NUMBERS[:23]))
    result = engine.evaluate(history, use_adaptive_weights=False, use_fallback=False)
    breakdown = result["confidence_breakdown"]

    assert "structural_raw_v2" in breakdown
    assert "merged_raw_v2" in breakdown
    assert breakdown["calibrated_confidence_v2"] == 67
    assert breakdown["calibration_bucket"] == "60-69"
    assert breakdown["calibration_bucket_hit4"] == 0.71
    assert breakdown["calibration_bucket_promptness_v2"] == 62.0
    assert breakdown["calibration_reliability"] == 0.9
    assert breakdown["calibration_avg_first_hit_attempt_v2"] == 3.2
    assert breakdown["calibration_bucket_hit1"] == 0.22
    assert breakdown["calibration_bucket_hit2"] == 0.44
    assert breakdown["calibration_bucket_hit8"] == 0.79
    assert breakdown["calibration_bucket_hit10"] == 0.83
    assert result["confidence"]["score"] != 67
    assert result["confidence_breakdown"]["confidence_v2_shadow"]["score"] == 67
