from shared.python.roulette.orbit.identifiers import build_orbital_identifier


def test_identifier_changes_with_pivot_and_orbital_coordinate():
    source = build_orbital_identifier(
        pivot=19,
        number=14,
        occurrence_lag=-2,
        relative_offset=-1,
    )
    materialized = build_orbital_identifier(
        pivot=19,
        number=14,
        occurrence_lag=0,
        relative_offset=1,
    )
    other_pivot = build_orbital_identifier(
        pivot=35,
        number=14,
        occurrence_lag=-2,
        relative_offset=-1,
    )
    assert "P19|T-2|A1|N14" in source
    assert "P19|T+0|D1|N14" in materialized
    assert source != materialized
    assert source != other_pivot
