from __future__ import annotations

from datetime import datetime


MAPA_CAVALOS_147 = [1, 4, 7, 14, 17, 21, 24, 27, 31, 34]
MAPA_CAVALOS_258 = [2, 5, 8, 12, 15, 18, 25, 28, 32, 35]
GATILHOS = {10, 20, 30}
INVALIDOS_DIRETOS = {10, 11, 20, 22, 30, 33}
DEFAULT_GALES = 4

_bootstrapped_slugs: set[str] = set()
_last_signatures: dict[str, tuple[int, ...]] = {}


def _history_signature(numbers: list[int]) -> tuple[int, ...]:
    return tuple(int(number) for number in numbers[:3])


def _should_skip_current_snapshot(slug: str, numbers: list[int]) -> bool:
    signature = _history_signature(numbers)
    previous_signature = _last_signatures.get(slug)
    _last_signatures[slug] = signature

    if previous_signature == signature:
        return True

    if slug not in _bootstrapped_slugs:
        _bootstrapped_slugs.add(slug)
        return True

    return False


def _obter_alvos(n_prev: int) -> dict | None:
    if not isinstance(n_prev, int):
        return None

    valor = n_prev

    while True:
        valor -= 36
        absoluto = abs(valor)

        if absoluto in INVALIDOS_DIRETOS:
            return None

        terminal = absoluto % 10
        if terminal in {1, 4, 7}:
            return {
                "grupo": "Absolu 1-4-7",
                "alvos": MAPA_CAVALOS_147 + [10, 0],
                "alvo_sub": "Protecao 10",
            }
        if terminal in {2, 5, 8}:
            return {
                "grupo": "Absolu 2-5-8",
                "alvos": MAPA_CAVALOS_258 + [20, 0],
                "alvo_sub": "Protecao 20",
            }
        if terminal in {3, 6, 9}:
            continue
        return None


def process_roulette(roulette, numbers):
    if len(numbers) < 2:
        return None

    slug = roulette["slug"]
    if _should_skip_current_snapshot(slug, numbers):
        return None

    gatilho = int(numbers[0])
    if gatilho not in GATILHOS:
        return None

    n_prev = int(numbers[1])
    if n_prev == 0 or n_prev == gatilho:
        return None

    alvos_dict = _obter_alvos(n_prev)
    if not alvos_dict:
        return None

    created_at = int(datetime.now().timestamp())
    grupo_slug = "147" if "1-4-7" in alvos_dict["grupo"] else "258"

    return {
        "roulette_id": slug,
        "roulette_name": roulette["name"],
        "roulette_url": roulette["url"],
        "pattern": "SUBTRACAO_API",
        "triggers": [gatilho],
        "targets": alvos_dict["alvos"],
        "bets": alvos_dict["alvos"],
        "status": "processing",
        "gales": DEFAULT_GALES,
        "passed_spins": 0,
        "spins_required": 0,
        "snapshot": numbers[:500],
        "score": 0,
        "message": (
            f"Subtracao armada | gatilho {gatilho} | anterior {n_prev} | "
            f"{alvos_dict['grupo']} -> {alvos_dict['alvo_sub']}"
        ),
        "tags": [
            "subtracao_api",
            f"gatilho_{gatilho}",
            f"grupo_{grupo_slug}",
        ],
        "temp_state": {
            "gatilho": gatilho,
            "n_prev": n_prev,
            "grupo": alvos_dict["grupo"],
            "alvo_sub": alvos_dict["alvo_sub"],
            "entradas_feitas": 0,
            "pausa_restante": 0,
            "ref_escada": gatilho,
            "historico_pausas": [],
            "resultados_girados": [],
            "entry_armed": False,
            "current_entry": None,
            "current_bet_value": None,
        },
        "created_at": created_at,
        "timestamp": created_at,
    }
