from __future__ import annotations

from apps.monitoring.src.ml_meta_rank import (
    build_default_ml_meta_rank_state,
    build_ml_meta_rank_payload_from_context,
    train_ml_meta_rank_state_from_resolved_event,
)


def _base_payload() -> dict:
    selected_details = [
        {
            "number": index,
            "support_score": max(1, 40 - index),
            "weighted_support_score": round(12.0 - (index * 0.22), 4),
            "supporting_patterns": [
                {
                    "pattern_id": "pattern_hot" if index % 3 == 0 else "pattern_cold",
                    "base_pattern_id": "pattern_hot" if index % 3 == 0 else "pattern_cold",
                    "pattern_name": "Pattern Hot" if index % 3 == 0 else "Pattern Cold",
                    "applied_weight": 1.35 if index % 3 == 0 else 0.92,
                }
            ],
        }
        for index in range(37)
    ]
    return {
        "available": True,
        "list": [item["number"] for item in selected_details],
        "suggestion": [item["number"] for item in selected_details],
        "selected_number_details": selected_details,
        "pattern_count": 22,
        "unique_numbers": 37,
        "entry_shadow": {
            "entry_confidence": {"score": 74, "base_score_before_rank_feedback": 81},
            "rank_context_confidence": {
                "confidence_delta": -4,
                "latest_rank_band": "top",
                "avg_rank_ratio": 0.62,
                "zigzag_rate": 0.58,
                "worsening_strength": 0.66,
                "improvement_strength": 0.18,
                "top_band_share": 0.18,
                "lower_band_share": 0.44,
            },
        },
        "dynamic_weighting": {
            "weights": {"pattern_hot": 1.42, "pattern_cold": 0.81},
        },
    }


def _top26_payload() -> dict:
    details = []
    for index in range(37):
        details.append(
            {
                "number": index,
                "top26_candidate": index < 26,
                "top26_reranked_position": index + 1,
                "top26_rerank_score": round(1.0 - (index / 40.0), 6),
                "top26_suggestion_memory": round(0.85 - (index * 0.01), 6),
                "top26_result_memory": round(0.70 - (index * 0.008), 6),
                "top26_regional_persistence": round(0.66 - (index * 0.007), 6),
                "top26_persistence": round(0.75 - (index * 0.01), 6),
                "top26_volatility_penalty": round(index / 50.0, 6),
            }
        )
    return {
        "available": True,
        "list": [item["number"] for item in details],
        "selected_number_details": details,
    }


def _time_window_payload() -> dict:
    details = []
    for index in range(37):
        details.append(
            {
                "number": index,
                "time_window_reranked_position": index + 1,
                "time_window_exact_prior": round(0.8 - (index * 0.01), 6),
                "time_window_region_prior": round(0.7 - (index * 0.008), 6),
                "time_window_final_score": round(0.9 - (index * 0.012), 6),
            }
        )
    return {
        "available": True,
        "list": [item["number"] for item in details],
        "selected_number_details": details,
    }


def test_build_ml_meta_rank_payload_creates_feature_snapshot_for_37_numbers() -> None:
    model_state = build_default_ml_meta_rank_state(
        roulette_id="pragmatic-auto-roulette",
        config_key="cfg-ml",
    )
    payload = build_ml_meta_rank_payload_from_context(
        base_payload=_base_payload(),
        top26_payload=_top26_payload(),
        time_window_prior_payload=_time_window_payload(),
        history_values=[17, 3, 28, 12, 17, 31, 5, 22],
        model_state=model_state,
        roulette_id="pragmatic-auto-roulette",
        config_key="cfg-ml",
    )

    assert payload is not None
    assert payload["available"] is True
    assert len(payload["suggestion"]) == 37
    assert payload["oscillation"]["profile"] == "ml_meta_rank_v1"
    snapshot = payload["oscillation"]["ml_meta_rank"]["candidate_features"]
    assert len(snapshot) == 37
    assert "base_weighted_support_norm" in snapshot[0]["features"]
    assert "time_region_prior" in snapshot[0]["features"]
    assert "history_region_density" in snapshot[0]["features"]


def test_train_ml_meta_rank_state_updates_weights_after_resolved_event() -> None:
    model_state = build_default_ml_meta_rank_state(
        roulette_id="pragmatic-auto-roulette",
        config_key="cfg-ml",
    )
    payload = build_ml_meta_rank_payload_from_context(
        base_payload=_base_payload(),
        top26_payload=_top26_payload(),
        time_window_prior_payload=_time_window_payload(),
        history_values=[17, 3, 28, 12, 17, 31, 5, 22],
        model_state=model_state,
        roulette_id="pragmatic-auto-roulette",
        config_key="cfg-ml",
    )

    updated_state = train_ml_meta_rank_state_from_resolved_event(
        model_state,
        {
            "_id": "ml-evt-1",
            "resolved_number": 0,
            "resolved_rank_position": 4,
            "oscillation": payload["oscillation"],
        },
        roulette_id="pragmatic-auto-roulette",
        config_key="cfg-ml",
    )

    assert updated_state["trained_events"] == 1
    assert updated_state["trained_rows"] > 0
    assert any(abs(float(weight)) > 0.0 for weight in updated_state["weights"].values())
    assert updated_state["last_train_event_id"] == "ml-evt-1"
