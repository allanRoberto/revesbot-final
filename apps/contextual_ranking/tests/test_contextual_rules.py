from __future__ import annotations

from contextual_ranking.rules import (
    analyze_occurrences, compare_distribution, match_counts, neighbors_of, rank_columns, rank_following,
    score_context, sort_occurrences,
)
from contextual_ranking.tests.fixtures import (
    PRODUCTION_CURRENT_CONTEXT, PRODUCTION_ROWS, PRODUCTION_SEQUENCE, production_occurrences,
)


def test_wheel_neighbors_wrap_around_zero():
    assert neighbors_of(0) == (26, 32)
    assert neighbors_of(5) == (10, 24)
    assert neighbors_of(26) == (3, 0)
    assert neighbors_of(37) == ()
    assert neighbors_of(True) == ()


def test_context_score_uses_each_historical_number_once():
    result = score_context([15, 15, 1, 2, 3], [15, 4, 5, 6, 7])
    assert (result["score"], result["exact"], result["neighbor"]) == (10, 1, 0)
    result = score_context([1, 16, 0, 15, 34], [15, 17, 24, 15, 9])
    assert (result["score"], result["exact"], result["neighbor"], result["similarity"]) == (26, 1, 2, 52)


def test_invalid_preceding_has_no_score_and_is_not_approved():
    rows = analyze_occurrences([1, 2, 3, 4, 5], [
        {"id": "a", "preceding": [1, 2, 3, 4, 5], "preceding_complete": False,
         "context": [1, 2, 3, 4], "following": [1, 2, 3, 4, 5]},
    ])
    assert rows[0]["score"] is None
    assert rows[0]["approved"] is False
    assert rows[0]["preceding_lookup_status"] == "unavailable"


def test_distribution_prefers_more_columns_then_larger_counts():
    assert compare_distribution([1, 1, 0], [2, 0, 0]) < 0
    assert compare_distribution([1, 0, 0], [3, 0, 0]) > 0
    assert compare_distribution([0, 2], [2, 0]) == 0


def test_sequence_match_counts_ignore_order():
    assert match_counts([23, 12, 32, 7], [7, 32, 12, 23]) == {"exact": 4, "neighbor": 0}
    assert match_counts([23, 12, 32, 7], [23, 35, 32, 7]) == {"exact": 3, "neighbor": 1}
    assert match_counts([23, 12, 32, 7], None) == {"exact": 0, "neighbor": 0}


def test_production_table_order_and_scores_are_reproduced():
    rows = analyze_occurrences(PRODUCTION_CURRENT_CONTEXT, production_occurrences())
    ordered = sort_occurrences(rows, PRODUCTION_SEQUENCE)
    assert [row["index"] for row in ordered] == list(range(len(PRODUCTION_ROWS)))
    for row, (_, _, _, (exact, neighbor, similarity)) in zip(rows, PRODUCTION_ROWS, strict=True):
        assert (row["score"]["exact"], row["score"]["neighbor"]) == (exact, neighbor)
        assert round(row["score"]["similarity"]) == similarity


def test_live_hits_in_posterior_move_rows_up():
    rows = analyze_occurrences(PRODUCTION_CURRENT_CONTEXT, production_occurrences())
    # 27 and 8 came out after the search. Rows that now have exact matches in
    # the three columns pass the first row (exact only in two columns); among
    # equal rows, the one without a repeated number in the sequence wins.
    ordered = sort_occurrences(rows, PRODUCTION_SEQUENCE, live_numbers=[27, 8])
    assert [row["id"] for row in ordered[:4]] == ["prod-2", "prod-3", "prod-4", "prod-6"]


def test_ranking_distributes_ten_to_self_and_eight_to_each_neighbor():
    ranked = rank_following([{"id": "a", "following": [5, 5, 0, 1, 2]}])
    by_number = {row["number"]: row for row in ranked["ranking"]}
    assert ranked["maximum"] == 50
    assert (by_number[5]["score"], by_number[5]["exact"]) == (20, 2)
    assert (by_number[10]["score"], by_number[10]["neighbor"]) == (16, 2)
    assert by_number[17]["score"] == 0
    assert len(ranked["ranking"]) == 37


def test_ranking_ignores_invalid_posterior_arrays():
    ranked = rank_following([{"id": "a", "following": [5, 5, 0, 1]}])
    assert ranked["analyzed_results"] == 0
    assert all(row["percentage"] == 0 for row in ranked["ranking"])


def test_worker_ranking_counts_every_number_of_the_three_columns():
    [row] = analyze_occurrences([1, 2, 3, 4, 5], [{
        "id": "a", "preceding": [5, 5, 9, 9, 9], "preceding_complete": True,
        "context": [9, 0, 0, 0], "following": [5, 10, 10, 10, 10],
    }])
    ranked = rank_columns([row])
    by_number = {item["number"]: item for item in ranked["ranking"]}
    assert ranked["analyzed_results"] == 14
    assert ranked["maximum"] == 140
    # 5: twice in Anterior and once in Posterior; 9: three times in Anterior and once in Sequência.
    assert (by_number[5]["exact"], by_number[9]["exact"], by_number[0]["exact"]) == (3, 4, 3)
    assert by_number[10]["exact"] == 4 and by_number[10]["neighbor"] == 3
    # Same scoring as the page: equal to rank_following when only Posterior is valid.
    only_following = {**row, "preceding_valid": False, "context_valid": False}
    assert rank_columns([only_following]) == rank_following([only_following])


def test_worker_ranking_skips_invalid_columns():
    [row] = analyze_occurrences([1, 2, 3, 4, 5], [{
        "id": "a", "preceding": [5, 5, 9, 9, 9], "preceding_complete": False,
        "context": [9, 0, 0, 0], "following": [5, 10, 10, 10],
    }])
    assert rank_columns([row])["analyzed_results"] == 4
