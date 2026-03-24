from __future__ import annotations

from api.services.pattern_weight_profiles import PatternWeightProfilesService


def test_save_load_and_list_profiles(tmp_path) -> None:
    service = PatternWeightProfilesService(base_dir=tmp_path)

    saved = service.save_profile(
        name="Treino Pragmatic",
        roulette_id="pragmatic-auto-roulette",
        history_size=1000,
        max_attempts=4,
        optimized_max_numbers=18,
        use_adaptive_weights=False,
        config={"min_sample": 20},
        summary={"overall_hit_rate": 0.42, "attributed_hit_rate": 0.31},
        patterns=[{"pattern_id": "p1", "recommended_multiplier": 1.2}],
        weights={"p1": 1.2},
        effective_weights={"p1": 4.8},
    )

    loaded = service.load_profile(saved["id"])
    profiles = service.list_profiles()

    assert loaded is not None
    assert loaded["name"] == "Treino Pragmatic"
    assert loaded["weights"]["p1"] == 1.2
    assert profiles[0]["id"] == saved["id"]
    assert profiles[0]["roulette_id"] == "pragmatic-auto-roulette"
