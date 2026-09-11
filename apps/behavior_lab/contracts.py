from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

from .wheel import validate_number


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SignalStatus(str, Enum):
    ACTIVE = "active"
    WON = "won"
    LOST = "lost"
    CENSORED = "censored"


@dataclass(frozen=True)
class Spin:
    value: int
    roulette_id: str = "pragmatic-auto-roulette"
    event_id: str | None = None
    external_game_id: str | None = None
    timestamp: str | None = None
    source: str = "unknown"

    @classmethod
    def from_raw(
        cls,
        raw: int | Mapping[str, Any] | "Spin",
        *,
        expected_roulette_id: str = "pragmatic-auto-roulette",
        source: str = "unknown",
    ) -> "Spin":
        if isinstance(raw, Spin):
            if raw.roulette_id != expected_roulette_id:
                raise ValueError("evento pertence a outra roleta")
            return raw
        if not isinstance(raw, Mapping):
            return cls(value=validate_number(raw), roulette_id=expected_roulette_id, source=source)

        nested = raw.get("full_result")
        full_result = nested if isinstance(nested, Mapping) else {}
        roulette_id = str(
            raw.get("roulette_id")
            or raw.get("slug")
            or full_result.get("roulette_id")
            or full_result.get("slug")
            or expected_roulette_id
        ).strip()
        if roulette_id != expected_roulette_id:
            raise ValueError(f"roleta nao suportada: {roulette_id}")
        candidate = raw.get(
            "value",
            raw.get("result", raw.get("number", full_result.get("value"))),
        )
        value = validate_number(candidate)
        event_id_raw = full_result.get("_id") or raw.get("_id") or raw.get("event_id")
        external_raw = full_result.get("external_game_id") or raw.get("external_game_id")
        timestamp_raw = (
            full_result.get("timestamp")
            or raw.get("timestamp")
            or full_result.get("captured_at")
            or raw.get("captured_at")
        )
        return cls(
            value=value,
            roulette_id=roulette_id,
            event_id=str(event_id_raw) if event_id_raw not in (None, "") else None,
            external_game_id=str(external_raw) if external_raw not in (None, "") else None,
            timestamp=str(timestamp_raw) if timestamp_raw not in (None, "") else None,
            source=source,
        )

    @property
    def identity_keys(self) -> tuple[str, ...]:
        keys: list[str] = []
        if self.external_game_id:
            keys.append(f"external:{self.external_game_id}")
        if self.event_id:
            keys.append(f"id:{self.event_id}")
        return tuple(keys)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RuleProposal:
    rule: str
    targets: tuple[int, ...]
    exhausted_targets: tuple[int, ...]
    evidence: dict[str, Any]


@dataclass
class Signal:
    signal_id: str
    rule: str
    roulette_id: str
    targets: list[int]
    suggested_numbers: list[int]
    exhausted_targets: list[int]
    evidence: dict[str, Any]
    activated_at_index: int
    activated_event_id: str | None
    activated_value: int
    status: SignalStatus = SignalStatus.ACTIVE
    attempts: int = 0
    payment_type: str | None = None
    paid_target: int | None = None
    paid_value: int | None = None
    resolved_at_index: int | None = None

    @classmethod
    def create(
        cls,
        *,
        proposal: RuleProposal,
        spin: Spin,
        index: int,
        suggested_numbers: list[int],
    ) -> "Signal":
        identity = spin.external_game_id or spin.event_id or str(index)
        raw_id = json.dumps(
            [proposal.rule, identity, list(proposal.targets), index],
            separators=(",", ":"),
        )
        signal_id = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:20]
        return cls(
            signal_id=signal_id,
            rule=proposal.rule,
            roulette_id=spin.roulette_id,
            targets=list(proposal.targets),
            suggested_numbers=suggested_numbers,
            exhausted_targets=list(proposal.exhausted_targets),
            evidence=proposal.evidence,
            activated_at_index=index,
            activated_event_id=spin.external_game_id or spin.event_id,
            activated_value=spin.value,
        )

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Signal":
        data = dict(raw)
        data["status"] = SignalStatus(str(data.get("status", "active")))
        return cls(**data)


@dataclass(frozen=True)
class ProcessResult:
    accepted: bool
    duplicate: bool
    index: int | None
    spin: Spin | None
    activated_signal_ids: tuple[str, ...] = ()
    resolved_signal_ids: tuple[str, ...] = ()
    active_signal_ids: tuple[str, ...] = ()
    suggestion: tuple[int, ...] = ()
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["spin"] = self.spin.as_dict() if self.spin else None
        return data
