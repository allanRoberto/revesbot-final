from __future__ import annotations

import asyncio

from api.services.assertiveness_replay import run_assertiveness_replay


def test_replay_measures_hit_by_attempt_and_profit() -> None:
    async def suggestion_provider(context_desc: list[int]) -> dict:
        focus = context_desc[0]
        mapping = {
            2: [3],
            3: [5],
            4: [9],
        }
        return {
            "available": True,
            "suggestion": mapping.get(focus, []),
            "confidence": {"score": 80, "label": "Alta"},
        }

    result = asyncio.run(
        run_assertiveness_replay(
            roulette_id="test-roulette",
            history_desc=[6, 5, 4, 3, 2, 1, 0],
            suggestion_provider=suggestion_provider,
            min_history_size=3,
            entries_limit=10,
            max_attempts=2,
            min_confidence=0,
            chip_values=[1.0, 1.0],
        )
    )

    assert result["available"] is True
    assert result["signals_taken"] == 3
    assert result["hits"] == 2
    assert result["misses"] == 1
    assert result["hit_rate_by_attempt"]["1"]["hits"] == 1
    assert result["hit_rate_by_attempt"]["2"]["hits"] == 1
    assert result["total_profit"] == 67.0


def test_replay_skips_entries_below_min_confidence() -> None:
    async def suggestion_provider(_: list[int]) -> dict:
        return {
            "available": True,
            "suggestion": [7, 11, 19],
            "confidence": {"score": 40, "label": "Baixa"},
        }

    result = asyncio.run(
        run_assertiveness_replay(
            roulette_id="test-roulette",
            history_desc=[6, 5, 4, 3, 2, 1, 0],
            suggestion_provider=suggestion_provider,
            min_history_size=3,
            entries_limit=10,
            max_attempts=2,
            min_confidence=60,
            chip_values=[1.0, 1.0],
        )
    )

    assert result["signals_taken"] == 0
    assert result["skipped_confidence"] == 3
    assert result["hits"] == 0


def test_replay_limits_to_most_recent_entries() -> None:
    seen_focuses: list[int] = []

    async def suggestion_provider(context_desc: list[int]) -> dict:
        seen_focuses.append(context_desc[0])
        return {
            "available": True,
            "suggestion": [99],
            "confidence": {"score": 90, "label": "Alta"},
        }

    asyncio.run(
        run_assertiveness_replay(
            roulette_id="test-roulette",
            history_desc=[8, 7, 6, 5, 4, 3, 2, 1, 0],
            suggestion_provider=suggestion_provider,
            min_history_size=3,
            entries_limit=2,
            max_attempts=2,
            min_confidence=0,
            chip_values=[1.0, 1.0],
        )
    )

    assert seen_focuses == [5, 6]
