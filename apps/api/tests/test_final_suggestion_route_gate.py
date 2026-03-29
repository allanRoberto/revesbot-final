from __future__ import annotations

import asyncio

from api.routes import patterns
from api.routes.patterns import FinalSuggestionRequest


def test_compute_final_suggestion_blocks_when_optimized_engine_has_no_support(monkeypatch) -> None:
    monkeypatch.setattr(patterns, "build_base_suggestion", lambda **kwargs: [4, 9, 15])
    monkeypatch.setattr(patterns.pattern_weight_profiles, "load_profile", lambda profile_id: None)

    def fake_evaluate(**kwargs):
        return {
            "available": False,
            "suggestion": [],
            "explanation": "Sinal filtrado: Confianca baixa",
            "filter_reason": "Confianca baixa",
            "confidence": {"score": 0, "label": "Baixa"},
            "confidence_breakdown": patterns.pattern_engine._empty_confidence_breakdown(),
            "contributions": [],
            "negative_contributions": [],
            "pending_patterns": [],
            "number_details": [],
            "adaptive_weights": [],
        }

    monkeypatch.setattr(patterns.pattern_engine, "evaluate", fake_evaluate)

    payload = FinalSuggestionRequest(
        history=[4, 9, 15, 22, 31, 18],
        focus_number=4,
        from_index=0,
        max_numbers=3,
        entry_policy_enabled=False,
        final_gate_require_optimized=True,
    )

    result = asyncio.run(patterns._compute_final_suggestion(payload))

    assert result["available"] is False
    assert result["candidate_list"] == [4, 9, 15]
    assert result["suggestion"] == []
    assert result["emission_gate"]["optimized_supported"] is False
    assert any("Motor otimizado" in reason for reason in result["emission_gate"]["reasons"])


def test_compute_final_suggestion_blocks_when_entry_policy_recommends_wait(monkeypatch) -> None:
    monkeypatch.setattr(patterns, "build_base_suggestion", lambda **kwargs: [4, 9, 15])
    monkeypatch.setattr(patterns.pattern_weight_profiles, "load_profile", lambda profile_id: None)

    def fake_evaluate(**kwargs):
        return {
            "available": True,
            "suggestion": [4, 9, 15],
            "explanation": "ok",
            "confidence": {"score": 88, "label": "Alta"},
            "confidence_breakdown": {
                "calibrated_confidence_v2": 74,
            },
            "contributions": [{"pattern_id": "p1", "pattern_name": "Pattern 1"}],
            "negative_contributions": [],
            "pending_patterns": [],
            "number_details": [],
            "adaptive_weights": [],
        }

    monkeypatch.setattr(patterns.pattern_engine, "evaluate", fake_evaluate)
    monkeypatch.setattr(
        patterns.final_suggestion_entry_intelligence,
        "recommend",
        lambda **kwargs: {
            "action": "wait",
            "label": "Esperar",
            "reason": "Overlap alto",
            "recommended_wait_spins": 2,
        },
    )

    payload = FinalSuggestionRequest(
        history=[4, 9, 15, 22, 31, 18],
        focus_number=4,
        from_index=0,
        max_numbers=3,
        entry_policy_enabled=True,
        final_gate_require_optimized=True,
        final_gate_use_confidence_v2=True,
    )

    result = asyncio.run(patterns._compute_final_suggestion(payload))

    assert result["available"] is False
    assert result["candidate_list"] == [4, 9, 15]
    assert result["candidate_confidence"]["score"] == 56
    assert result["optimized_confidence_effective"] == 74
    assert result["emission_gate"]["entry_policy_action"] == "wait"
    assert result["emission_gate"]["entry_policy_wait_spins"] == 2
    assert result["suggestion"] == []


def test_compute_final_suggestion_blocks_when_candidate_confidence_is_below_minimum(monkeypatch) -> None:
    monkeypatch.setattr(patterns, "build_base_suggestion", lambda **kwargs: [4, 9, 15])
    monkeypatch.setattr(patterns.pattern_weight_profiles, "load_profile", lambda profile_id: None)

    monkeypatch.setattr(
        patterns.pattern_engine,
        "evaluate",
        lambda **kwargs: {
            "available": True,
            "suggestion": [4, 9, 15],
            "explanation": "ok",
            "confidence": {"score": 52, "label": "Média"},
            "confidence_breakdown": {
                "calibrated_confidence_v2": 38,
            },
            "contributions": [],
            "negative_contributions": [],
            "pending_patterns": [],
            "number_details": [],
            "adaptive_weights": [],
        },
    )
    monkeypatch.setattr(
        patterns,
        "build_final_suggestion",
        lambda **kwargs: {
            "available": True,
            "list": [4, 9, 15],
            "protections": [],
            "confidence": {"score": 35, "label": "Baixa"},
            "explanation": "ok",
            "breakdown": {},
        },
    )

    payload = FinalSuggestionRequest(
        history=[4, 9, 15, 22, 31, 18],
        focus_number=4,
        from_index=0,
        max_numbers=3,
        entry_policy_enabled=False,
        final_gate_require_optimized=True,
        final_gate_min_confidence=40,
    )

    result = asyncio.run(patterns._compute_final_suggestion(payload))

    assert result["available"] is False
    assert result["candidate_list"] == [4, 9, 15]
    assert result["candidate_confidence"]["score"] == 35
    assert result["emission_gate"]["min_confidence"] == 40
    assert result["emission_gate"]["candidate_confidence"] == 35
    assert any("Confidence final abaixo do mínimo" in reason for reason in result["emission_gate"]["reasons"])
