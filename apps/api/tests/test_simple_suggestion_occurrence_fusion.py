from api.services import simple_suggestion_occurrence_fusion as fusion


def test_occurrence_tail_replace_injects_strong_occurrence_numbers(monkeypatch) -> None:
    monkeypatch.setattr(
        fusion,
        "normalize_history_desc",
        lambda history, history_limit: list(history)[:history_limit],
    )
    monkeypatch.setattr(
        fusion,
        "build_occurrence_snapshot",
        lambda *args, **kwargs: {
            "available": True,
            "ranking": [7, 3, 11, 12],
            "ranking_details": [
                {"number": 7, "count": 5},
                {"number": 3, "count": 4},
                {"number": 11, "count": 4},
                {"number": 12, "count": 3},
            ],
            "cancelled_reason": None,
            "inverted_evaluation": {"hit_offsets": [], "hit_count": 0},
        },
    )

    simple_payload = {
        "available": True,
        "list": [3, 7, 5],
        "suggestion": [3, 7, 5],
        "number_details": [
            {"number": 3, "support_score": 5, "support_count": 5, "weighted_support_score": 5.0},
            {"number": 7, "support_score": 7, "support_count": 7, "weighted_support_score": 7.0},
            {"number": 5, "support_score": 4, "support_count": 4, "weighted_support_score": 4.0},
        ],
        "selected_number_details": [],
        "explanation": "ok",
    }

    result = fusion.apply_occurrence_rerank_to_simple_suggestion(
        simple_payload=simple_payload,
        history=[4, 7, 9, 4, 7, 8, 4, 3, 6],
        focus_number=4,
        from_index=0,
        enabled=True,
        history_limit=2000,
        window_before=1,
        window_after=1,
        ranking_size=4,
        invert_check_window=0,
        pattern_weight=0.75,
        occurrence_weight=0.25,
        overlap_bonus=0.05,
        tail_replace_limit=1,
    )

    assert result["pre_fusion_list"] == [3, 7, 5]
    assert result["list"] == [7, 3, 11]
    assert result["occurrence_tail_replace_applied"] is True
    assert result["occurrence_only_numbers_injected"] == [11]
    assert result["occurrence_fusion"]["mode"] == "rerank_tail_replace"
    assert result["occurrence_fusion"]["tail_replace_applied"] is True
    assert result["occurrence_fusion"]["tail_replacements"] == [
        {
            "index": 2,
            "removed_number": 5,
            "inserted_number": 11,
            "inserted_occurrence_count": 4,
            "inserted_occurrence_norm": 0.8,
        }
    ]
