from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from api.routes import terminal_signals
from api.schemas.terminal_signals import TerminalSignalProfitabilityRequest


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
    assert payload.attempt_stakes == [Decimal("1"), Decimal("1.5")]
    assert payload.payout_mode == "source_html"

    with pytest.raises(ValidationError):
        TerminalSignalProfitabilityRequest(
            variant="gemeos",
            attempt_stakes=[Decimal("1")],
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
            maximum_records=1_000,
        )
    )

    assert result == {"ok": True}
    assert captured["variant"] == "motor-a-seco"
    assert captured["roulette_ids"] == (
        "pragmatic-auto-roulette",
        "pragmatic-brazilian-roulette",
    )


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
