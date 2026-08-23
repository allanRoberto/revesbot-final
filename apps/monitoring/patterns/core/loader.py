from __future__ import annotations

import importlib
import re

from .contracts import LoadedPattern


_ALIASES = {
    "last-hope": "last_hope",
    "lasthope": "last_hope",
    "nera-alpha": "nera",
    "nera_alpha": "nera",
}


def normalize_pattern_key(value: str) -> str:
    key = str(value or "").strip().lower()
    key = _ALIASES.get(key, key.replace("-", "_"))
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", key):
        raise ValueError("identificador de pattern invalido")
    return key


def load_pattern(value: str) -> LoadedPattern:
    key = normalize_pattern_key(value)
    try:
        module = importlib.import_module(
            f"apps.monitoring.patterns.{key}.definition"
        )
    except ModuleNotFoundError as exc:
        expected = f"apps.monitoring.patterns.{key}.definition"
        if exc.name == expected or str(exc.name or "").startswith(expected + "."):
            raise ValueError(f"pattern nao instalado: {key}") from exc
        raise
    factory = getattr(module, "create_pattern", None)
    if not callable(factory):
        raise ValueError(f"pattern sem create_pattern(): {key}")
    loaded = factory()
    if not isinstance(loaded, LoadedPattern):
        raise TypeError(f"create_pattern() de {key} retornou contrato invalido")
    if loaded.definition.key != key:
        raise ValueError(
            f"pattern carregado com chave divergente: {loaded.definition.key} != {key}"
        )
    return loaded


__all__ = ["load_pattern", "normalize_pattern_key"]
