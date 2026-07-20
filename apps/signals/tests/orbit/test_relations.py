from shared.python.roulette.orbit.relation_matrix import RELATION_MATRIX


def test_13_reinforcement_relations():
    assert RELATION_MATRIX.get(13, 31).mirror is True
    assert RELATION_MATRIX.get(27, 13).wheel_distance == 1
    assert RELATION_MATRIX.get(13, 14).numeric_sequence_distance == 1


def test_sum_family_is_symmetric():
    for source in (5, 14, 23, 32):
        for target in (5, 14, 23, 32):
            assert RELATION_MATRIX.get(source, target).same_digit_sum is True


def test_signed_wheel_delta_19_to_14():
    relation = RELATION_MATRIX.get(19, 14)
    assert relation.wheel_delta == -15
    assert relation.wheel_distance == 15
    assert relation.numeric_delta == -5
