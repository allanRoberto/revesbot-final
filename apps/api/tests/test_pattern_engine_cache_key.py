from __future__ import annotations

from api.patterns.engine import PatternEngine


def test_cache_key_changes_with_base_suggestion_and_runtime_overrides(tmp_path) -> None:
    engine = PatternEngine(patterns_dir=tmp_path)
    history = [4, 9, 15, 22, 31, 18]

    key_a = engine._build_cache_key(
        history,
        from_index=0,
        max_numbers=8,
        focus_number=4,
        base_suggestion=[4, 9, 15],
        runtime_overrides={"p1": {"threshold": 2}},
        use_adaptive_weights=True,
        use_fallback=True,
    )
    key_b = engine._build_cache_key(
        history,
        from_index=0,
        max_numbers=8,
        focus_number=4,
        base_suggestion=[4, 9, 22],
        runtime_overrides={"p1": {"threshold": 2}},
        use_adaptive_weights=True,
        use_fallback=True,
    )
    key_c = engine._build_cache_key(
        history,
        from_index=0,
        max_numbers=8,
        focus_number=4,
        base_suggestion=[4, 9, 15],
        runtime_overrides={"p1": {"threshold": 3}},
        use_adaptive_weights=True,
        use_fallback=True,
    )

    assert key_a != key_b
    assert key_a != key_c
