from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from api.routes import terminal_signals
from api.schemas.terminal_signals import (
    TerminalSignalProfitabilityRequest,
    TerminalSignalScenarioRequest,
    TerminalSignalStrategyRequest,
)


def test_profitability_request_normalizes_roulettes_and_defaults() -> None:
    payload = TerminalSignalProfitabilityRequest(
        variant="cruzado",
        roulette_ids=[
            " pragmatic-auto-roulette ",
            "pragmatic-auto-roulette",
            "pragmatic-brazilian-roulette",
        ],
    )

    assert payload.roulette_ids == [
        "pragmatic-auto-roulette",
        "pragmatic-brazilian-roulette",
    ]
    assert payload.attempt_stakes[:2] == [Decimal("1"), Decimal("1.5")]
    assert len(payload.attempt_stakes) == 10
    assert payload.payout_mode == "source_html"

    with pytest.raises(ValidationError):
        TerminalSignalProfitabilityRequest(
            variant="gemeos",
            attempt_stakes=[Decimal("1")],
        )

    with pytest.raises(ValidationError):
        TerminalSignalProfitabilityRequest(
            variant="gemeos",
            max_attempts=4,
            attempt_stakes=[Decimal("1"), Decimal("1.5")],
        )


def test_scenario_request_requires_stakes_through_t10() -> None:
    payload = TerminalSignalScenarioRequest(variant="motor-a-vizinhos")
    assert payload.minimum_attempts == 2
    assert payload.maximum_attempts == 10
    assert len(payload.attempt_stakes) == 10

    with pytest.raises(ValidationError):
        TerminalSignalScenarioRequest(
            variant="motor-a-vizinhos",
            attempt_stakes=[Decimal("1")] * 9,
        )


def test_strategy_request_defaults_to_top3_last10_with_tie30() -> None:
    payload = TerminalSignalStrategyRequest(variant="motor-a-vizinhos")

    assert payload.selection_mode == "top3"
    assert payload.ranking_lookback == 10
    assert payload.tie_break_lookback == 30
    assert payload.minimum_samples == 10
    assert payload.comparison_modes == ["all", "top3", "top1"]

    with pytest.raises(ValidationError):
        TerminalSignalStrategyRequest(
            variant="motor-a-vizinhos",
            ranking_lookback=10,
            minimum_samples=11,
        )
    with pytest.raises(ValidationError):
        TerminalSignalStrategyRequest(
            variant="motor-a-vizinhos",
            selection_mode="fixed",
        )


def test_summary_route_passes_individual_roulette_filter(monkeypatch) -> None:
    captured = {}

    async def fake_summary(variant, **kwargs):
        captured["variant"] = variant
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(terminal_signals.terminal_signal_service, "summary", fake_summary)

    result = asyncio.run(
        terminal_signals.terminal_signal_summary(
            variant="motor-a-seco",
            roulette_ids="pragmatic-auto-roulette,pragmatic-brazilian-roulette",
            window="24h",
            max_attempts=4,
            maximum_records=1_000,
        )
    )

    assert result == {"ok": True}
    assert captured["variant"] == "motor-a-seco"
    assert captured["roulette_ids"] == (
        "pragmatic-auto-roulette",
        "pragmatic-brazilian-roulette",
    )
    assert captured["max_attempts"] == 4


def test_scenarios_route_uses_common_t10_comparison(monkeypatch) -> None:
    captured = {}

    async def fake_scenarios(variant, **kwargs):
        captured["variant"] = variant
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(
        terminal_signals.terminal_signal_service,
        "scenarios",
        fake_scenarios,
    )
    payload = TerminalSignalScenarioRequest(variant="motor-a-vizinhos")

    result = asyncio.run(terminal_signals.terminal_signal_scenarios(payload))

    assert result == {"ok": True}
    assert captured["minimum_attempts"] == 2
    assert captured["maximum_attempts"] == 10
    assert len(captured["attempt_stakes"]) == 10


def test_strategy_route_passes_dynamic_ranking_configuration(monkeypatch) -> None:
    captured = {}

    async def fake_strategy(variant, **kwargs):
        captured["variant"] = variant
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(
        terminal_signals.terminal_signal_service,
        "strategy",
        fake_strategy,
    )
    payload = TerminalSignalStrategyRequest(
        variant="motor-a-vizinhos",
        selection_mode="top1",
        ranking_lookback=20,
        tie_break_lookback=40,
        minimum_samples=15,
        max_attempts=4,
    )

    result = asyncio.run(terminal_signals.terminal_signal_strategy(payload))

    assert result == {"ok": True}
    assert captured["selection_mode"] == "top1"
    assert captured["ranking_lookback"] == 20
    assert captured["tie_break_lookback"] == 40
    assert captured["minimum_samples"] == 15
    assert captured["max_attempts"] == 4


def test_dashboard_contains_variant_and_roulette_selectors() -> None:
    template = (
        Path(__file__).resolve().parents[1]
        / "templates"
        / "terminal_signals.html"
    ).read_text(encoding="utf-8")

    assert 'id="variant"' in template
    assert 'id="roulette"' in template
    assert 'id="chart"' in template
    assert "/api/terminal-signals/summary" in template
    assert "/api/terminal-signals/profitability" in template
    assert "/api/terminal-signals/scenarios" in template
    assert "/api/terminal-signals/strategy" in template
    assert 'id="maxAttempts"' in template
    assert 'id="scenarios"' in template
