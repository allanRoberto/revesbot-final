from __future__ import annotations

from itertools import combinations

from contextual_pairs import rules
from contextual_pairs.rules import digital_root, group, kept_numbers, pair_bet, wheel_arcs
from contextual_ranking.rules import WHEEL, neighbors_of


def test_groups_hold_terminals_mirror_and_digit_sum():
    assert group(0) == [0, 10, 20, 30]
    assert group(3) == [3, 13, 23, 33, 30, 12, 21]
    assert group(7) == [7, 17, 27, 16, 25, 34]
    assert group(6) == [6, 16, 26, 36, 9, 15, 24, 33]
    assert group(9) == [9, 19, 29, 6, 18, 27, 36]


def test_digital_root_reduces_to_one_digit():
    assert [digital_root(number) for number in (7, 16, 19, 28, 29, 36)] == [7, 7, 1, 1, 2, 9]


def test_user_example_three_and_seven():
    # 13 is a neighbor of 27, 33 of 16, 27 of 13 and 16 of 33; 3, 23, 30, 12, 21, 7, 17, 25, 34 are not.
    assert sorted(kept_numbers(3, 7)) == [13, 16, 27, 33]
    info = pair_bet([3, 7, 36, 35, 34, 33, 32])
    assert (info["kind"], info["pair"]) == ("ok", [3, 7])
    assert info["kept"] == [13, 16, 27, 33]
    # intersection with one neighbor on each side, plus the two numbers of the pair
    assert info["bet"] == sorted([6, 27, 13, 36, 1, 33, 16, 24, 3, 7])
    assert info["arcs"] == [[6, 27, 13, 36], [24, 16, 33, 1], [7], [3]]


def test_the_two_numbers_of_the_pair_are_in_the_bet_without_their_neighbors():
    info = pair_bet([4, 8, 20, 25, 28, 12, 31])
    assert info["kept"] == [17, 18, 22, 34]
    # before this rule neither 4 nor 8 was inside the bet
    assert info["bet"] == sorted([25, 17, 34, 6, 9, 22, 18, 29, 4, 8])
    for base in (4, 8):
        assert base in info["bet"]
        assert all(neighbor not in info["bet"] for neighbor in neighbors_of(base))


def test_the_switch_brings_back_the_bet_without_the_pair_numbers(monkeypatch):
    monkeypatch.setattr(rules, "INCLUDE_PAIR_NUMBERS", False)
    assert pair_bet([3, 7, 20, 25, 28, 12, 31])["bet"] == [1, 6, 13, 16, 24, 27, 33, 36]
    assert 8 not in pair_bet([4, 8, 20, 25, 28, 12, 31])["bet"]


def test_an_ignored_pair_never_has_a_bet(monkeypatch):
    info = pair_bet([6, 9, 20, 25, 28, 12, 31])
    assert (info["kind"], info["pair"], info["kept"], info["bet"], info["arcs"]) == ("ignored", [6, 9], [], [], [])
    assert pair_bet([9, 31, 6, 20, 25, 28, 12])["kind"] == "ignored"
    assert pair_bet([6, 20, 25, 28, 12, 31, 35])["kind"] == "no_pair"
    monkeypatch.setattr(rules, "IGNORED_PAIRS", frozenset())
    assert pair_bet([6, 9, 20, 25, 28, 12, 31])["kind"] == "ok"


def test_pair_does_not_depend_on_the_order_of_the_ranking():
    first = pair_bet([3, 20, 25, 7, 28, 12, 31])
    second = pair_bet([7, 3, 31, 12, 28, 25, 20])
    assert first == {**second, "bases": first["bases"]}
    assert first["bases"] == [3, 7] and second["bases"] == [7, 3]


def test_only_numbers_from_zero_to_nine_are_bases():
    assert pair_bet([0, 3, 20, 25, 28, 12, 31])["bases"] == [0, 3]
    assert pair_bet([10, 3, 20, 25, 28, 12, 31])["kind"] == "no_pair"


def test_rankings_without_a_valid_pair_have_no_bet():
    one = pair_bet([3, 20, 25, 28, 12, 31, 35])
    assert (one["kind"], one["pair"], one["bet"]) == ("no_pair", None, [])
    assert pair_bet([])["kind"] == "no_pair"
    many = pair_bet([1, 2, 3, 20, 25, 28, 12])
    assert (many["kind"], many["pair"], many["bet"], many["bases"]) == ("too_many", None, [], [1, 2, 3])
    # 0 and 7: no number of one group is a wheel neighbor of a number of the other.
    none = pair_bet([0, 7, 20, 25, 28, 12, 31])
    assert (none["kind"], none["pair"], none["bet"]) == ("no_intersection", [0, 7], [])


def test_bet_is_every_kept_number_with_one_neighbor_on_each_side_and_the_pair_itself():
    for first, second in combinations(range(10), 2):
        info = pair_bet([first, second, 20, 25, 28, 12, 31])
        if (first, second) == (6, 9):
            assert info["kind"] == "ignored"
            continue
        expected = set()
        for number in kept_numbers(first, second):
            expected.update((number, *neighbors_of(number)))
        if not expected:
            assert info["kind"] == "no_intersection" and info["bet"] == []
            continue
        expected.update((first, second))
        assert info["kind"] == "ok" and set(info["bet"]) == expected and info["bet"] == sorted(expected)
        assert sorted(number for arc in info["arcs"] for number in arc) == info["bet"]


def test_only_two_of_the_forty_five_pairs_have_no_intersection():
    empty = [pair for pair in combinations(range(10), 2) if not kept_numbers(*pair)]
    assert empty == [(0, 7), (0, 9)]
    assert len(kept_numbers(3, 4)) > 0


def test_wheel_arcs_group_adjacent_pockets_and_wrap_around_zero():
    assert wheel_arcs([]) == []
    assert wheel_arcs([26, 0, 32, 10]) == [[10], [26, 0, 32]]
    assert wheel_arcs([6, 27, 13, 36, 24, 16, 33, 1]) == [[6, 27, 13, 36], [24, 16, 33, 1]]
    assert wheel_arcs(WHEEL) == [list(WHEEL)]
    assert wheel_arcs([5]) == [[5]]
