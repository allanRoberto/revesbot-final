from __future__ import annotations

import random

import pytest

from contextual_pairs.quality import (
    HIGH_QUALITY, LOOKBACK, NEAR_DISTANCE, QUALITY_RULE, TAGS, WATCH_NEAR, entry_context, last_exact_distance,
    quality_tags,
)

# Real signals of 16 and 17/11/2026: the bet and the 13 results up to the trigger, oldest first.
HIGH_REAL = ([4, 5, 9, 14, 15, 19, 31, 32], [11, 18, 26, 0, 11, 32, 30, 31, 7, 5, 9, 36, 33])  # pair 5-9, 8 numbers
WATCH_REAL = ([0, 3, 7, 8, 10, 11, 12, 23, 26, 28, 30, 35], [34, 9, 25, 4, 27, 30, 30, 29, 0, 3, 8, 10, 11])  # 3-8, 12
SMALL_NEAR_REAL = ([2, 7, 12, 17, 18, 21, 25, 28, 29], [33, 21, 27, 19, 3, 22, 34, 23, 2, 35, 16, 28, 2])  # 2-7, 9
MEDIUM_FAR_REAL = ([0, 3, 7, 8, 10, 11, 12, 23, 26, 28, 30, 35], [4, 27, 30, 30, 29, 0, 3, 8, 10, 11, 3, 2, 20])  # 3-8


def test_the_tags_are_the_two_monitored_conditions():
    assert TAGS == (HIGH_QUALITY, WATCH_NEAR) == ("high_quality", "watch_12_15_exact_near")
    assert (LOOKBACK, NEAR_DISTANCE, QUALITY_RULE) == (10, 2, 1)


def test_the_distance_counts_back_from_the_latest_result():
    bet = [1, 2, 3]
    assert last_exact_distance(bet, [9, 9, 9, 9, 9, 9, 9, 9, 9, 3]) == 1
    assert last_exact_distance(bet, [9, 9, 9, 9, 9, 9, 9, 9, 3, 9]) == 2
    assert last_exact_distance(bet, [3, 9, 9, 9, 9, 9, 9, 9, 9, 9]) == 10
    assert last_exact_distance(bet, [9] * 10) is None
    # Only the last 10 results count, and the closest number of the bet wins.
    assert last_exact_distance(bet, [1] + [9] * 10) is None
    assert last_exact_distance(bet, [2, 9, 9, 3, 9, 1, 9, 9, 9, 9, 9, 9]) == 7


def test_the_entry_context_needs_ten_results_and_records_the_size_and_the_distance():
    assert entry_context([1, 2], [5] * (LOOKBACK - 1)) is None
    assert entry_context([1, 2], []) is None
    assert entry_context([1, 2], [5] * LOOKBACK) == {"rule": QUALITY_RULE, "chips": 2, "last_exact_distance": None}
    assert entry_context([1, 2, 3], [1] + [5] * 12) == {"rule": QUALITY_RULE, "chips": 3, "last_exact_distance": None}
    assert entry_context([1, 2, 3], [5] * 12 + [3]) == {"rule": QUALITY_RULE, "chips": 3, "last_exact_distance": 1}


@pytest.mark.parametrize("chips, distance, expected", [
    (8, None, [HIGH_QUALITY]), (8, 3, [HIGH_QUALITY]), (10, 5, [HIGH_QUALITY]), (11, 10, [HIGH_QUALITY]),
    (8, 1, []), (9, 2, []), (11, 1, []),
    (12, 1, [WATCH_NEAR]), (13, 2, [WATCH_NEAR]), (15, 1, [WATCH_NEAR]),
    (12, 3, []), (14, 10, []), (15, None, []),
    (7, None, []), (7, 1, []), (16, 1, []), (16, None, []), (22, 2, []), (22, 7, []),
])
def test_the_tags_follow_the_size_of_the_bet_and_the_distance(chips, distance, expected):
    context = {"rule": QUALITY_RULE, "chips": chips, "last_exact_distance": distance}
    assert quality_tags(context) == expected


def test_a_signal_without_context_is_not_tagged():
    assert quality_tags(None) == []
    assert quality_tags({}) == []


@pytest.mark.parametrize("real, distance, tags", [
    (HIGH_REAL, 3, [HIGH_QUALITY]),  # 33 and 36 are outside the bet, the 9 came 3 results back
    (WATCH_REAL, 1, [WATCH_NEAR]),  # the trigger (11) is in the bet
    (SMALL_NEAR_REAL, 1, []),  # small bet, but the trigger (2) is in it
    (MEDIUM_FAR_REAL, 3, []),  # medium bet, the last number of the bet (3) came 3 results back: far
])
def test_real_signals_get_the_tags_the_analysis_found(real, distance, tags):
    bet, chain = real
    context = entry_context(bet, chain)
    assert context["last_exact_distance"] == distance and context["chips"] == len(bet)
    assert quality_tags(context) == tags


def test_the_tags_only_look_at_the_two_latest_results_and_never_overlap():
    rng = random.Random(7)
    seen = set()
    for _ in range(2000):
        bet = rng.sample(range(37), rng.randint(8, 22))
        numbers = [rng.randrange(37) for _ in range(rng.randint(LOOKBACK, 13))]
        near = numbers[-1] in bet or numbers[-2] in bet  # the rule, said another way
        expected = []
        if 8 <= len(bet) <= 11 and not near:
            expected.append("high_quality")
        if 12 <= len(bet) <= 15 and near:
            expected.append("watch_12_15_exact_near")
        tags = quality_tags(entry_context(bet, numbers))
        assert tags == expected and len(tags) <= 1
        seen.update(tags)
    assert seen == set(TAGS)
