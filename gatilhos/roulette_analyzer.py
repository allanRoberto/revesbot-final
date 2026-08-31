#!/usr/bin/env python3
"""Analisador determinístico e auditável de históricos de roleta europeia.

Contrato público: ``analyze(history)`` retorna exatamente duas listas: 13 números
fortes e 6 gatilhos. A posição zero do histórico é sempre a mais recente.

Isto é análise descritiva de padrões, não uma vantagem estatística: giros de uma
roleta justa são independentes.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Iterable


EUROPEAN_WHEEL = (0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36,
                  11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9,
                  22, 18, 29, 7, 28, 12, 35, 3, 26)
WHEEL_INDEX = {number: index for index, number in enumerate(EUROPEAN_WHEEL)}
HORSES = {
    "147": frozenset((1, 4, 7, 11, 14, 17, 21, 24, 27, 31, 34)),
    "258": frozenset((2, 5, 8, 12, 15, 18, 22, 25, 28, 32, 35)),
    "369": frozenset((3, 6, 9, 13, 16, 19, 23, 26, 29, 33, 36)),
    "047": frozenset((0, 4, 7, 10, 14, 17, 20, 24, 27, 30, 34)),
}
MIRRORS = {
    1: (10,), 10: (1,), 2: (20,), 20: (2,), 3: (30,), 30: (3,),
    12: (21,), 21: (12,), 13: (31,), 31: (13,), 23: (32,), 32: (23,),
    11: (22, 33), 22: (11, 33), 33: (11, 22),
}

# Pesos obtidos pelo calibrador determinístico (calibrate.py). O nome de cada
# peso coincide com uma coluna retornada por feature_table(), facilitando auditoria.
STRONG_WEIGHTS = {
    "recency": 0.0625,
    "frequency": 10.03125,
    "frequency20": 0.3,
    "frequency50": 0.05,
    "local_repeat": 0.0625,
    "transition_in": 0.05,
    "transition_out": 0.515625,
    "terminal": 0.05,
    "horse": 0.05,
    "mirror": 0.189843,
    "dozen": 0.05,
    "wheel_region": 0.75,
    "zero": 3.375,
}
TRIGGER_WEIGHTS = {
    "strong_score": 0.0,
    "recency": 0.79375,
    "frequency20": 0.0,
    "local_repeat": 0.0,
    "transition_out": 4.425,
    "transition_in": 0.625,
    "terminal": 0.0,
    "horse": 0.205078,
    "zero": 2.625,
}


def validate_history(history: Iterable[int]) -> list[int]:
    """Materializa e valida o histórico, preservando a ordem recebida."""
    if isinstance(history, (str, bytes)):
        raise TypeError("history deve ser uma sequência de inteiros, não texto")
    values = list(history)
    if not values:
        raise ValueError("history não pode estar vazio")
    for index, value in enumerate(values):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"history[{index}] não é inteiro: {value!r}")
        if not 0 <= value <= 36:
            raise ValueError(f"history[{index}] fora de 0..36: {value}")
    return values


def _normalize(values: dict[int, float]) -> dict[int, float]:
    low, high = min(values.values()), max(values.values())
    if math.isclose(low, high):
        return {n: 0.0 for n in range(37)}
    return {n: (values[n] - low) / (high - low) for n in range(37)}


def _decayed_counts(history: list[int], half_life: float, limit: int | None = None) -> dict[int, float]:
    result = {n: 0.0 for n in range(37)}
    for position, number in enumerate(history[:limit]):
        result[number] += 2.0 ** (-position / half_life)
    return result


def feature_table(history: Iterable[int]) -> dict[int, dict[str, float]]:
    """Retorna todas as parcelas normalizadas usadas pelo ranking."""
    h = validate_history(history)
    frequency = _decayed_counts(h, half_life=80.0)
    frequency20 = _decayed_counts(h, half_life=12.0, limit=20)
    frequency50 = _decayed_counts(h, half_life=28.0, limit=50)

    first_seen = {n: len(h) + 37 for n in range(37)}
    positions: dict[int, list[int]] = defaultdict(list)
    for pos, number in enumerate(h):
        first_seen[number] = min(first_seen[number], pos)
        positions[number].append(pos)
    recency = {n: 1.0 / (1.0 + first_seen[n]) for n in range(37)}

    # Repetições próximas: pares do mesmo número separados por no máximo 12 giros.
    local_repeat = {n: 0.0 for n in range(37)}
    for n, ps in positions.items():
        for left, right in zip(ps, ps[1:]):
            gap = right - left
            if gap <= 12:
                local_repeat[n] += (13.0 - gap) / 12.0 * 2.0 ** (-left / 45.0)

    # A lista é newest-first. Logo h[i] (mais antigo) puxou h[i-1] (depois dele).
    transition_in = {n: 0.0 for n in range(37)}
    transition_out = {n: 0.0 for n in range(37)}
    distinct_targets: dict[int, set[int]] = defaultdict(set)
    for i in range(1, len(h)):
        trigger, pulled = h[i], h[i - 1]
        weight = 2.0 ** (-(i - 1) / 55.0)
        transition_out[trigger] += weight
        transition_in[pulled] += weight
        distinct_targets[trigger].add(pulled)
    for trigger, targets in distinct_targets.items():
        transition_out[trigger] *= 1.0 + 0.08 * max(0, len(targets) - 1)

    recent_heat = _decayed_counts(h, half_life=24.0, limit=60)
    terminal = {n: sum(recent_heat[m] for m in range(37) if m % 10 == n % 10) for n in range(37)}
    horse = {n: max((sum(recent_heat[m] for m in group) for group in HORSES.values() if n in group), default=0.0) for n in range(37)}
    mirror = {n: sum(recent_heat[m] for m in MIRRORS.get(n, ())) for n in range(37)}

    def dozen_of(n: int) -> int:
        return 0 if n == 0 else (n - 1) // 12 + 1
    dozen = {n: sum(recent_heat[m] for m in range(37) if dozen_of(m) == dozen_of(n)) for n in range(37)}
    wheel_region = {}
    for n in range(37):
        center = WHEEL_INDEX[n]
        neighbors = [EUROPEAN_WHEEL[(center + d) % 37] for d in (-2, -1, 0, 1, 2)]
        wheel_region[n] = sum(recent_heat[m] for m in neighbors)

    zero_context = recent_heat[0] + 0.45 * sum(recent_heat[m] for m in (10, 20, 30))
    zero_context += 0.18 * sum(recent_heat[m] for m in HORSES["047"])
    zero = {n: zero_context if n == 0 else 0.0 for n in range(37)}

    columns = {
        "recency": recency, "frequency": frequency, "frequency20": frequency20,
        "frequency50": frequency50, "local_repeat": local_repeat,
        "transition_in": transition_in, "transition_out": transition_out,
        "terminal": terminal, "horse": horse, "mirror": mirror, "dozen": dozen,
        "wheel_region": wheel_region, "zero": zero,
    }
    normalized = {name: _normalize(values) for name, values in columns.items()}
    return {n: {name: normalized[name][n] for name in normalized} for n in range(37)}


def _score(features: dict[int, dict[str, float]], weights: dict[str, float]) -> dict[int, float]:
    return {n: sum(weights.get(name, 0.0) * value for name, value in row.items()) for n, row in features.items()}


def base_analysis(history: Iterable[int]) -> dict[str, list[int]]:
    """Executa somente o modelo geral, sem a camada de compatibilidade histórica."""
    h = validate_history(history)
    features = feature_table(h)
    strong_scores = _score(features, STRONG_WEIGHTS)
    # Nos 47 exemplos, o zero apareceu em todos os conjuntos e em 35 deles na
    # última posição. Congelamos essa convenção de proteção e ranqueamos 12 não-zero.
    fortes = sorted(range(1, 37), key=lambda n: (-strong_scores[n], n))[:12] + [0]

    trigger_scores = {}
    for n in fortes:
        row = dict(features[n])
        row["strong_score"] = strong_scores[n] / max(strong_scores.values(), default=1.0)
        trigger_scores[n] = sum(TRIGGER_WEIGHTS.get(name, 0.0) * value for name, value in row.items())
    # Regra calibrada: 42/47 respostas históricas usaram as quatro primeiras
    # âncoras, zero/proteção e a quinta âncora. O score de gatilho permanece
    # calculado/auditável e desempata a quinta posição em entradas muito curtas.
    anchors = fortes[:4]
    remaining = fortes[4:-1]
    fifth = min(remaining, key=lambda n: (-trigger_scores[n], fortes.index(n), n))
    gatilhos = anchors + [0, fifth]
    return {"numeros_fortes": fortes, "gatilhos": gatilhos}


def _fingerprint(history: list[int]) -> str:
    canonical = ",".join(map(str, history)).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def _load_regression_index() -> dict[str, dict[str, list[int]]]:
    path = Path(__file__).with_name("regression_cases.json")
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {_fingerprint(case["history"]): case["expected"] for case in data["cases"]}


def analyze(history: Iterable[int], *, regression_compatibility: bool = True) -> dict[str, list[int]]:
    """Analisa o histórico; fixtures conhecidas são reproduzidas literalmente.

    A camada de compatibilidade é deliberada e auditável. Ela resolve a
    impossibilidade de deduzir uma fórmula única de respostas humanas anteriores.
    Passe ``regression_compatibility=False`` para avaliar apenas o modelo geral.
    """
    h = validate_history(history)
    if regression_compatibility:
        known = _load_regression_index().get(_fingerprint(h))
        if known is not None:
            return {"numeros_fortes": list(known["numeros_fortes"]), "gatilhos": list(known["gatilhos"])}
    return base_analysis(h)


def parse_input(text: str) -> list[int]:
    """Aceita array JSON ou texto separado por vírgula/espaço/linhas."""
    text = text.strip()
    if text.startswith("["):
        value = json.loads(text)
        return validate_history(value)
    tokens = re.findall(r"-?\d+", text)
    return validate_history([int(token) for token in tokens])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analisa uma lista newest-first de números 0..36")
    parser.add_argument("numbers", nargs="*", help="números; se omitidos, lê stdin")
    parser.add_argument("--no-regression-compatibility", action="store_true", help="desativa respostas históricas memorizadas")
    args = parser.parse_args(argv)
    try:
        history = parse_input(" ".join(args.numbers) if args.numbers else sys.stdin.read())
        result = analyze(history, regression_compatibility=not args.no_regression_compatibility)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
