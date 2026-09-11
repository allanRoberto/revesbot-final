from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from .config import BehaviorLabConfig
from .contracts import Spin, utc_now_iso
from .engine import BehaviorEngine
from .metrics import build_metrics


CHRONOLOGICAL_ORDERS = {"chronological", "oldest-first", "oldest_first"}
REVERSE_ORDERS = {"newest-first", "newest_first", "reverse-chronological"}


def _ordered(events: Sequence[int | Mapping[str, Any] | Spin], input_order: str) -> list[Any]:
    normalized = str(input_order).strip().lower()
    if normalized in CHRONOLOGICAL_ORDERS:
        return list(events)
    if normalized in REVERSE_ORDERS:
        return list(reversed(events))
    raise ValueError("input_order deve ser chronological/oldest-first ou newest-first")


def replay(
    events: Sequence[int | Mapping[str, Any] | Spin],
    *,
    config: BehaviorLabConfig,
    input_order: str = "chronological",
    include_decisions: bool = True,
    include_signals: bool = True,
) -> dict[str, Any]:
    chronological = _ordered(events, input_order)
    engine = BehaviorEngine(config)
    decisions: list[dict[str, Any]] = []
    accepted_payload: list[dict[str, Any]] = []
    duplicate_events = 0

    for raw in chronological:
        suggestion_before = list(engine.current_suggestion())
        active_before = [signal.signal_id for signal in engine.ledger.active]
        outcome = engine.process(raw, source="backtest")
        if outcome.duplicate:
            duplicate_events += 1
            continue
        if not outcome.accepted or outcome.spin is None or outcome.index is None:
            continue
        accepted_payload.append(outcome.spin.as_dict())
        decisions.append(
            {
                "index": outcome.index,
                "event_id": outcome.spin.external_game_id or outcome.spin.event_id,
                "result": outcome.spin.value,
                "suggestion": suggestion_before,
                "active_signal_ids": active_before,
                "hit": outcome.spin.value in suggestion_before,
                "decision": "BET" if suggestion_before else "NO_BET",
                "activated_signal_ids": list(outcome.activated_signal_ids),
                "resolved_signal_ids": list(outcome.resolved_signal_ids),
            }
        )

    final_index = engine.processed_count - 1 if engine.processed_count else None
    engine.ledger.censor_active(final_index)
    metrics = build_metrics(
        signals=engine.ledger.signals,
        decisions=decisions,
        accepted_spins=engine.processed_count,
        duplicate_events=duplicate_events,
        decisions_scope="full_sample",
    )
    final_snapshot = engine.snapshot()
    # The engine retains only a bounded decision window for live operation;
    # a backtest report must expose one consistent full-sample metric set.
    final_snapshot["metrics"] = metrics
    data_json = json.dumps(accepted_payload, sort_keys=True, separators=(",", ":"))
    report: dict[str, Any] = {
        "schema_version": "behavior-lab-backtest-v1",
        "generated_at": utc_now_iso(),
        "roulette_id": config.roulette_id,
        "input_order": input_order,
        "causal": True,
        "horizon": config.signal_horizon,
        "config": config.as_dict(),
        "config_fingerprint": config.fingerprint,
        "data_fingerprint": hashlib.sha256(data_json.encode("utf-8")).hexdigest()[:16],
        "metrics": metrics,
        "final_snapshot": final_snapshot,
    }
    if include_decisions:
        report["decisions"] = decisions
    if include_signals:
        report["signals"] = [signal.as_dict() for signal in engine.ledger.signals]
    return report
