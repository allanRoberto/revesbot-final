from shared.python.roulette.orbit.constants import DIGIT_SUM_GROUPS, MIRRORS
from shared.python.roulette.orbit.number_features import get_number_features


def test_number_35_matches_confirmed_identifier_features():
    features = get_number_features(35)
    assert features.wheel_index == 34
    assert features.parity == "IM"
    assert features.color == "PR"
    assert features.dozen == 3
    assert features.column == 2
    assert features.sector == "VZ"
    assert (features.digit_sum_group, features.digit_sum_position) == (8, 4)
    assert features.mirror is None
    assert (features.terminal_family, features.terminal_position) == ("258", 2)
    assert features.wheel_neighbors == (12, 3)


def test_zero_is_included_in_real_wheel_adjacency():
    assert get_number_features(32).wheel_neighbors == (0, 15)
    assert get_number_features(26).wheel_neighbors == (3, 0)


def test_user_mirror_registry_is_exact():
    assert MIRRORS[13] == 31
    assert MIRRORS[31] == 13
    assert 14 not in MIRRORS
    assert 34 not in MIRRORS


def test_digit_sum_groups_have_four_members_and_exclude_zero():
    assert DIGIT_SUM_GROUPS[5] == (5, 14, 23, 32)
    assert all(len(group) == 4 for group in DIGIT_SUM_GROUPS.values())
    assert all(0 not in group for group in DIGIT_SUM_GROUPS.values())
