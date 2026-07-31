from api.services.minute_region_signal_stats import (
    build_accuracy_pipeline,
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


def test_accuracy_pipeline_filters_coverage_and_completed_horizon():
    pipeline = build_accuracy_pipeline(
        {"roulette_id": "pragmatic-auto-roulette", "coverage": 8},
        attempt_horizon=7,
        include_alternative=True,
    )

    assert pipeline[0]["$match"]["coverage"] == 8
    assert pipeline[0]["$match"]["attempt_count"] == {"$gte": 7}
    hit_expression = pipeline[1]["$project"]["hit"]
    assert "$gt" in hit_expression
    filtered_hit = hit_expression["$gt"][0]["$size"]["$filter"]["cond"]
    assert "$or" in filtered_hit
