from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from api.routes import next_number_rankings
from api.services.next_number_intersection_service import (
    build_next_number_intersection_payload,
    extract_followups,
    rank_neighbor_intersections,
)


GROUPS = {
    19: [20, 18, 18, 4, 13, 28, 5, 25, 14, 21, 13, 2, 15, 14, 23],
    16: [19, 28, 7, 16, 29, 5, 21, 22, 15, 17, 8, 23, 18, 20, 30],
    34: [16, 14, 8, 10, 1, 10, 19, 4, 19, 7, 36, 32, 15, 9, 29],
}


def _relation(ranking, values):
    return next(item for item in ranking if item["values"] == list(values))


def test_extract_followups_uses_the_next_chronological_spin() -> None:
    history_desc = [
        19,  # ocorrencia atual, ainda sem sucessor
        6,
        19,
        5,
        19,
        4,
        16,
        3,
        34,
        2,
        19,
    ]

    groups = extract_followups(history_desc, [19, 16, 34], occurrence_limit=2)

    assert groups[19] == [6, 5]
    assert groups[16] == [4]
    assert groups[34] == [3]


def test_neighbor_ranking_matches_exact_strong_and_weak_examples() -> None:
    ranking = rank_neighbor_intersections(GROUPS, [19, 16, 34])

    assert ranking[0]["values"] == [15, 15, 15]
    assert ranking[0]["strength"] == "exact"
    assert ranking[0]["neighbor_count"] == 0

    strong = _relation(ranking, [23, 23, 10])
    assert strong["center_number"] == 23
    assert strong["wheel_neighbors"] == [8, 10]
    assert strong["neighbor_count"] == 1
    assert strong["strength"] == "one_neighbor"

    weak = _relation(ranking, [23, 8, 10])
    assert weak["center_number"] == 23
    assert weak["neighbor_count"] == 2
    assert weak["strength"] == "two_neighbors"
    assert strong["position"] < weak["position"]


def test_payload_reports_incomplete_groups_without_fabricating_values() -> None:
    payload = build_next_number_intersection_payload(
        roulette_id="pragmatic-auto-roulette",
        history_desc=[6, 19, 5, 16, 4, 34],
        base_numbers=[19, 16, 34],
        occurrence_limit=2,
    )

    assert payload["complete"] is False
    assert payload["groups"][0]["pulled_numbers"] == [6]
    assert payload["groups"][0]["collected_occurrences"] == 1
    assert payload["warnings"]


def test_request_requires_three_distinct_strict_roulette_numbers() -> None:
    payload = next_number_rankings.NextNumberIntersectionRequest(
        base_numbers=[19, 16, 34],
        occurrences=15,
    )
    assert payload.base_numbers == [19, 16, 34]
    assert payload.occurrences == 15

    with pytest.raises(ValidationError):
        next_number_rankings.NextNumberIntersectionRequest(
            base_numbers=[19, 19, 34],
        )
    with pytest.raises(ValidationError):
        next_number_rankings.NextNumberIntersectionRequest(
            base_numbers=[19, 16],
        )
    with pytest.raises(ValidationError):
        next_number_rankings.NextNumberIntersectionRequest(
            base_numbers=["19", 16, 34],
        )
    with pytest.raises(ValidationError):
        next_number_rankings.NextNumberIntersectionRequest(
            base_numbers=[19, 16, 34],
            occurrences="15",
        )


def test_route_forwards_selected_numbers_and_occurrence_limit(monkeypatch) -> None:
    captured = {}

    async def fake_intersection(**kwargs):
        captured.update(kwargs)
        return {"ranking": []}

    monkeypatch.setattr(
        next_number_rankings,
        "get_next_number_intersection",
        fake_intersection,
    )
    request = next_number_rankings.NextNumberIntersectionRequest(
        base_numbers=[19, 16, 34],
        occurrences=15,
    )

    result = asyncio.run(
        next_number_rankings.post_next_number_intersection_route(
            "pragmatic-auto-roulette",
            request,
        )
    )

    assert result == {"ranking": []}
    assert captured == {
        "roulette_id": "pragmatic-auto-roulette",
        "base_numbers": [19, 16, 34],
        "occurrence_limit": 15,
    }


def test_page_exposes_three_number_intersection_controls() -> None:
    template = (
        Path(__file__).resolve().parents[1]
        / "templates"
        / "next_number_rankings.html"
    ).read_text(encoding="utf-8")

    assert 'id="intersectionNumberA"' in template
    assert 'id="intersectionNumberB"' in template
    assert 'id="intersectionNumberC"' in template
    assert 'id="intersectionRouletteSelect"' in template
    assert 'id="intersectionLoadLatestButton"' in template
    assert 'id="intersectionOccurrences"' in template
    assert 'id="intersectionRankingBody"' in template
    assert 'fetch("/api/roulettes-list"' in template
    assert "/api/next-number-rankings/${encodeURIComponent(selectedRouletteId)}/intersection" in template
    assert "/history/${encodeURIComponent(selectedRouletteId)}?limit=20" in template
    assert 'intersectionLoadLatestButton.addEventListener("click", loadLatestIntersectionNumbers)' in template
    assert 'intersectionRouletteSelect.addEventListener("change", () =>' in template
