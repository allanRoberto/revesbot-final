"""Modelo exploratorio de probabilidades para numeros de roleta europeia.

O motor combina frequencia com decaimento, frequencia em varias janelas,
transicoes de primeira ordem, proximidade na roda fisica e incerteza
bayesiana. A saida do softmax e um score normalizado: ela precisa superar
o baseline uniforme em backtests fora da amostra antes de ser interpretada
como vantagem preditiva.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal, Sequence

from shared.python.roulette.orbit.constants import EUROPEAN_WHEEL
from shared.python.roulette.orbit.probability import softmax


HistoryOrder = Literal["chronological", "newest_first"]
ROULETTE_SIZE = 37
WHEEL_INDEX = {number: index for index, number in enumerate(EUROPEAN_WHEEL)}


@dataclass(frozen=True, slots=True)
class ProbabilityModelConfig:
    """Parametros versionados da expressao central."""

    alpha: float = 1.0
    half_life: float = 250.0
    markov_backoff: float = 20.0
    recent_windows: tuple[int, ...] = (25, 50, 100, 250, 500, 1000)
    wheel_recent_limit: int = 100
    wheel_temporal_decay: float = 0.97
    wheel_sigma: float = 2.0
    frequency_weight: float = 0.45
    markov_weight: float = 0.25
    recency_weight: float = 0.15
    wheel_weight: float = 0.15
    uncertainty_penalty: float = 2.0
    temperature: float = 1.5
    minimum_history: int = 10

    def __post_init__(self) -> None:
        if self.alpha <= 0:
            raise ValueError("alpha deve ser positivo")
        if self.half_life <= 0:
            raise ValueError("half_life deve ser positivo")
        if self.markov_backoff <= 0:
            raise ValueError("markov_backoff deve ser positivo")
        if self.wheel_recent_limit < 1:
            raise ValueError("wheel_recent_limit deve ser positivo")
        if not 0 < self.wheel_temporal_decay <= 1:
            raise ValueError("wheel_temporal_decay deve estar em (0, 1]")
        if self.wheel_sigma <= 0:
            raise ValueError("wheel_sigma deve ser positivo")
        if self.temperature <= 0:
            raise ValueError("temperature deve ser positiva")
        if self.minimum_history < 2:
            raise ValueError("minimum_history deve ser pelo menos 2")
        if not self.recent_windows or any(window < 2 for window in self.recent_windows):
            raise ValueError("recent_windows deve conter janelas >= 2")


DEFAULT_CONFIG = ProbabilityModelConfig()


def _normalize_history(history: Sequence[int], order: HistoryOrder) -> list[int]:
    if order not in {"chronological", "newest_first"}:
        raise ValueError("order deve ser 'chronological' ou 'newest_first'")
    values: list[int] = []
    for raw in history:
        if isinstance(raw, bool):
            raise ValueError("o historico deve conter inteiros entre 0 e 36")
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("o historico deve conter inteiros entre 0 e 36") from exc
        if value != raw or not 0 <= value < ROULETTE_SIZE:
            raise ValueError("o historico deve conter inteiros entre 0 e 36")
        values.append(value)
    if order == "newest_first":
        values.reverse()
    return values


def _wheel_distance(left: int, right: int) -> int:
    distance = abs(WHEEL_INDEX[left] - WHEEL_INDEX[right])
    return min(distance, ROULETTE_SIZE - distance)


def _frequency_component(
    chronological: Sequence[int],
    config: ProbabilityModelConfig,
) -> tuple[dict[int, float], dict[int, float], float]:
    decay = 2.0 ** (-1.0 / config.half_life)
    counts = {number: 0.0 for number in range(ROULETTE_SIZE)}
    for age, number in enumerate(reversed(chronological)):
        counts[number] += decay**age
    weighted_total = sum(counts.values())
    dirichlet_total = weighted_total + ROULETTE_SIZE * config.alpha
    probabilities = {
        number: (counts[number] + config.alpha) / dirichlet_total
        for number in range(ROULETTE_SIZE)
    }
    return counts, probabilities, dirichlet_total


def _recency_component(
    chronological: Sequence[int],
    config: ProbabilityModelConfig,
) -> tuple[dict[int, float], tuple[int, ...]]:
    z_scores = {number: 0.0 for number in range(ROULETTE_SIZE)}
    effective_windows = tuple(
        sorted({min(window, len(chronological)) for window in config.recent_windows})
    )
    effective_windows = tuple(window for window in effective_windows if window >= 2)
    if not effective_windows:
        return z_scores, ()

    for window_size in effective_windows:
        recent = chronological[-window_size:]
        counts = {number: 0 for number in range(ROULETTE_SIZE)}
        for number in recent:
            counts[number] += 1
        expected = window_size / ROULETTE_SIZE
        standard_deviation = math.sqrt(
            window_size * (1.0 / ROULETTE_SIZE) * ((ROULETTE_SIZE - 1.0) / ROULETTE_SIZE)
        )
        for number in range(ROULETTE_SIZE):
            z_score = (counts[number] - expected) / standard_deviation
            z_scores[number] += max(-3.0, min(3.0, z_score))

    divisor = float(len(effective_windows))
    return (
        {number: z_scores[number] / divisor for number in range(ROULETTE_SIZE)},
        effective_windows,
    )


def _markov_component(
    chronological: Sequence[int],
    frequency_probabilities: dict[int, float],
    config: ProbabilityModelConfig,
) -> tuple[dict[int, float], float]:
    trigger = chronological[-1]
    decay = 2.0 ** (-1.0 / config.half_life)
    transition_counts = {number: 0.0 for number in range(ROULETTE_SIZE)}
    support = 0.0
    for index in range(len(chronological) - 1):
        if chronological[index] != trigger:
            continue
        age = (len(chronological) - 2) - index
        weight = decay**age
        transition_counts[chronological[index + 1]] += weight
        support += weight

    probabilities = {
        number: (
            transition_counts[number]
            + config.markov_backoff * frequency_probabilities[number]
        )
        / (support + config.markov_backoff)
        for number in range(ROULETTE_SIZE)
    }
    return probabilities, support


def _wheel_component(
    chronological: Sequence[int],
    config: ProbabilityModelConfig,
) -> dict[int, float]:
    raw = {number: config.alpha for number in range(ROULETTE_SIZE)}
    recent = chronological[-config.wheel_recent_limit :]
    for age, observed in enumerate(reversed(recent)):
        temporal_weight = config.wheel_temporal_decay**age
        for candidate in range(ROULETTE_SIZE):
            distance = _wheel_distance(candidate, observed)
            kernel = math.exp(-(distance**2) / (2.0 * config.wheel_sigma**2))
            raw[candidate] += temporal_weight * kernel
    total = sum(raw.values())
    return {number: raw[number] / total for number in range(ROULETTE_SIZE)}


def calculate_number_probabilities(
    history: Sequence[int],
    *,
    order: HistoryOrder = "chronological",
    number_count: int = 10,
    config: ProbabilityModelConfig | None = None,
) -> dict[str, Any]:
    """Calcula o ranking dos 37 numeros usando somente o historico recebido."""

    active_config = config or DEFAULT_CONFIG
    if isinstance(number_count, bool) or not 1 <= int(number_count) <= 36:
        raise ValueError("number_count deve estar entre 1 e 36")
    chronological = _normalize_history(history, order)
    if len(chronological) < active_config.minimum_history:
        raise ValueError(
            f"historico insuficiente: minimo de {active_config.minimum_history} resultados"
        )

    counts, frequency, dirichlet_total = _frequency_component(
        chronological, active_config
    )
    recency, effective_windows = _recency_component(chronological, active_config)
    markov, markov_support = _markov_component(
        chronological, frequency, active_config
    )
    wheel = _wheel_component(chronological, active_config)

    raw_scores: dict[int, float] = {}
    uncertainty_by_number: dict[int, float] = {}
    for number in range(ROULETTE_SIZE):
        parameter = counts[number] + active_config.alpha
        variance = (
            parameter
            * (dirichlet_total - parameter)
            / (dirichlet_total**2 * (dirichlet_total + 1.0))
        )
        uncertainty = math.sqrt(max(0.0, variance))
        uncertainty_by_number[number] = uncertainty
        raw_scores[number] = (
            active_config.frequency_weight * math.log(frequency[number])
            + active_config.markov_weight * math.log(markov[number])
            + active_config.recency_weight * recency[number]
            + active_config.wheel_weight * math.log(wheel[number])
            - active_config.uncertainty_penalty * uncertainty
        )

    probabilities = softmax(raw_scores, temperature=active_config.temperature)
    ranking = [
        {
            "rank": 0,
            "number": number,
            "probability": probabilities[number],
            "score": raw_scores[number],
            "frequency_probability": frequency[number],
            "markov_probability": markov[number],
            "recency_z": recency[number],
            "wheel_probability": wheel[number],
            "uncertainty": uncertainty_by_number[number],
            "straight_up_ev": 36.0 * probabilities[number] - 1.0,
        }
        for number in sorted(
            range(ROULETTE_SIZE),
            key=lambda candidate: (-probabilities[candidate], candidate),
        )
    ]
    for rank, row in enumerate(ranking, start=1):
        row["rank"] = rank

    selected = [row["number"] for row in ranking[: int(number_count)]]
    selected_mass = sum(probabilities[number] for number in selected)
    return {
        "engine_version": "central-probability-v1",
        "history_size": len(chronological),
        "history_order_received": order,
        "last_number": chronological[-1],
        "number_count": int(number_count),
        "selected": selected,
        "selected_probability_mass": selected_mass,
        "uniform_probability_mass": int(number_count) / ROULETTE_SIZE,
        "ranking": ranking,
        "diagnostics": {
            "markov_weighted_support": markov_support,
            "recent_windows": list(effective_windows),
            "probabilities_sum": sum(probabilities.values()),
            "score_is_calibrated_probability": False,
        },
    }


__all__ = [
    "DEFAULT_CONFIG",
    "ProbabilityModelConfig",
    "calculate_number_probabilities",
]
