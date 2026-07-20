"""Definicoes versionadas usadas exclusivamente pelo motor orbital.

As relacoes legadas do repositorio possuem divergencias. Este modulo segue a
convencao confirmada pelo usuario e nao altera o comportamento dos motores
existentes.
"""

from __future__ import annotations

from types import MappingProxyType

SCHEMA_VERSION = "orbit-relations-v1"
NUMBER_MIN = 0
NUMBER_MAX = 36
ROULETTE_NUMBERS = tuple(range(NUMBER_MIN, NUMBER_MAX + 1))

# Ordem canonica da roda europeia, com indice zero no proprio numero zero.
EUROPEAN_WHEEL = (
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8,
    23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12,
    35, 3, 26,
)
WHEEL_INDEX = MappingProxyType({number: index for index, number in enumerate(EUROPEAN_WHEEL)})

RED_NUMBERS = frozenset({
    1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36,
})
BLACK_NUMBERS = frozenset(set(ROULETTE_NUMBERS) - RED_NUMBERS - {0})

VOISINS_ZERO = frozenset({22, 18, 29, 7, 28, 12, 35, 3, 26, 0, 32, 15, 19, 4, 21, 2, 25})
TIERS_CYLINDRE = frozenset({27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33})
ORPHELINS = frozenset({1, 20, 14, 31, 9, 17, 34, 6})

# Lista exata fornecida pelo usuario. 14 <-> 34 nao faz parte desta versao.
MIRROR_PAIRS = (
    (1, 10),
    (2, 20),
    (3, 30),
    (6, 9),
    (12, 21),
    (13, 31),
    (16, 19),
    (23, 32),
    (26, 29),
)
MIRRORS = MappingProxyType({
    number: mirror
    for left, right in MIRROR_PAIRS
    for number, mirror in ((left, right), (right, left))
})

# Quatro numeros por familia; zero fica explicitamente fora das familias.
DIGIT_SUM_GROUPS = MappingProxyType({
    root: tuple(root + (9 * offset) for offset in range(4))
    for root in range(1, 10)
})
DIGIT_SUM_MEMBERSHIP = MappingProxyType({
    number: (root, position + 1)
    for root, members in DIGIT_SUM_GROUPS.items()
    for position, number in enumerate(members)
})

TERMINAL_FAMILIES = MappingProxyType({
    "147": frozenset({1, 4, 7}),
    "258": frozenset({2, 5, 8}),
    "369": frozenset({3, 6, 9}),
})

TERMINAL_POSITION = MappingProxyType({
    1: ("147", 1), 4: ("147", 2), 7: ("147", 3),
    2: ("258", 1), 5: ("258", 2), 8: ("258", 3),
    3: ("369", 1), 6: ("369", 2), 9: ("369", 3),
})


def validate_number(number: int) -> int:
    """Normaliza e valida um numero de roleta sem aceitar booleanos."""
    if isinstance(number, bool):
        raise ValueError("booleano nao e numero de roleta")
    try:
        value = int(number)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"numero de roleta invalido: {number!r}") from exc
    if not NUMBER_MIN <= value <= NUMBER_MAX:
        raise ValueError(f"numero fora do intervalo 0..36: {value}")
    return value
