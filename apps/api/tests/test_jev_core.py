from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from api.schemas.jev import (
    GROUP_KEYS,
    JevAnalysisRequest,
    JevInputError,
    JevRankingRequest,
    parse_roulette_text,
)
from api.services.jev_statistics import (
    build_jev_questions,
    build_jev_state,
    calculate_all_group_statistics,
    calculate_group_statistics,
)


def _groups() -> dict[str, list[int]]:
    return {
        "grupo_1": [1, 2, 3, 4, 5, 6],
        "grupo_2": [7, 8, 9, 10, 11, 12],
        "grupo_3": [13, 14, 15, 16, 17, 18],
        "grupo_4": [19, 20, 21, 22, 23, 24],
        "grupo_5": [25, 26, 27, 28, 29, 30],
        "grupo_6": [31, 32, 33, 34, 35, 36],
    }


def test_parser_accepts_only_documented_separators_and_preserves_order_and_repetitions() -> None:
    assert parse_roulette_text("1, 7;0\t2\n8  3") == [1, 7, 0, 2, 8, 3]
    assert parse_roulette_text("7, 7, 7") == [7, 7, 7]
    assert parse_roulette_text(" , ; \n\t ") == []


@pytest.mark.parametrize(
    "value",
    ["-1", "+1", "1.0", "1.5", "1e1", "true", "1|2", "um", "١", "9" * 5000],
)
def test_parser_rejects_non_ascii_or_non_integer_tokens(value: str) -> None:
    with pytest.raises(JevInputError):
        parse_roulette_text(value)


@pytest.mark.parametrize("value", ["37", "999999999999999999999999999999999"])
def test_parser_rejects_values_outside_roulette(value: str) -> None:
    with pytest.raises(JevInputError):
        parse_roulette_text(value)


def test_groups_require_exact_ids_nonempty_unique_strict_integers() -> None:
    payload = JevAnalysisRequest.model_validate(
        {"history_order": "oldest_to_newest", "historico_texto": "0", "grupos": _groups()}
    )
    assert payload.grupos["grupo_1"] == [1, 2, 3, 4, 5, 6]

    invalid_payloads = []
    missing = _groups()
    missing.pop("grupo_6")
    invalid_payloads.append(missing)
    extra = _groups()
    extra["grupo_7"] = [0]
    invalid_payloads.append(extra)
    empty = _groups()
    empty["grupo_1"] = []
    invalid_payloads.append(empty)
    duplicate = _groups()
    duplicate["grupo_1"] = [1, 1]
    invalid_payloads.append(duplicate)
    boolean = _groups()
    boolean["grupo_1"] = [True]
    invalid_payloads.append(boolean)
    floating = _groups()
    floating["grupo_1"] = [1.0]
    invalid_payloads.append(floating)
    string = _groups()
    string["grupo_1"] = ["1"]
    invalid_payloads.append(string)

    for groups in invalid_payloads:
        with pytest.raises(ValidationError):
            JevAnalysisRequest.model_validate(
                {"history_order": "oldest_to_newest", "historico_texto": "0", "grupos": groups}
            )


def test_zero_and_overlap_between_groups_are_allowed() -> None:
    groups = _groups()
    groups["grupo_1"] = [0, 1]
    groups["grupo_2"] = [0, 2]
    payload = JevAnalysisRequest.model_validate(
        {"history_order": "oldest_to_newest", "historico_texto": "0", "grupos": groups}
    )
    assert payload.grupos["grupo_1"] == [0, 1]
    assert payload.grupos["grupo_2"] == [0, 2]


def test_ranking_request_accepts_only_history_contract() -> None:
    payload = JevRankingRequest.model_validate(
        {"history_order": "oldest_to_newest", "historico_texto": "17, 0"}
    )
    assert payload.historico_texto == "17, 0"
    with pytest.raises(ValidationError):
        JevRankingRequest.model_validate(
            {"history_order": "newest_to_oldest", "historico_texto": "17, 0"}
        )
    with pytest.raises(ValidationError):
        JevRankingRequest.model_validate(
            {
                "history_order": "oldest_to_newest",
                "historico_texto": "17, 0",
                "horizon": 1,
            }
        )


def test_deterministic_statistics_match_the_specification() -> None:
    history = [1, 7, 0, 2, 8, 3]
    stats = calculate_all_group_statistics(history, _groups())
    assert stats["grupo_1"]["hits_in_recent_window"] == 3
    assert stats["grupo_1"]["spins_since_last_hit"] == 0
    assert stats["grupo_2"]["hits_in_recent_window"] == 2
    assert stats["grupo_2"]["spins_since_last_hit"] == 1
    assert stats["grupo_3"]["hits_in_recent_window"] == 0
    assert stats["grupo_3"]["spins_since_last_hit"] is None
    assert stats["grupo_1"]["recent_window_size"] == 6
    assert stats["grupo_1"]["fair_independent_baseline"] == pytest.approx(
        0.41186109411091154
    )


def test_statistics_cover_group_sizes_one_six_and_thirty_seven_and_window_30() -> None:
    history = list(range(37))
    for size in (1, 6, 37):
        stats = calculate_group_statistics(history, list(range(size)))
        assert stats["size"] == size
        assert stats["recent_window_size"] == 30
        assert stats["fair_independent_baseline"] == pytest.approx(
            1 - (1 - size / 37) ** 3
        )
        assert math.isfinite(stats["fair_independent_baseline"])
    assert calculate_group_statistics([1, 2, 3], [3])["spins_since_last_hit"] == 0
    assert calculate_group_statistics([1, 2, 3], [2])["spins_since_last_hit"] == 1
    assert calculate_group_statistics([1, 2, 3], [4])["spins_since_last_hit"] is None


def test_state_and_questions_keep_six_independent_nouls() -> None:
    history = [1, 7, 0, 2, 8, 3]
    groups = _groups()
    stats = calculate_all_group_statistics(history, groups)
    state = build_jev_state(history, stats)
    questions = build_jev_questions(groups)

    assert list(questions) == list(GROUP_KEYS)
    assert len(questions) == 6
    assert all(question["type"] == "noul" for question in questions.values())
    assert questions["grupo_1"]["instructions"]["target_numbers"] == groups["grupo_1"]
    assert "next three spins" in questions["grupo_1"]["instructions"]["question"]
    assert state["history"] == history
    assert state["history_order"] == "oldest_to_newest"
    assert state["latest_observed_number"] == 3
    assert state["forecast_horizon_spins"] == 3
