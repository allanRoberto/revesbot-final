from api.services.minute_region_signal_stats import (
    build_accuracy_pipeline,
    build_attempt_accuracy_rows,
    build_coverage_stages,
    build_hit_count_rows,
    build_signal_list_pipeline,
    effective_coverage,
    evaluate_signal,
)


def _signal(*attempts):
    return {
        "attempt_count": len(attempts),
        "attempts": [
            {
                "attempt_number": index,
                "is_payment": official,
                "is_alternative_payment": alternative,
            }
            for index, (official, alternative) in enumerate(attempts, 1)
        ],
    }


def test_signal_needs_full_horizon_before_becoming_a_miss():
    evaluation = evaluate_signal(
        _signal(*[(False, False)] * 6),
        attempt_horizon=7,
        include_alternative=False,
    )

    assert evaluation["eligible"] is False
    assert evaluation["outcome"] == "pending"
    assert evaluation["hit"] is None


def test_official_hit_is_measured_only_inside_selected_horizon():
    attempts = [(False, False)] * 6 + [(True, False)] + [(False, False)] * 3
    at_six = evaluate_signal(
        _signal(*attempts),
        attempt_horizon=6,
        include_alternative=False,
    )
    at_seven = evaluate_signal(
        _signal(*attempts),
        attempt_horizon=7,
        include_alternative=False,
    )

    assert at_six["outcome"] == "miss"
    assert at_seven["outcome"] == "hit"
    assert at_seven["first_hit_attempt"] == 7


def test_alternative_hit_is_optional_and_does_not_become_official():
    signal = _signal((False, False), (False, True), (False, False))

    official_only = evaluate_signal(
        signal,
        attempt_horizon=3,
        include_alternative=False,
    )
    with_alternative = evaluate_signal(
        signal,
        attempt_horizon=3,
        include_alternative=True,
    )

    assert official_only["outcome"] == "miss"
    assert official_only["official_hit"] is False
    assert with_alternative["outcome"] == "hit"
    assert with_alternative["official_hit"] is False
    assert with_alternative["alternative_hit"] is True
    assert with_alternative["first_hit_attempt"] == 2


def test_hit_count_counts_each_attempt_only_once_with_alternative():
    evaluation = evaluate_signal(
        _signal((True, True), (False, True), (False, False)),
        attempt_horizon=3,
        include_alternative=True,
    )

    assert evaluation["hit_count"] == 2


def test_accuracy_pipeline_filters_coverage_and_completed_horizon():
    pipeline = build_accuracy_pipeline(
        {"roulette_id": "pragmatic-auto-roulette"},
        attempt_horizon=7,
        include_alternative=True,
        coverage=8,
        coverage_mode="exact",
    )

    assert pipeline[0]["$match"]["attempt_count"] == {"$gte": 7}
    assert pipeline[2]["$match"]["effective_coverage"] == 8
    hit_expression = pipeline[3]["$project"]["hit"]
    assert "$gt" in hit_expression
    filtered_hit = hit_expression["$gt"][0]["$size"]["$filter"]["cond"]
    assert "$or" in filtered_hit
    group = pipeline[4]["$group"]
    assert "attempt_1_hits" in group
    assert "attempt_7_hits" in group
    assert "attempt_8_hits" not in group


def test_effective_coverage_unites_official_and_alternative_without_duplicates():
    signal = {
        "coverage": 3,
        "bet_values": [1, 2, 3],
        "alternative_analysis": {"alternative_bet_values": [3, 4, 5]},
    }

    assert effective_coverage(signal, include_alternative=False) == 3
    assert effective_coverage(signal, include_alternative=True) == 5


def test_coverage_modes_support_up_to_and_exact():
    up_to = build_coverage_stages(
        include_alternative=False,
        coverage=8,
        coverage_mode="up_to",
    )
    exact = build_coverage_stages(
        include_alternative=False,
        coverage=8,
        coverage_mode="exact",
    )

    assert up_to[1] == {"$match": {"effective_coverage": {"$lte": 8}}}
    assert exact[1] == {"$match": {"effective_coverage": 8}}


def test_list_pipeline_does_not_hide_recent_signals_by_attempt_count():
    pipeline = build_signal_list_pipeline(
        {"roulette_id": "pragmatic-auto-roulette"},
        include_alternative=True,
        coverage=None,
        coverage_mode="up_to",
        attempt_horizon=7,
        hit_count=None,
        limit=200,
    )

    assert pipeline[0] == {"$match": {"roulette_id": "pragmatic-auto-roulette"}}
    assert "attempt_count" not in str(pipeline)
    assert pipeline[-1]["$facet"]["items"][-1] == {"$limit": 200}


def test_list_pipeline_filters_an_exact_hit_count_only_after_full_horizon():
    pipeline = build_signal_list_pipeline(
        {"roulette_id": "pragmatic-auto-roulette"},
        include_alternative=True,
        coverage=None,
        coverage_mode="up_to",
        attempt_horizon=7,
        hit_count=2,
        limit=200,
    )

    assert pipeline[-2] == {
        "$match": {
            "attempt_count": {"$gte": 7},
            "evaluated_hit_count": 2,
        }
    }


def test_attempt_accuracy_rows_show_exact_and_cumulative_percentages():
    rows = build_attempt_accuracy_rows(
        {
            "evaluated": 10,
            "attempt_1_hits": 3,
            "attempt_2_hits": 2,
            "attempt_3_hits": 1,
        },
        attempt_horizon=3,
    )

    assert rows == [
        {
            "attempt": 1,
            "hits": 3,
            "accuracy": 30.0,
            "cumulative_hits": 3,
            "cumulative_accuracy": 30.0,
        },
        {
            "attempt": 2,
            "hits": 2,
            "accuracy": 20.0,
            "cumulative_hits": 5,
            "cumulative_accuracy": 50.0,
        },
        {
            "attempt": 3,
            "hits": 1,
            "accuracy": 10.0,
            "cumulative_hits": 6,
            "cumulative_accuracy": 60.0,
        },
    ]


def test_hit_count_rows_show_exact_and_at_least_percentages():
    rows = build_hit_count_rows(
        {
            "evaluated": 10,
            "hit_count_0_signals": 2,
            "hit_count_1_signals": 5,
            "hit_count_2_signals": 3,
        },
        attempt_horizon=2,
    )

    assert rows == [
        {
            "hit_count": 0,
            "signals": 2,
            "percentage": 20.0,
            "at_least_signals": 10,
            "at_least_percentage": 100.0,
        },
        {
            "hit_count": 1,
            "signals": 5,
            "percentage": 50.0,
            "at_least_signals": 8,
            "at_least_percentage": 80.0,
        },
        {
            "hit_count": 2,
            "signals": 3,
            "percentage": 30.0,
            "at_least_signals": 3,
            "at_least_percentage": 30.0,
        },
    ]
