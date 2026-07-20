"""Catalogo versionado das estrategias de gatilho orbital."""

from __future__ import annotations

from dataclasses import asdict, dataclass


TRIGGER_ENGINE_VERSION = "orbit_triggers_v1"
DEFAULT_MAX_ATTEMPTS = 5


@dataclass(frozen=True, slots=True)
class TriggerStrategySpec:
    slug: str
    name: str
    short_name: str
    summary: str
    activation_rule: str
    entry_rule: str
    max_attempts: int = DEFAULT_MAX_ATTEMPTS

    def as_payload(self) -> dict[str, object]:
        return asdict(self)


STRATEGIES: tuple[TriggerStrategySpec, ...] = (
    TriggerStrategySpec(
        slug="green-primeira",
        name="Modelo Green de Primeira",
        short_name="Green de Primeira",
        summary="Reentra depois que uma sugestão paga no primeiro giro.",
        activation_rule=(
            "A sugestão anterior precisa acertar na primeira tentativa; um giro adicional "
            "é aguardado antes de congelar a nova sugestão."
        ),
        entry_rule="Top 9 da sugestão gerada depois do giro de espera.",
    ),
    TriggerStrategySpec(
        slug="allan",
        name="Modelo Allan",
        short_name="Allan",
        summary="Mede toda sugestão com proteção física dos alvos.",
        activation_rule="Toda nova sugestão orbital ativa uma verificação.",
        entry_rule="Top 9 com um vizinho físico de cada lado de cada número.",
    ),
    TriggerStrategySpec(
        slug="inception",
        name="Modelo Inception",
        short_name="Inception",
        summary="Ativa o Top 9 depois de seis ausências quando o pivô mais recente é zero.",
        activation_rule=(
            "O número mais recente deve ser 0 e nenhum número do Top 9 original pode "
            "aparecer nos seis giros seguintes."
        ),
        entry_rule="Top 9 original, a partir do setimo giro posterior ao zero.",
    ),
    TriggerStrategySpec(
        slug="inception-primeiros-4",
        name="Inception · Primeiros 4",
        short_name="Inception 4",
        summary="Variação que acompanha somente os quatro primeiros alvos.",
        activation_rule=(
            "O número mais recente deve ser 0 e nenhum dos quatro primeiros alvos "
            "pode aparecer nos seis giros seguintes."
        ),
        entry_rule="Quatro primeiros alvos com um vizinho físico de cada lado.",
    ),
    TriggerStrategySpec(
        slug="interrompimento",
        name="Verificacao de Interrompimento",
        short_name="Interrompimento",
        summary="Detecta a quebra de uma sugestão que vinha pagando em até quatro giros.",
        activation_rule=(
            "A sugestão precisa registrar três pagamentos com intervalos máximos de "
            "quatro giros e depois completar cinco giros sem pagar."
        ),
        entry_rule="Top 9 atual congelado no quinto giro sem pagamento.",
    ),
    TriggerStrategySpec(
        slug="distancia",
        name="Modelo de Distancia",
        short_name="Distancia",
        summary="Reutiliza uma sugestão respeitando a distância de seu primeiro pagamento.",
        activation_rule=(
            "Quando a sugestão paga pela primeira vez na distância D, o monitor aguarda "
            "D menos um giros completos."
        ),
        entry_rule="Mesmo Top 9 da sugestão original.",
    ),
    TriggerStrategySpec(
        slug="ryan",
        name="Modelo Ryan",
        short_name="Ryan",
        summary="Cruza confluência, vizinhos dos pivôs restantes e famílias terminais.",
        activation_rule=(
            "Exatamente um dos três pivôs deve estar no Top 9; os outros dois geram "
            "vizinhos cujas famílias de último dígito são cruzadas com a sugestão."
        ),
        entry_rule=(
            "Candidatos terminais encontrados no Top 9, com dois vizinhos físicos de "
            "cada lado; de um a quatro candidatos centrais."
        ),
    ),
)

_BY_SLUG = {strategy.slug: strategy for strategy in STRATEGIES}


def get_strategy(slug: str) -> TriggerStrategySpec:
    try:
        return _BY_SLUG[str(slug)]
    except KeyError as exc:
        raise ValueError(f"estrategia de gatilho desconhecida: {slug}") from exc
