from __future__ import annotations

from itertools import combinations

from contextual_pairs import rules
from contextual_pairs.rules import digital_root, group, kept_numbers, pair_bet, protection_triples, wheel_arcs
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
    # intersection with one neighbor on each side, the two numbers of the pair and the protection numbers
    assert info["bet"] == sorted([6, 27, 13, 36, 1, 33, 16, 24, 3, 7, 2, 12, 21, 25, 28])
    assert info["protection"] == [2, 12, 21, 25, 28]
    assert info["protection_triples"] == [[21, 2, 25], [7, 28, 12]]
    assert info["arcs"] == [[21, 2, 25], [6, 27, 13, 36], [24, 16, 33, 1], [7, 28, 12], [3]]


def test_the_two_numbers_of_the_pair_are_in_the_bet_without_their_neighbors():
    info = pair_bet([4, 8, 20, 25, 28, 12, 31])
    assert info["kept"] == [17, 18, 22, 34]
    # before this rule neither 4 nor 8 was inside the bet
    assert info["bet"] == sorted([25, 17, 34, 6, 9, 22, 18, 29, 4, 8])
    for base in (4, 8):
        assert base in info["bet"]
        assert all(neighbor not in info["bet"] for neighbor in neighbors_of(base))


def test_the_switch_brings_back_the_bet_without_the_pair_numbers(monkeypatch):
    monkeypatch.setattr(rules, "INCLUDE_PROTECTION", False)
    monkeypatch.setattr(rules, "INCLUDE_PAIR_NUMBERS", False)
    assert pair_bet([3, 7, 20, 25, 28, 12, 31])["bet"] == [1, 6, 13, 16, 24, 27, 33, 36]
    assert 8 not in pair_bet([4, 8, 20, 25, 28, 12, 31])["bet"]


def test_the_protection_switch_brings_back_the_bet_without_protection(monkeypatch):
    monkeypatch.setattr(rules, "INCLUDE_PROTECTION", False)
    info = pair_bet([3, 7, 20, 25, 28, 12, 31])
    assert info["bet"] == sorted([6, 27, 13, 36, 1, 33, 16, 24, 3, 7])
    assert (info["protection"], info["protection_triples"]) == ([], [])


def test_user_example_protection_for_four_and_five():
    # 17 sits between 25 (group of 5) and 34 (group of 4); 19 between 15 (group of 5) and 4.
    assert protection_triples(4, 5) == [[15, 19, 4], [25, 17, 34]]
    info = pair_bet([4, 5, 20, 21, 22, 23, 24])
    assert info["kept"] == [5, 14, 24, 31]
    assert info["protection"] == [15, 17, 19, 25, 34]
    # 16 is a neighbor of the kept 24: it was already in the bet, so it is not a protection number
    assert 16 in info["bet"] and 16 not in info["protection"]
    assert info["bet"] == sorted([4, 5, 9, 10, 14, 16, 20, 24, 31] + [15, 17, 19, 25, 34])


def test_protection_triples_are_the_numbers_between_a_number_of_each_group():
    position = {number: index for index, number in enumerate(WHEEL)}
    size = len(WHEEL)
    for first, second in combinations(range(10), 2):
        expected = set()
        for one in group(first):
            for other in group(second):
                gap = (position[other] - position[one]) % size
                if gap == 2:  # one number sits between them, going clockwise from `one`
                    expected.add((one, WHEEL[(position[one] + 1) % size], other))
                if gap == size - 2:  # the same, going clockwise from `other`
                    expected.add((other, WHEEL[(position[other] + 1) % size], one))
        assert {tuple(triple) for triple in protection_triples(first, second)} == expected, (first, second)
        for left, middle, right in protection_triples(first, second):
            assert set(neighbors_of(middle)) == {left, right}


def test_protection_only_adds_numbers_the_rest_of_the_bet_did_not_have(monkeypatch):
    for first, second in combinations(range(10), 2):
        top = [first, second, 20, 25, 28, 12, 31]
        full = pair_bet(top)
        monkeypatch.setattr(rules, "INCLUDE_PROTECTION", False)
        plain = pair_bet(top)
        monkeypatch.setattr(rules, "INCLUDE_PROTECTION", True)
        if full["kind"] != "ok":  # ignored or without intersection: no bet, so nothing to protect
            assert (full["protection"], full["protection_triples"]) == ([], [])
            continue
        triple_numbers = {number for triple in full["protection_triples"] for number in triple}
        assert set(full["protection"]) == triple_numbers - set(plain["bet"])
        assert full["bet"] == sorted(set(plain["bet"]) | triple_numbers)
        assert full["protection"] == sorted(full["protection"])


def test_pairs_without_a_triple_between_the_groups_get_no_protection():
    for first, second in ((0, 2), (2, 5), (3, 8), (4, 8)):
        info = pair_bet([first, second, 20, 25, 28, 12, 31])
        assert info["kind"] == "ok" and info["protection"] == [] and info["protection_triples"] == []


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


def test_bet_is_every_kept_number_with_one_neighbor_on_each_side_the_pair_itself_and_the_protection():
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
        for triple in protection_triples(first, second):
            expected.update(triple)
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
