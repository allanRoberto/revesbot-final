"""Catálogo versionado das variações monitoradas."""

from __future__ import annotations

from dataclasses import asdict, dataclass


ENGINE_VERSION = "terminal_signals_v2"
COLLECTION_HORIZON = 10
DEFAULT_MAX_ATTEMPTS = COLLECTION_HORIZON
DEFAULT_SIMULATION_ATTEMPTS = 2
DEFAULT_ATTEMPT_STAKES = (1.0, 1.5, 1.5, 1.5, 1.5, 1.5, 1.5, 1.5, 1.5, 1.5)


@dataclass(frozen=True, slots=True)
class VariantSpec:
    slug: str
    name: str
    short_name: str
    motor: str
    coverage: str
    relation: str | None
    summary: str
    max_attempts: int = DEFAULT_MAX_ATTEMPTS

    def as_payload(self) -> dict[str, object]:
        return asdict(self)


VARIANTS: tuple[VariantSpec, ...] = (
    VariantSpec(
        slug="motor-a-seco",
        name="Motor A · Terminais Secos",
        short_name="A Seco",
        motor="A",
        coverage="seco",
        relation=None,
        summary="Terminal único em comum entre os vizinhos dos dois últimos números.",
    ),
    VariantSpec(
        slug="motor-a-vizinhos",
        name="Motor A · Terminais + Vizinhos",
        short_name="A + Vizinhos",
        motor="A",
        coverage="vizinhos",
        relation=None,
        summary="Motor A com expansão de um vizinho físico para cada número terminal.",
    ),
    VariantSpec(
        slug="motor-b-seco",
        name="Motor B · Terminais Secos",
        short_name="B Seco",
        motor="B",
        coverage="seco",
        relation=None,
        summary="Terminal derivado dos puxados históricos dos dois últimos números.",
    ),
    VariantSpec(
        slug="motor-b-vizinhos",
        name="Motor B · Terminais + Vizinhos",
        short_name="B + Vizinhos",
        motor="B",
        coverage="vizinhos",
        relation=None,
        summary="Motor B com expansão de um vizinho físico para cada número terminal.",
    ),
    VariantSpec(
        slug="cruzado",
        name="Gatilho Cruzado · A ≠ B",
        short_name="Cruzado",
        motor="AB",
        coverage="cruzado",
        relation="different",
        summary="Motor A e Motor B válidos no mesmo giro, apontando terminais diferentes.",
    ),
    VariantSpec(
        slug="gemeos",
        name="Motores Gêmeos · A = B",
        short_name="Gêmeos",
        motor="AB",
        coverage="cruzado",
        relation="equal",
        summary="Motor A e Motor B válidos no mesmo giro, apontando o mesmo terminal.",
    ),
)

_BY_SLUG = {variant.slug: variant for variant in VARIANTS}


def get_variant(slug: str) -> VariantSpec:
    try:
        return _BY_SLUG[str(slug)]
    except KeyError as exc:
        raise ValueError(f"variação de terminal desconhecida: {slug}") from exc
