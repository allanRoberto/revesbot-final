from __future__ import annotations

from api.services.final_suggestion_signal_policy import FinalSuggestionSignalPolicyService


def test_switch_policy_detects_when_newer_signal_hits_faster() -> None:
    service = FinalSuggestionSignalPolicyService()

    result = service.analyze_cases(
        cases=[
            {
                "from_index": 10,
                "focus_number": 4,
                "confidence_score": 62,
                "suggestion": [1, 2, 3, 4],
                "suggestion_size": 4,
                "policy_score": 56.0,
                "future_numbers": [30, 9, 15, 1],
                "extended_future_numbers": [30, 9, 15, 1, 0],
                "exact_hit_step": 4,
            },
            {
                "from_index": 9,
                "focus_number": 9,
                "confidence_score": 78,
                "suggestion": [9, 10, 11],
                "suggestion_size": 3,
                "policy_score": 73.5,
                "future_numbers": [9, 12, 18, 0],
                "extended_future_numbers": [9, 12, 18, 0, 1],
                "exact_hit_step": 1,
            },
        ],
        max_attempts=4,
        switch_window=2,
        switch_min_score_delta=6.0,
        switch_min_confidence_delta=4,
        switch_min_hold_spins=1,
    )

    switch = result["policies"]["switch_if_better"]

    assert switch["switch_rate"] == 0.5
    assert switch["improved_rate"] == 1.0
    assert switch["avg_saved_steps"] == 2.0
    assert result["opportunities"][0]["saved_steps"] == 2


def test_wait_policy_can_arm_after_pressure_and_capture_later_repeat() -> None:
    service = FinalSuggestionSignalPolicyService()

    result = service.analyze_cases(
        cases=[
            {
                "from_index": 8,
                "focus_number": 7,
                "confidence_score": 70,
                "suggestion": [7, 8],
                "suggestion_size": 2,
                "policy_score": 67.0,
                "future_numbers": [30, 7, 30, 8],
                "extended_future_numbers": [30, 7, 30, 8, 14],
            },
        ],
        max_attempts=4,
        observation_window=2,
        pressure_window=3,
        min_block_touches=1,
        min_near_touches=2,
        confirm_window=2,
    )

    wait_policy = result["policies"]["wait_for_pressure"]
    behavior = result["behavior"]

    assert wait_policy["armed_rate"] == 1.0
    assert wait_policy["hit_rate"] == 1.0
    assert wait_policy["avg_hit_delay"] == 4.0
    assert wait_policy["missed_fast_hit_rate"] == 1.0
    assert behavior["repeat_after_exact_rate"] == 1.0


def test_recommend_live_transition_prefers_switch_when_candidate_is_clearly_better() -> None:
    service = FinalSuggestionSignalPolicyService()

    decision = service.recommend_live_transition(
        active_signal={
            "suggestion": [1, 2, 3, 4],
            "confidence_score": 60,
            "suggestion_size": 4,
            "attempts_used": 1,
            "max_attempts": 4,
            "policy_score": 54.0,
        },
        candidate_signal={
            "suggestion": [9, 10],
            "confidence_score": 76,
            "suggestion_size": 2,
            "policy_score": 73.0,
            "block_compaction_applied": True,
        },
        observation_window=2,
        min_hold_spins=1,
        switch_min_score_delta=6.0,
        switch_min_confidence_delta=4,
    )

    assert decision["action"] == "switch"
    assert decision["saved_steps_estimate"] >= 1
