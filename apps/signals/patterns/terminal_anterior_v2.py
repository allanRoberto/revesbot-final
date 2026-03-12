from datetime import datetime

from helpers.utils.filters import (
    get_neighbords,
    get_numbers_by_terminal,
    get_terminal,
    soma_digitos,
)
from helpers.utils.get_mirror import get_mirror


WINDOW_CHECK = 4


def _represents_terminal(number: int, terminal: int) -> bool:
    if get_terminal(number) == terminal:
        return True
    if soma_digitos(number) == terminal:
        return True
    if terminal in get_mirror(number):
        return True
    return False


def _build_signal(*, roulette: dict, numbers: list[int], trigger: int, target_terminal: int, bet: list[int]) -> dict:
    created_at = int(datetime.now().timestamp())

    return {
        "roulette_id": roulette["slug"],
        "roulette_name": roulette["name"],
        "roulette_url": roulette["url"],
        "pattern": "TERMINAL-ANTERIOR-V2",
        "triggers": trigger,
        "targets": [target_terminal],
        "bets": bet,
        "passed_spins": 0,
        "spins_required": 0,
        "spins_count": 0,
        "gales": 4,
        "score": 0,
        "snapshot": numbers[:200],
        "status": "processing",
        "message": "Gatilho encontrado! ",
        "tags": [],
        "temp_state": None,
        "created_at": created_at,
        "timestamp": created_at,
    }


def process_roulette(roulette, numbers):
    if len(numbers) < WINDOW_CHECK:
        return None

    n0 = numbers[0]
    n1 = numbers[1]

    t0 = get_terminal(n0)
    t1 = get_terminal(n1)

    if t0 != t1:
        return None

    if t0 == 0:
        return None

    recent = numbers[:WINDOW_CHECK]
    masked_count = sum(1 for n in recent if _represents_terminal(n, t0))
    if masked_count != 2:
        return None

    target_terminal = (t0 - 1) % 10
    numbers_target = get_numbers_by_terminal(target_terminal)

    bet_set = set(numbers_target)
    for n in numbers_target:
        bet_set.update(get_neighbords(n))

    bet = sorted(bet_set)

    return _build_signal(
        roulette=roulette,
        numbers=numbers,
        trigger=n0,
        target_terminal=target_terminal,
        bet=bet,
    )
