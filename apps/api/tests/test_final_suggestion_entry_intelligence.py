from __future__ import annotations

from api.services.final_suggestion_entry_intelligence import FinalSuggestionEntryIntelligenceService


def test_enters_when_recent_region_was_touched() -> None:
    service = FinalSuggestionEntryIntelligenceService()

    decision = service.recommend(
        active_signal=None,
        candidate_signal={
            "suggestion": [32, 15, 19, 4],
            "confidence_score": 72,
            "suggestion_size": 4,
            "policy_score": 66.0,
        },
        history=[15, 8, 22, 31, 4, 10, 12],
    )

    assert decision["action"] == "enter"
    assert decision["touch_exact"] >= 1


def test_waits_when_last_number_is_two_steps_away_from_active_signal() -> None:
    service = FinalSuggestionEntryIntelligenceService()

    decision = service.recommend(
        active_signal={
            "suggestion": [32, 15, 19, 4],
            "confidence_score": 70,
            "suggestion_size": 4,
            "policy_score": 64.0,
            "attempts_used": 1,
            "max_attempts": 4,
            "wait_spins": 1,
        },
        candidate_signal={
            "suggestion": [11, 17, 20, 24],
            "confidence_score": 68,
            "suggestion_size": 4,
            "policy_score": 62.0,
        },
        history=[2, 8, 22, 31, 4, 10],
    )

    assert decision["action"] == "wait"
    assert decision["last_distance"] == 2


def test_switches_when_candidate_aligns_better_after_wait() -> None:
    service = FinalSuggestionEntryIntelligenceService()

    decision = service.recommend(
        active_signal={
            "suggestion": [0, 3, 12, 15, 19, 26],
            "confidence_score": 66,
            "suggestion_size": 6,
            "policy_score": 57.0,
            "attempts_used": 2,
            "max_attempts": 4,
            "wait_spins": 3,
        },
        candidate_signal={
            "suggestion": [20, 22, 29, 31],
            "confidence_score": 69,
            "suggestion_size": 4,
            "policy_score": 63.0,
        },
        history=[29, 20, 22, 31, 18, 7],
    )

    assert decision["action"] == "switch"
    assert decision["candidate_last_distance"] <= decision["last_distance"]


def test_waits_on_overlap_policy_for_low_confidence_candidate() -> None:
    service = FinalSuggestionEntryIntelligenceService()

    decision = service.recommend(
        active_signal=None,
        candidate_signal={
            "suggestion": [4, 9, 15, 22],
            "confidence_score": 58,
            "suggestion_size": 4,
            "policy_score": 52.0,
        },
        history=[4, 15, 22, 9, 31, 18, 7],
        from_index=0,
        overlap_window=3,
        high_confidence_cutoff=60,
    )

    assert decision["action"] == "wait"
    assert decision["recommended_wait_spins"] == 2
    assert decision["entry_overlap_group"] == "3+"
