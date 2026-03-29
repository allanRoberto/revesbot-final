from __future__ import annotations

from api.services import decoder_live_monitor


def test_build_signal_candidate_accepts_eligible_analysis() -> None:
    analysis = {
        "summary": {
            "matched_episodes": 18,
            "selection_mode": "threshold",
            "future_horizon": 5,
        },
        "top_candidates": [
            {"number": 14},
            {"number": 27},
            {"number": 35},
            {"number": 7},
            {"number": 31},
            {"number": 9},
            {"number": 18},
        ],
        "suggestion": {
            "available": True,
            "primary_numbers": [14, 27, 35, 7],
            "secondary_numbers": [31, 9],
            "confidence": {"score": 68, "label": "Média"},
        },
        "similar_episodes": [{"similarity": 0.74}, {"similarity": 0.66}],
        "current_state": {"active_regimes": ["short_hops", "terminal_bias"]},
    }

    result = decoder_live_monitor.build_signal_candidate(
        analysis,
        include_secondary=True,
        max_numbers=6,
        min_confidence=55,
        min_matched_episodes=12,
        require_threshold_mode=True,
    )

    assert result["emit"] is True
    assert result["numbers"] == [14, 27, 35, 7, 31, 9]
    assert result["number_count_requested"] == 6
    assert result["number_count_used"] == 6
    assert result["confidence_score"] == 68
    assert result["matched_episodes"] == 18
    assert result["selection_mode"] == "threshold"


def test_build_signal_candidate_rejects_low_confidence() -> None:
    analysis = {
        "summary": {
            "matched_episodes": 30,
            "selection_mode": "threshold",
            "future_horizon": 5,
        },
        "suggestion": {
            "available": True,
            "primary_numbers": [5, 11],
            "secondary_numbers": [],
            "confidence": {"score": 42, "label": "Baixa"},
        },
        "similar_episodes": [{"similarity": 0.61}],
        "current_state": {"active_regimes": ["clustered_sector"]},
    }

    result = decoder_live_monitor.build_signal_candidate(
        analysis,
        min_confidence=55,
        min_matched_episodes=12,
    )

    assert result["emit"] is False
    assert "Confiança 42 abaixo do mínimo 55." in result["reason"]


def test_resolve_live_signal_marks_win_and_loss() -> None:
    base_signal = {
        "numbers": [14, 27, 35],
        "attempts": 0,
        "max_attempts": 3,
    }

    win_signal = decoder_live_monitor.resolve_live_signal(base_signal, number=27)
    assert win_signal["status"] == "win"
    assert win_signal["hit_number"] == 27
    assert win_signal["hit_attempt"] == 1

    loss_step_1 = decoder_live_monitor.resolve_live_signal(base_signal, number=8)
    assert loss_step_1["status"] == "active"

    loss_step_2 = decoder_live_monitor.resolve_live_signal(loss_step_1, number=9)
    assert loss_step_2["status"] == "active"

    loss_step_3 = decoder_live_monitor.resolve_live_signal(loss_step_2, number=10)
    assert loss_step_3["status"] == "loss"
    assert loss_step_3["resolved"] is True


def test_build_signal_candidate_can_expand_to_requested_count_from_ranked_candidates() -> None:
    analysis = {
        "summary": {
            "matched_episodes": 14,
            "selection_mode": "threshold",
            "future_horizon": 5,
        },
        "top_candidates": [
            {"number": 30},
            {"number": 6},
            {"number": 13},
            {"number": 5},
            {"number": 26},
            {"number": 24},
            {"number": 25},
            {"number": 7},
            {"number": 18},
            {"number": 1},
            {"number": 8},
            {"number": 19},
        ],
        "suggestion": {
            "available": True,
            "primary_numbers": [30, 6, 13, 5],
            "secondary_numbers": [26, 24],
            "confidence": {"score": 64, "label": "Média"},
        },
        "similar_episodes": [{"similarity": 0.71}],
        "current_state": {"active_regimes": ["short_hops"]},
    }

    result = decoder_live_monitor.build_signal_candidate(
        analysis,
        max_numbers=12,
        min_confidence=55,
        min_matched_episodes=12,
    )

    assert result["emit"] is True
    assert result["numbers"] == [30, 6, 13, 5, 26, 24, 25, 7, 18, 1, 8, 19]
    assert result["number_count_used"] == 12
