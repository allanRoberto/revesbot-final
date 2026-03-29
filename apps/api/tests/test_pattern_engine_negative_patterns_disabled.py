from __future__ import annotations

import json

from api.patterns.engine import PatternEngine


def test_engine_ignores_negative_patterns_when_negativation_is_disabled(tmp_path) -> None:
    positive_definition = {
        "id": "positive_stub",
        "name": "Positive Stub",
        "kind": "positive",
        "version": "1.0.0",
        "active": True,
        "priority": 10,
        "weight": 1.0,
        "evaluator": "positive_stub",
        "max_numbers": 5,
        "params": {},
    }
    negative_definition = {
        "id": "negative_stub",
        "name": "Negative Stub",
        "kind": "negative",
        "version": "1.0.0",
        "active": True,
        "priority": 11,
        "weight": 1.0,
        "evaluator": "negative_stub",
        "max_numbers": 5,
        "params": {},
    }
    (tmp_path / "positive_stub.json").write_text(json.dumps(positive_definition), encoding="utf-8")
    (tmp_path / "negative_stub.json").write_text(json.dumps(negative_definition), encoding="utf-8")

    engine = PatternEngine(patterns_dir=tmp_path)
    engine._evaluator_registry["positive_stub"] = lambda *args, **kwargs: {
        "numbers": [9],
        "scores": {9: 1.0},
        "explanation": "positive",
    }
    engine._evaluator_registry["negative_stub"] = lambda *args, **kwargs: {
        "numbers": [9],
        "scores": {9: 1.0},
        "explanation": "negative",
    }
    engine.apply_suggestion_filter = lambda **kwargs: {"passed": True, "reason": "", "filter_details": {}}

    result = engine.evaluate(
        history=[9, 22, 18, 29, 7, 28],
        use_adaptive_weights=False,
        use_fallback=False,
    )

    assert result["available"] is True
    assert result["suggestion"] == [9]
    assert result["negative_contributions"] == []
    assert "0 padrao(es) negativos aplicados." in result["explanation"]

    detail = next(item for item in result["number_details"] if item["number"] == 9)
    assert detail["negative_score"] == 0.0
    assert detail["negative_patterns"] == []
