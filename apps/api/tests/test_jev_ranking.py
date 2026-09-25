from __future__ import annotations

import pytest

from api.services.jev_ranking import (
    HISTORY_TAIL_LIMIT,
    NUMBER_KEYS,
    ROULETTE_NUMBERS,
    SINGLE_NUMBER_BASELINE,
    build_ranking_payload,
    calculate_pull_relations,
    number_key,
)


def _strong_zero_pull_history(repetitions: int = 40) -> list[int]:
    return [value for _ in range(repetitions) for value in (17, 0, 1, 2)] + [17]


def test_pull_relation_uses_only_complete_future_windows_and_includes_zero() -> None:
    history = _strong_zero_pull_history()
    catalog = calculate_pull_relations(history)
    relations = {item["target_number"]: item for item in catalog["relations"]}

    assert catalog["source_number"] == 17
    assert set(relations) == set(ROULETTE_NUMBERS)
    assert relations[0]["support"] == 40
    assert relations[0]["hits"] == 40
    assert relations[0]["raw_rate"] == 1
    assert relations[0]["fair_baseline"] == pytest.approx(SINGLE_NUMBER_BASELINE)
    assert relations[0]["classification"] in {"stable_positive_pull", "positive_pull"}
    assert any(candidate["target_number"] == 0 for candidate in catalog["candidates"])


def test_ranking_payload_has_37_number_questions_and_structured_candidates() -> None:
    payload = build_ranking_payload(_strong_zero_pull_history())
    state = payload["state"]
    questions = payload["questions"]

    assert list(questions)[:37] == list(NUMBER_KEYS)
    assert all(questions[key]["type"] == "noul" for key in questions)
    assert questions["numero_00"]["instructions"]["target_number"] == 0
    assert len(state["number_profiles"]) == 37
    zero = state["number_profiles"][0]
    assert zero["number"] == 0
    assert zero["attributes"] == {
        "color": "green",
        "parity": None,
        "dozen": None,
        "column": None,
    }
    assert state["task"]["include_zero"] is True
    assert state["task"]["universe"] == list(range(37))
    assert any(key.startswith("relacao_17_00") for key in questions)


def test_ranking_state_caps_raw_tail_but_keeps_full_aggregates_and_digest() -> None:
    history = [number % 37 for number in range(HISTORY_TAIL_LIMIT + 75)]
    payload = build_ranking_payload(history)
    context = payload["state"]["history_context"]

    assert context["observed_spins"] == len(history)
    assert context["recent_history"] == history[-HISTORY_TAIL_LIMIT:]
    assert context["raw_history_scope"] == f"last_{HISTORY_TAIL_LIMIT}_of_{len(history)}"
    assert len(context["full_history_sha256"]) == 64
    assert payload["state"]["number_profiles"][0]["frequency"]["all"]["spins"] == len(history)


def test_number_keys_are_stable_and_cover_zero_through_thirty_six() -> None:
    assert number_key(0) == "numero_00"
    assert number_key(36) == "numero_36"
    assert len(NUMBER_KEYS) == 37
    assert len(set(NUMBER_KEYS)) == 37
