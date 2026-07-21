import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from api.schemas.orbit_triggers import OrbitTriggerProfitabilityRequest
from api.services.orbit_trigger_service import OrbitTriggerService


def test_profitability_request_accepts_five_non_negative_stakes():
    payload = OrbitTriggerProfitabilityRequest(
        roulette_ids=["roulette-1", "roulette-1", "roulette-2"],
        strategy_slugs=["allan"],
        window="24h",
        initial_bank="1000.50",
        attempt_stakes=["10", "20", "40", "80", "160"],
    )

    assert payload.roulette_ids == ["roulette-1", "roulette-2"]
    assert payload.initial_bank == Decimal("1000.50")
    assert payload.attempt_stakes[4] == Decimal("160")


def test_profitability_request_accepts_all_eight_strategy_slugs():
    strategy_slugs = [
        "green-primeira",
        "allan",
        "inception",
        "inception-primeiros-4",
        "interrompimento",
        "distancia",
        "ryan",
        "ryan-2",
    ]
    payload = OrbitTriggerProfitabilityRequest(
        roulette_ids=["roulette-1"],
        strategy_slugs=strategy_slugs,
        initial_bank=1000,
        attempt_stakes=[10, 20, 40, 80, 160],
    )

    assert payload.strategy_slugs == strategy_slugs


@pytest.mark.parametrize(
    "field, value",
    [
        ("initial_bank", 0),
        ("attempt_stakes", [1, 2, 3]),
        ("attempt_stakes", [1, 2, 3, 4, -1]),
        ("attempt_stakes", [1, 2, 3, 4, 5.5]),
        ("window", "48h"),
    ],
)
def test_profitability_request_rejects_invalid_values(field, value):
    data = {
        "roulette_ids": ["roulette-1"],
        "initial_bank": 1000,
        "attempt_stakes": [10, 20, 40, 80, 160],
        "window": "24h",
    }
    data[field] = value
    with pytest.raises(ValidationError):
        OrbitTriggerProfitabilityRequest(**data)


def test_profitability_is_calculated_independently_for_each_roulette(monkeypatch):
    service = OrbitTriggerService()
    calls = []

    async def rows(strategy_slug, roulette_id, *, cutoff, maximum_records):
        calls.append((strategy_slug, roulette_id, cutoff, maximum_records))
        return [
            {
                "activation_timestamp_utc": datetime(2026, 7, 20, 18, tzinfo=timezone.utc),
                "first_hit_attempt": 1 if roulette_id == "roulette-a" else None,
                "target_size": 9,
            }
        ]

    monkeypatch.setattr(service, "_profitability_rows", rows)
    result = asyncio.run(
        service.profitability(
            ["roulette-a", "roulette-b", "roulette-a"],
            initial_bank=Decimal("1000"),
            attempt_stakes=[Decimal(value) for value in (1, 2, 4, 8, 16)],
            window="all",
            strategy_slugs=["ryan"],
        )
    )

    assert result["calculation_scope"] == "per_roulette"
    assert "strategies" not in result
    assert [row["roulette_id"] for row in result["roulettes"]] == [
        "roulette-a",
        "roulette-b",
    ]
    assert result["roulettes"][0]["strategies"][0]["final_bank"] == 1027.0
    assert result["roulettes"][1]["strategies"][0]["final_bank"] == 721.0
    assert {(strategy, roulette) for strategy, roulette, _, _ in calls} == {
        ("ryan", "roulette-a"),
        ("ryan", "roulette-b"),
    }
