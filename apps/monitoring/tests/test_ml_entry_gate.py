from __future__ import annotations

from src.ml_entry_gate import (
    build_default_ml_entry_gate_state,
    build_ml_entry_gate_payload_from_ml_meta,
    build_ml_top12_reference_payload_from_ml_meta,
    train_ml_entry_gate_state_from_reference_event,
)


def _ml_meta_payload() -> dict:
    candidate_features = []
    selected_details = []
    ordered = list(range(37))
    for index in range(37):
        selected_details.append(
            {
                "number": index,
                "support_score": max(1, 40 - index),
                "weighted_support_score": round(11.0 - (index * 0.2), 6),
            }
        )
        candidate_features.append(
            {
                "number": index,
                "heuristic_score": round(0.95 - (index * 0.01), 6),
                "model_probability": round(0.82 - (index * 0.01), 6),
                "final_score": round(0.9 - (index * 0.012), 6),
                "features": {
                    "time_region_prior": round(0.7 - (index * 0.008), 6),
                    "history_region_density": round(0.66 - (index * 0.007), 6),
                    "top26_rank_score": round(0.88 - (index * 0.01), 6),
                    "base_dynamic_weight_avg_norm": round(0.8 - (index * 0.009), 6),
                    "base_positive_pattern_share": round(0.72 - (index * 0.006), 6),
                    "base_negative_pattern_share": round(0.2 + (index * 0.002), 6),
                    "base_rank_score": round(0.9 - (index * 0.011), 6),
                },
            }
        )

    return {
        "available": True,
        "list": ordered,
        "suggestion": ordered,
        "ordered_suggestion": ordered,
        "selected_number_details": selected_details,
        "entry_shadow": {
            "entry_confidence": {"score": 78, "base_score_before_rank_feedback": 83},
            "rank_context_confidence": {
                "confidence_delta": 4,
                "latest_rank_band": "bottom",
                "avg_rank_ratio": 0.71,
                "zigzag_rate": 0.41,
                "worsening_strength": 0.18,
                "improvement_strength": 0.64,
                "top_band_share": 0.16,
                "lower_band_share": 0.52,
            },
        },
        "oscillation": {
            "profile": "ml_meta_rank_v1",
            "ml_meta_rank": {
                "candidate_features": candidate_features,
            },
        },
    }


def test_build_ml_top12_reference_payload_uses_12_numbers_and_4_attempts() -> None:
    payload = build_ml_top12_reference_payload_from_ml_meta(_ml_meta_payload())

    assert payload is not None
    assert payload["available"] is True
    assert payload["evaluation_window_attempts"] == 4
    assert len(payload["suggestion"]) == 12
    assert payload["oscillation"]["profile"] == "ml_top12_reference_12x4_v1"
    assert payload["oscillation"]["ml_entry_gate"]["mode"] == "reference"


def test_build_default_ml_entry_gate_state_uses_runtime_defaults() -> None:
    state = build_default_ml_entry_gate_state(
        roulette_id="pragmatic-auto-roulette",
        config_key="cfg-gate",
    )

    assert state["warmup_events"] == 12
    assert state["threshold"] == 0.52


def test_build_ml_entry_gate_payload_enters_after_warmup_with_positive_bias() -> None:
    state = build_default_ml_entry_gate_state(
        roulette_id="pragmatic-auto-roulette",
        config_key="cfg-gate",
    )
    state["bias"] = 1.2
    state["trained_events"] = 12
    state["warmup_events"] = 10
    state["threshold"] = 0.55

    payload = build_ml_entry_gate_payload_from_ml_meta(
        _ml_meta_payload(),
        state,
        roulette_id="pragmatic-auto-roulette",
        config_key="cfg-gate",
    )

    assert payload is not None
    assert payload["available"] is True
    assert len(payload["suggestion"]) == 12
    assert payload["evaluation_window_attempts"] == 4
    assert payload["oscillation"]["profile"] == "ml_entry_gate_12x4_v1"
    assert payload["oscillation"]["ml_entry_gate"]["should_enter"] is True


def test_build_ml_entry_gate_payload_reports_warmup_reason_before_unlock() -> None:
    state = build_default_ml_entry_gate_state(
        roulette_id="pragmatic-auto-roulette",
        config_key="cfg-gate",
    )
    state["bias"] = 1.2
    state["trained_events"] = 4

    payload = build_ml_entry_gate_payload_from_ml_meta(
        _ml_meta_payload(),
        state,
        roulette_id="pragmatic-auto-roulette",
        config_key="cfg-gate",
    )

    assert payload is not None
    assert payload["available"] is False
    assert payload["entry_shadow"]["recommendation"]["action"] == "wait"
    assert "aquecimento" in payload["entry_shadow"]["recommendation"]["reason"].lower()
    assert payload["oscillation"]["ml_entry_gate"]["warmup_required"] == 6


def test_train_ml_entry_gate_state_from_reference_event_updates_model() -> None:
    state = build_default_ml_entry_gate_state(
        roulette_id="pragmatic-auto-roulette",
        config_key="cfg-gate",
    )
    reference_payload = build_ml_top12_reference_payload_from_ml_meta(_ml_meta_payload())
    assert reference_payload is not None

    updated_state = train_ml_entry_gate_state_from_reference_event(
        state,
        {
            "_id": "ref-gate-1",
            "window_result_hit": True,
            "oscillation": reference_payload["oscillation"],
        },
        roulette_id="pragmatic-auto-roulette",
        config_key="cfg-gate",
    )

    assert updated_state["trained_events"] == 1
    assert updated_state["trained_rows"] > 0
    assert updated_state["last_train_event_id"] == "ref-gate-1"
    assert updated_state["last_label"] is True
    assert any(abs(float(weight)) > 0.0 for weight in updated_state["weights"].values())
