"""Port fiel das regras do HTML de Terminais Cruzado + Gêmeos.

Todas as funções recebem o histórico com o giro mais recente na posição zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .catalog import VariantSpec, get_variant


EUROPEAN_WHEEL = (
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23,
    10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26,
)
WHEEL_INDEX = {number: index for index, number in enumerate(EUROPEAN_WHEEL)}


def _number(value: Any) -> int:
    parsed = int(value)
    if not 0 <= parsed <= 36:
        raise ValueError(f"número de roleta inválido: {value}")
    return parsed


def wheel_neighbors(number: int) -> tuple[int, int]:
    value = _number(number)
    index = WHEEL_INDEX[value]
    return (
        EUROPEAN_WHEEL[(index - 1) % len(EUROPEAN_WHEEL)],
        EUROPEAN_WHEEL[(index + 1) % len(EUROPEAN_WHEEL)],
    )


def terminal_of(number: int) -> int:
    return _number(number) % 10


def terminal_group(terminal: int) -> tuple[int, ...]:
    value = int(terminal)
    if not 0 <= value <= 9:
        raise ValueError(f"terminal inválido: {terminal}")
    return tuple(number for number in range(37) if number % 10 == value)


def compute_terminal_targets(terminal: int, *, with_neighbors: bool) -> tuple[int, ...]:
    targets: set[int] = set(terminal_group(terminal))
    if with_neighbors:
        for number in tuple(targets):
            targets.update(wheel_neighbors(number))
    targets.add(0)
    return tuple(sorted(targets))


def compute_cross_targets(terminal_a: int, terminal_b: int) -> tuple[int, ...]:
    a = int(terminal_a)
    b = int(terminal_b)
    if not 0 <= a <= 9 or not 0 <= b <= 9:
        raise ValueError("terminais do cruzamento precisam estar entre 0 e 9")
    targets = {a, *wheel_neighbors(a), b, *wheel_neighbors(b), 0}
    return tuple(sorted(targets))


@dataclass(frozen=True, slots=True)
class PatternAnalysis:
    motor: str
    valid: bool
    idx0: int | None = None
    idx1: int | None = None
    terminal: int | None = None
    reason: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SignalCandidate:
    variant: str
    targets: tuple[int, ...]
    terminal_a: int | None
    terminal_b: int | None
    motor_a: PatternAnalysis | None
    motor_b: PatternAnalysis | None
    activation_number: int

    def as_document(self) -> dict[str, Any]:
        def analysis_payload(analysis: PatternAnalysis | None) -> dict[str, Any] | None:
            if analysis is None:
                return None
            return {
                "motor": analysis.motor,
                "valid": analysis.valid,
                "idx0": analysis.idx0,
                "idx1": analysis.idx1,
                "terminal": analysis.terminal,
                "reason": analysis.reason,
                "metadata": dict(analysis.metadata),
            }

        return {
            "variant": self.variant,
            "targets": list(self.targets),
            "target_size": len(self.targets),
            "terminal_a": self.terminal_a,
            "terminal_b": self.terminal_b,
            "motor_a": analysis_payload(self.motor_a),
            "motor_b": analysis_payload(self.motor_b),
            "activation_number": self.activation_number,
        }


def analyze_motor_a(history: Sequence[int]) -> PatternAnalysis:
    numbers = [_number(value) for value in history]
    if len(numbers) < 2:
        return PatternAnalysis("A", False, reason="Histórico insuficiente.")
    idx0, idx1 = numbers[0], numbers[1]
    if idx0 == idx1:
        return PatternAnalysis("A", False, idx0, idx1, reason="Os dois últimos números são iguais.")

    neighbors0 = wheel_neighbors(idx0)
    neighbors1 = wheel_neighbors(idx1)
    terminals0 = sorted(set(terminal_of(value) for value in neighbors0))
    terminals1 = sorted(set(terminal_of(value) for value in neighbors1))
    common = sorted(set(terminals0).intersection(terminals1))
    metadata = {
        "neighbors0": list(neighbors0),
        "neighbors1": list(neighbors1),
        "terminals0": terminals0,
        "terminals1": terminals1,
        "common_terminals": common,
    }
    if not common:
        return PatternAnalysis(
            "A", False, idx0, idx1,
            reason="Nenhum terminal em comum entre os vizinhos dos dois números.",
            metadata=metadata,
        )
    if len(common) > 1:
        return PatternAnalysis(
            "A", False, idx0, idx1,
            reason=f"Mais de um terminal em comum ({', '.join(map(str, common))}).",
            metadata=metadata,
        )
    return PatternAnalysis(
        "A", True, idx0, idx1, common[0],
        reason=f"Terminal em comum: {common[0]}.",
        metadata=metadata,
    )


def _previous_index(numbers: Sequence[int], value: int, start: int) -> int:
    for index in range(start, len(numbers)):
        if numbers[index] == value:
            return index
    return -1


def analyze_motor_b(history: Sequence[int]) -> PatternAnalysis:
    numbers = [_number(value) for value in history]
    if len(numbers) < 3:
        return PatternAnalysis("B", False, reason="Histórico insuficiente.")
    idx0, idx1 = numbers[0], numbers[1]
    if idx0 == idx1:
        return PatternAnalysis("B", False, idx0, idx1, reason="Os dois últimos números são iguais.")

    previous0 = _previous_index(numbers, idx0, 1)
    previous1 = _previous_index(numbers, idx1, 2)
    if previous0 == -1 or previous1 == -1 or previous0 - 1 < 0 or previous1 - 1 < 0:
        return PatternAnalysis(
            "B", False, idx0, idx1,
            reason="Não há ocorrência anterior suficiente no histórico.",
            metadata={"previous_index0": previous0, "previous_index1": previous1},
        )

    pulled0 = numbers[previous0 - 1]
    pulled1 = numbers[previous1 - 1]
    base_metadata = {
        "previous_index0": previous0,
        "previous_index1": previous1,
        "pulled0": pulled0,
        "pulled1": pulled1,
    }
    if pulled0 == pulled1:
        terminal = terminal_of(pulled0)
        return PatternAnalysis(
            "B", True, idx0, idx1, terminal,
            reason=f"Puxados iguais ({pulled0}) — terminal {terminal}.",
            metadata={**base_metadata, "pulled_equal": True},
        )

    neighbors0 = wheel_neighbors(pulled0)
    neighbors1 = wheel_neighbors(pulled1)
    terminals0 = sorted(set(terminal_of(value) for value in neighbors0))
    terminals1 = sorted(set(terminal_of(value) for value in neighbors1))
    common = sorted(set(terminals0).intersection(terminals1))
    metadata = {
        **base_metadata,
        "pulled_equal": False,
        "neighbors0": list(neighbors0),
        "neighbors1": list(neighbors1),
        "terminals0": terminals0,
        "terminals1": terminals1,
        "common_terminals": common,
    }
    if not common:
        return PatternAnalysis(
            "B", False, idx0, idx1,
            reason="Nenhum terminal em comum entre os vizinhos dos puxados.",
            metadata=metadata,
        )
    # O HTML escolhe o primeiro comum ordenado no Motor B, mesmo quando há mais de um.
    terminal = common[0]
    return PatternAnalysis(
        "B", True, idx0, idx1, terminal,
        reason=f"Terminal em comum entre os puxados: {terminal}.",
        metadata=metadata,
    )


def detect_variant(variant: str | VariantSpec, history: Sequence[int]) -> SignalCandidate | None:
    spec = get_variant(variant) if isinstance(variant, str) else variant
    if not history:
        return None
    activation_number = _number(history[0])

    if spec.motor == "A":
        analysis_a = analyze_motor_a(history)
        if not analysis_a.valid or analysis_a.terminal is None:
            return None
        targets = compute_terminal_targets(
            analysis_a.terminal,
            with_neighbors=spec.coverage == "vizinhos",
        )
        return SignalCandidate(
            spec.slug, targets, analysis_a.terminal, None, analysis_a, None, activation_number,
        )

    if spec.motor == "B":
        analysis_b = analyze_motor_b(history)
        if not analysis_b.valid or analysis_b.terminal is None:
            return None
        targets = compute_terminal_targets(
            analysis_b.terminal,
            with_neighbors=spec.coverage == "vizinhos",
        )
        return SignalCandidate(
            spec.slug, targets, None, analysis_b.terminal, None, analysis_b, activation_number,
        )

    analysis_a = analyze_motor_a(history)
    analysis_b = analyze_motor_b(history)
    if (
        not analysis_a.valid
        or not analysis_b.valid
        or analysis_a.terminal is None
        or analysis_b.terminal is None
    ):
        return None
    equal = analysis_a.terminal == analysis_b.terminal
    if spec.relation == "equal" and not equal:
        return None
    if spec.relation == "different" and equal:
        return None
    targets = compute_cross_targets(analysis_a.terminal, analysis_b.terminal)
    return SignalCandidate(
        spec.slug,
        targets,
        analysis_a.terminal,
        analysis_b.terminal,
        analysis_a,
        analysis_b,
        activation_number,
    )
