from __future__ import annotations

import asyncio

from api.routes import patterns
from api.routes.patterns import FinalSuggestionPolicyRequest, FinalSuggestionRequest


def test_build_simple_suggestion_counts_one_vote_per_positive_pattern() -> None:
    result = patterns._build_simple_suggestion_from_contributions(
        [
            {"pattern_id": "p1", "pattern_name": "Pattern 1", "numbers": [3, 5], "weight": 99.0},
            {"pattern_id": "p2", "pattern_name": "Pattern 2", "numbers": [3], "weight": 0.1},
            {"pattern_id": "p3", "pattern_name": "Pattern 3", "numbers": [7, 3], "weight": 0.01},
            {"pattern_id": "p4", "pattern_name": "Pattern 4", "numbers": [7], "weight": 500.0},
        ],
        focus_number=3,
        from_index=0,
        max_numbers=3,
    )

    assert result["available"] is True
    assert result["list"] == [3, 7, 5]
    assert result["pattern_count"] == 4
    assert result["unique_numbers"] == 3
    assert result["top_support_count"] == 3
    assert result["min_support_count"] == 1
    assert result["avg_support_count"] == 2.0
    assert result["number_details"][0]["number"] == 3
    assert result["number_details"][0]["support_score"] == 3
    assert result["number_details"][1]["number"] == 7
    assert result["number_details"][1]["support_score"] == 2


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
    assert result["simple_payload"]["available"] is False


def test_compute_final_suggestion_exposes_simple_payload_based_on_pattern_votes(monkeypatch) -> None:
    monkeypatch.setattr(patterns, "build_base_suggestion", lambda **kwargs: [4, 9, 15])
    monkeypatch.setattr(patterns.pattern_weight_profiles, "load_profile", lambda profile_id: None)

    monkeypatch.setattr(
        patterns.pattern_engine,
        "evaluate",
        lambda **kwargs: {
            "available": True,
            "suggestion": [3, 7, 5],
            "explanation": "ok",
            "confidence": {"score": 88, "label": "Alta"},
            "confidence_breakdown": {
                "calibrated_confidence_v2": 74,
            },
            "contributions": [
                {"pattern_id": "p1", "pattern_name": "Pattern 1", "numbers": [3, 5], "weight": 99.0},
                {"pattern_id": "p2", "pattern_name": "Pattern 2", "numbers": [3], "weight": 0.1},
                {"pattern_id": "p3", "pattern_name": "Pattern 3", "numbers": [7, 3], "weight": 0.01},
                {"pattern_id": "p4", "pattern_name": "Pattern 4", "numbers": [7], "weight": 500.0},
            ],
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
            "confidence": {"score": 66, "label": "Alta"},
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
        final_gate_require_optimized=False,
    )

    result = asyncio.run(patterns._compute_final_suggestion(payload))

    assert result["simple_payload"]["available"] is True
    assert result["simple_payload"]["list"] == [3, 7, 5]
    assert result["simple_suggestion"] == [3, 7, 5]
    assert result["simple_pattern_count"] == 4
    assert result["simple_payload"]["top_support_count"] == 3
    assert result["simple_payload"]["avg_support_count"] == 2.0
    assert result["simple_payload"]["entry_shadow"]["available"] is True
    assert result["simple_payload"]["entry_shadow"]["mode"] == "shadow"
    assert result["simple_payload"]["entry_shadow"]["economics"]["profits_by_attempt"]["hit_1"] == 33
    assert result["simple_entry_shadow"] == result["simple_payload"]["entry_shadow"]


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


def test_compute_final_suggestion_applies_protected_mode_and_cold_metadata(monkeypatch) -> None:
    monkeypatch.setattr(patterns, "build_base_suggestion", lambda **kwargs: [23, 13, 31, 32])
    monkeypatch.setattr(patterns.pattern_weight_profiles, "load_profile", lambda profile_id: None)

    monkeypatch.setattr(
        patterns.pattern_engine,
        "evaluate",
        lambda **kwargs: {
            "available": True,
            "suggestion": [23, 13, 31, 32],
            "explanation": "ok",
            "confidence": {"score": 88, "label": "Alta"},
            "confidence_breakdown": {
                "calibrated_confidence_v2": 74,
            },
            "contributions": [],
            "negative_contributions": [],
            "pending_patterns": [],
            "number_details": [{"number": n, "net_score": float(37 - n)} for n in range(37)],
            "adaptive_weights": [],
        },
    )
    monkeypatch.setattr(
        patterns,
        "build_final_suggestion",
        lambda **kwargs: {
            "available": True,
            "list": [23, 13, 31, 32],
            "protections": [22],
            "confidence": {"score": 66, "label": "Alta"},
            "explanation": "ok",
            "breakdown": {},
        },
    )
    monkeypatch.setattr(
        patterns,
        "build_protected_coverage_suggestion",
        lambda **kwargs: {
            "ordered_suggestion": [n for n in range(37) if n not in {12, 36}],
            "excluded_tail_numbers": [36, 12],
            "excluded_tail_reasons": [],
            "candidate_details": {},
            "base_is_cold": False,
            "base_cold_rank": None,
            "cold_numbers_considered": [36, 12],
            "protected_excluded_numbers": [36, 12],
            "protected_original_excluded_numbers": [36, 12],
            "protected_guard_numbers": [11, 12, 13, 35, 36],
            "protected_guard_details": {
                "11": [{"source": 12, "relation": "sequence"}],
            },
            "protected_wait_triggered": True,
            "protected_wait_matches": [{"source": 12, "relation": "sequence"}],
            "protected_wait_recommended_spins": 3,
            "protected_wait_reason": "Numero 11 tocou a zona protegida dos excluidos 36, 12 (sequencia numerica de 12). Aguarde 3 giros.",
            "cold_wait_recommended_spins": 3,
            "protected_swap_enabled": False,
            "protected_swap_applied": False,
            "protected_swap_summary": "",
            "protected_swap_details": [],
        },
    )
    monkeypatch.setattr(
        patterns,
        "analyze_wheel_temperature",
        lambda *args, **kwargs: {
            "cold_numbers": {23},
            "cold_ranking": [23, 7, 4],
            "score_map": {n: 0.0 for n in range(37)},
        },
    )

    payload = FinalSuggestionRequest(
        history=[23, 13, 31, 32, 4, 18, 29],
        focus_number=11,
        from_index=0,
        max_numbers=8,
        protected_mode_enabled=True,
        protected_suggestion_size=32,
        cold_count=18,
        entry_policy_enabled=False,
    )

    result = asyncio.run(patterns._compute_final_suggestion(payload))

    assert result["available"] is True
    assert result["ranking_locked"] is True
    assert result["protected_mode_enabled"] is True
    assert result["protected_suggestion_size"] == 35
    assert len(result["suggestion"]) == 35
    assert result["suggestion"][:5] == [0, 1, 2, 3, 4]
    assert result["excluded_tail_numbers"] == [36, 12]
    assert result["protected_excluded_numbers"] == [36, 12]
    assert result["protected_guard_numbers"] == [11, 12, 13, 35, 36]
    assert result["protected_wait_triggered"] is False
    assert result["protected_wait_recommended_spins"] == 0
    assert result["base_is_cold"] is False
    assert result["base_cold_rank"] is None
    assert result["cold_wait_recommended_spins"] == 0
    assert result["entry_policy"]["action"] == "enter"
    assert result["entry_policy"]["recommended_wait_spins"] == 0
    assert "fora da jogada" in result["entry_policy"]["reason"].lower()


def test_final_suggestion_policy_prefers_protected_wait_over_generic_entry_policy(monkeypatch) -> None:
    monkeypatch.setattr(patterns, "build_base_suggestion", lambda **kwargs: [23, 13, 31, 32])
    monkeypatch.setattr(patterns.pattern_weight_profiles, "load_profile", lambda profile_id: None)

    monkeypatch.setattr(
        patterns.pattern_engine,
        "evaluate",
        lambda **kwargs: {
            "available": True,
            "suggestion": [23, 13, 31, 32],
            "explanation": "ok",
            "confidence": {"score": 88, "label": "Alta"},
            "confidence_breakdown": {
                "calibrated_confidence_v2": 74,
            },
            "contributions": [],
            "negative_contributions": [],
            "pending_patterns": [],
            "number_details": [{"number": n, "net_score": float(37 - n)} for n in range(37)],
            "adaptive_weights": [],
        },
    )
    monkeypatch.setattr(
        patterns,
        "build_final_suggestion",
        lambda **kwargs: {
            "available": True,
            "list": [23, 13, 31, 32],
            "protections": [22],
            "confidence": {"score": 66, "label": "Alta"},
            "explanation": "ok",
            "breakdown": {},
        },
    )
    monkeypatch.setattr(
        patterns,
        "build_protected_coverage_suggestion",
        lambda **kwargs: {
            "ordered_suggestion": [n for n in range(37) if n not in {12, 36}],
            "excluded_tail_numbers": [36, 12],
            "excluded_tail_reasons": [],
            "candidate_details": {},
            "base_is_cold": False,
            "base_cold_rank": None,
            "cold_numbers_considered": [36, 12],
            "protected_excluded_numbers": [36, 12],
            "protected_original_excluded_numbers": [36, 12],
            "protected_guard_numbers": [11, 12, 13, 35, 36],
            "protected_guard_details": {
                "11": [{"source": 12, "relation": "sequence"}],
            },
            "protected_wait_triggered": True,
            "protected_wait_matches": [{"source": 12, "relation": "sequence"}],
            "protected_wait_recommended_spins": 3,
            "protected_wait_reason": "Numero 11 tocou a zona protegida dos excluidos 36, 12 (sequencia numerica de 12). Aguarde 3 giros.",
            "cold_wait_recommended_spins": 3,
            "protected_swap_enabled": False,
            "protected_swap_applied": False,
            "protected_swap_summary": "",
            "protected_swap_details": [],
        },
    )
    monkeypatch.setattr(
        patterns,
        "analyze_wheel_temperature",
        lambda *args, **kwargs: {
            "cold_numbers": {23},
            "cold_ranking": [23, 7, 4],
            "score_map": {n: 0.0 for n in range(37)},
        },
    )
    monkeypatch.setattr(
        patterns.final_suggestion_entry_intelligence,
        "recommend",
        lambda **kwargs: {
            "action": "wait",
            "label": "Esperar",
            "reason": "Overlap alto com contexto recente antes do gatilho. Melhor aguardar 2 giros.",
            "recommended_wait_spins": 2,
            "score": 10,
        },
    )

    payload = FinalSuggestionPolicyRequest(
        history=[23, 13, 31, 32, 4, 18, 29],
        focus_number=11,
        from_index=0,
        max_numbers=8,
        protected_mode_enabled=True,
        protected_suggestion_size=35,
        cold_count=18,
        entry_policy_enabled=True,
    )

    result = asyncio.run(patterns.get_final_suggestion_policy(payload))

    assert result["available"] is True
    assert result["decision"]["action"] == "enter"
    assert result["decision"]["label"] == "Cobertura protegida"
    assert result["decision"]["recommended_wait_spins"] == 0
    assert "fora da jogada" in result["decision"]["reason"].lower()
    assert "2 giros" not in result["decision"]["reason"]
    assert result["candidate_signal"]["protected_mode_enabled"] is True


def test_final_suggestion_policy_marks_saved_bet_when_protected_swap_applies(monkeypatch) -> None:
    monkeypatch.setattr(patterns, "build_base_suggestion", lambda **kwargs: [23, 13, 31, 32])
    monkeypatch.setattr(patterns.pattern_weight_profiles, "load_profile", lambda profile_id: None)

    monkeypatch.setattr(
        patterns.pattern_engine,
        "evaluate",
        lambda **kwargs: {
            "available": True,
            "suggestion": [23, 13, 31, 32],
            "explanation": "ok",
            "confidence": {"score": 88, "label": "Alta"},
            "confidence_breakdown": {
                "calibrated_confidence_v2": 74,
            },
            "contributions": [],
            "negative_contributions": [],
            "pending_patterns": [],
            "number_details": [{"number": n, "net_score": float(37 - n)} for n in range(37)],
            "adaptive_weights": [],
        },
    )
    monkeypatch.setattr(
        patterns,
        "build_final_suggestion",
        lambda **kwargs: {
            "available": True,
            "list": [23, 13, 31, 32],
            "protections": [22],
            "confidence": {"score": 66, "label": "Alta"},
            "explanation": "ok",
            "breakdown": {},
        },
    )
    monkeypatch.setattr(
        patterns,
        "build_protected_coverage_suggestion",
        lambda **kwargs: {
            "ordered_suggestion": [n for n in range(37) if n not in {3, 8}],
            "excluded_tail_numbers": [3, 8],
            "excluded_tail_reasons": [],
            "candidate_details": {},
            "base_is_cold": False,
            "base_cold_rank": None,
            "cold_numbers_considered": [3, 8],
            "protected_excluded_numbers": [3, 8],
            "protected_original_excluded_numbers": [3, 26],
            "protected_guard_numbers": [],
            "protected_guard_details": {},
            "protected_wait_triggered": False,
            "protected_wait_matches": [],
            "protected_wait_recommended_spins": 0,
            "protected_wait_reason": "",
            "cold_wait_recommended_spins": 0,
            "protected_swap_enabled": True,
            "protected_swap_applied": True,
            "protected_swap_summary": "Aposta salva no numero 16: trocas aplicadas 26->8. Fora da jogada agora: 3, 8.",
            "protected_swap_details": [
                {
                    "replaced_number": 26,
                    "replacement_number": 8,
                    "trigger_number": 16,
                    "trigger_matches": [{"source": 26, "relation": "same_terminal"}],
                    "trigger_reason": "mesmo terminal de 26",
                }
            ],
        },
    )
    monkeypatch.setattr(
        patterns,
        "analyze_wheel_temperature",
        lambda *args, **kwargs: {
            "cold_numbers": {23},
            "cold_ranking": [23, 7, 4],
            "score_map": {n: 0.0 for n in range(37)},
        },
    )
    monkeypatch.setattr(
        patterns.final_suggestion_entry_intelligence,
        "recommend",
        lambda **kwargs: {
            "action": "wait",
            "label": "Esperar",
            "reason": "Overlap alto com contexto recente antes do gatilho. Melhor aguardar 2 giros.",
            "recommended_wait_spins": 2,
            "score": 10,
        },
    )

    payload = FinalSuggestionPolicyRequest(
        history=[23, 13, 31, 32, 4, 18, 29],
        focus_number=16,
        from_index=0,
        max_numbers=8,
        protected_mode_enabled=True,
        protected_suggestion_size=35,
        protected_swap_enabled=True,
        cold_count=18,
        entry_policy_enabled=True,
    )

    result = asyncio.run(patterns.get_final_suggestion_policy(payload))

    assert result["available"] is True
    assert result["decision"]["action"] == "enter"
    assert result["decision"]["label"] == "Cobertura protegida"
    assert "fora da jogada" in result["decision"]["reason"].lower()
    assert result["candidate_signal"]["protected_swap_applied"] is False
    assert result["candidate_signal"]["protected_excluded_numbers"] == [3, 8]
