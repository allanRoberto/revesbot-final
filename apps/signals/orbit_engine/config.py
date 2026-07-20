from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from shared.python.roulette.orbit.constants import SCHEMA_VERSION
from shared.python.roulette.orbit.evidence_graph import DEFAULT_RELATION_WEIGHTS


CONFIG_DIR = Path(__file__).resolve().parent / "config"


@dataclass(frozen=True, slots=True)
class OrbitEngineSettings:
    engine_version: str = "orbital-rule-v1"
    pre_window: int = 5
    post_window: int = 5
    memory_occurrences: int = 6
    horizons: tuple[int, ...] = (1, 2, 3)
    ranking_sizes: tuple[int, ...] = (9, 12)
    occurrence_decay: float = 0.78
    second_hop_damping: float = 0.20
    max_hops: int = 2
    relation_weights: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_RELATION_WEIGHTS))
    shadow_only: bool = True


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"configuracao precisa ser objeto JSON: {path}")
    return payload


def validate_relation_registry(path: Path | None = None) -> dict[str, Any]:
    payload = _load_json(path or (CONFIG_DIR / "relations_v1.json"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"schema de relacoes divergente: {payload.get('schema_version')} != {SCHEMA_VERSION}"
        )
    return payload


def load_engine_settings(path: Path | None = None) -> OrbitEngineSettings:
    validate_relation_registry()
    payload = _load_json(path or (CONFIG_DIR / "engine_v1.json"))
    policy = dict(payload.get("policy") or {})
    return OrbitEngineSettings(
        engine_version=str(payload.get("engine_version") or "orbital-rule-v1"),
        pre_window=max(1, int(payload.get("pre_window", 5))),
        post_window=max(1, int(payload.get("post_window", 5))),
        memory_occurrences=max(1, int(payload.get("memory_occurrences", 6))),
        horizons=tuple(max(1, int(value)) for value in payload.get("horizons", [1, 2, 3])),
        ranking_sizes=tuple(max(1, min(37, int(value))) for value in payload.get("ranking_sizes", [9, 12])),
        occurrence_decay=float(payload.get("occurrence_decay", 0.78)),
        second_hop_damping=float(payload.get("second_hop_damping", 0.20)),
        max_hops=max(1, min(2, int(payload.get("max_hops", 2)))),
        relation_weights={
            **DEFAULT_RELATION_WEIGHTS,
            **{
                str(name): float(value)
                for name, value in dict(payload.get("relation_weights") or {}).items()
            },
        },
        shadow_only=bool(policy.get("shadow_only", True)),
    )
