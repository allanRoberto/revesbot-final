from __future__ import annotations

from collections.abc import Iterable


EUROPEAN_WHEEL: tuple[int, ...] = (
    0,
    32,
    15,
    19,
    4,
    21,
    2,
    25,
    17,
    34,
    6,
    27,
    13,
    36,
    11,
    30,
    8,
    23,
    10,
    5,
    24,
    16,
    33,
    1,
    20,
    14,
    31,
    9,
    22,
    18,
    29,
    7,
    28,
    12,
    35,
    3,
    26,
)
_INDEX = {number: index for index, number in enumerate(EUROPEAN_WHEEL)}


def validate_number(value: object) -> int:
    if isinstance(value, (bool, float)):
        raise ValueError("resultado deve ser um inteiro")
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"resultado invalido: {value!r}") from exc
    if number not in _INDEX:
        raise ValueError(f"resultado fora do intervalo 0..36: {value!r}")
    return number


def neighbors(number: int, span: int = 1) -> tuple[int, ...]:
    number = validate_number(number)
    if span < 0 or span > 18:
        raise ValueError("span deve estar entre 0 e 18")
    index = _INDEX[number]
    result: list[int] = []
    for distance in range(1, span + 1):
        result.append(EUROPEAN_WHEEL[(index - distance) % len(EUROPEAN_WHEEL)])
        result.append(EUROPEAN_WHEEL[(index + distance) % len(EUROPEAN_WHEEL)])
    return tuple(result)


def mirror_map(pairs: Iterable[tuple[int, int]]) -> dict[int, int]:
    result: dict[int, int] = {}
    for left, right in pairs:
        left = validate_number(left)
        right = validate_number(right)
        result[left] = right
        result[right] = left
    return result


def coverage_for_target(
    target: int,
    *,
    span: int = 1,
    mirrors: Iterable[tuple[int, int]] = (),
) -> tuple[int, ...]:
    """Return exact, physical neighbours, then configured mirror."""

    exact = validate_number(target)
    values = [exact, *neighbors(exact, span)]
    mirrored = mirror_map(mirrors).get(exact)
    if mirrored is not None:
        values.append(mirrored)
    return tuple(dict.fromkeys(values))


def classify_payment(
    result: int,
    targets: Iterable[int],
    *,
    span: int = 1,
    mirrors: Iterable[tuple[int, int]] = (),
) -> tuple[str, int] | None:
    """Classify once, with deterministic exact > neighbour > mirror priority."""

    value = validate_number(result)
    safe_targets = tuple(dict.fromkeys(validate_number(target) for target in targets))
    if value in safe_targets:
        return "exact", value

    for target in safe_targets:
        if value in neighbors(target, span):
            return "neighbor", target
    configured_mirrors = mirror_map(mirrors)
    for target in safe_targets:
        if configured_mirrors.get(target) == value:
            return "mirror", target
    return None
