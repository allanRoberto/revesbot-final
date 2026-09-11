from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any, Mapping


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "default_v1.json"


@dataclass(frozen=True)
class BehaviorLabConfig:
    version: str = "v1"
    roulette_id: str = "pragmatic-auto-roulette"
    context_size: int = 500
    signal_horizon: int = 10
    neighbor_span: int = 1
    max_suggested_numbers: int = 12
    exhaustion_window: int = 8
    pair_tail_size: int = 3
    double_tail_size: int = 3
    structural_tail_size: int = 4
    structural_max_gap: int = 1
    terminal_one_numbers: tuple[int, ...] = (1, 11, 31)
    mirrors: tuple[tuple[int, int], ...] = ((13, 31),)
    redis_namespace: str = "behavior_lab:v1"

    def __post_init__(self) -> None:
        if self.roulette_id != "pragmatic-auto-roulette":
            raise ValueError("behavior-lab aceita apenas pragmatic-auto-roulette")
        positive = (
            "context_size",
            "signal_horizon",
            "max_suggested_numbers",
            "pair_tail_size",
            "double_tail_size",
            "structural_tail_size",
        )
        for name in positive:
            if int(getattr(self, name)) < 1:
                raise ValueError(f"{name} deve ser positivo")
        if self.signal_horizon != 10:
            raise ValueError("signal_horizon deve permanecer em 10 nesta versao")
        if not 0 <= self.neighbor_span <= 18:
            raise ValueError("neighbor_span fora do intervalo")
        if self.exhaustion_window < 0 or self.structural_max_gap not in (0, 1):
            raise ValueError("janela de configuracao invalida")
        for value in self.terminal_one_numbers:
            _validate_number(value)
        for left, right in self.mirrors:
            _validate_number(left)
            _validate_number(right)
            if left == right:
                raise ValueError("espelho deve apontar para outro numero")

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    @property
    def redis_prefix(self) -> str:
        return f"{self.redis_namespace}:{self.roulette_id}"

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["terminal_one_numbers"] = list(self.terminal_one_numbers)
        data["mirrors"] = [list(pair) for pair in self.mirrors]
        return data


def _validate_number(value: Any) -> int:
    if isinstance(value, (bool, float)):
        raise ValueError("resultado deve ser um inteiro")
    number = int(value)
    if not 0 <= number <= 36:
        raise ValueError(f"numero fora da roleta: {value!r}")
    return number


def _normalize(data: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {field.name for field in fields(BehaviorLabConfig)}
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f"campos de configuracao desconhecidos: {sorted(unknown)}")
    normalized = dict(data)
    if "terminal_one_numbers" in normalized:
        normalized["terminal_one_numbers"] = tuple(
            _validate_number(value) for value in normalized["terminal_one_numbers"]
        )
    if "mirrors" in normalized:
        normalized["mirrors"] = tuple(
            (_validate_number(pair[0]), _validate_number(pair[1]))
            for pair in normalized["mirrors"]
        )
    return normalized


def load_config(
    path: str | Path | None = None,
    *,
    overrides: Mapping[str, Any] | None = None,
) -> BehaviorLabConfig:
    """Load the frozen engine configuration.

    Only ``BEHAVIOR_LAB_CONFIG`` is consulted.  Runtime connection settings
    belong to the worker and cannot silently change replay semantics.
    """

    selected = Path(path or os.getenv("BEHAVIOR_LAB_CONFIG") or DEFAULT_CONFIG_PATH)
    with selected.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError("configuracao deve ser um objeto JSON")
    config = BehaviorLabConfig(**_normalize(raw))
    if overrides:
        config = replace(config, **_normalize(overrides))
    return config
