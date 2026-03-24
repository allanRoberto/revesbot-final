from __future__ import annotations

from datetime import datetime

from helpers.utils.filters import get_terminal


GROUP_TERMINALS = {
    "147": {1, 4, 7},
    "258": {2, 5, 8},
    "0369": {0, 3, 6, 9},
}


def _find_previous_single_digit(numbers: list[int]) -> tuple[int, int] | None:
    for index, number in enumerate(numbers[2:], start=2):
        if 1 <= number <= 9:
            return index, number
    return None


def _get_group_name(terminal: int) -> str | None:
    for group_name, terminals in GROUP_TERMINALS.items():
        if terminal in terminals:
            return group_name
    return None


def _build_group_bets(group_name: str) -> list[int]:
    terminals = GROUP_TERMINALS[group_name]
    return [number for number in range(37) if get_terminal(number) in terminals]


def process_roulette(roulette, numbers):
    if len(numbers) < 3:
        return None

    trigger_number = numbers[1]
    if trigger_number < 1 or trigger_number > 9:
        return None

    previous_match = _find_previous_single_digit(numbers)
    if previous_match is None:
        return None
    previous_index, previous_single_digit = previous_match

    total = trigger_number + previous_single_digit
    terminal = get_terminal(total)
    group_name = _get_group_name(terminal)
    if group_name is None:
        return None

    bets = _build_group_bets(group_name)
    front_number = numbers[0]

    if 1 <= front_number <= 9:
        return None

    if front_number in bets:
        return None

    between_numbers = numbers[2:previous_index]
    if any(number in bets for number in between_numbers):
        return None

    created_at = int(datetime.now().timestamp())

    return {
        "roulette_id": roulette["slug"],
        "roulette_name": roulette["name"],
        "roulette_url": roulette["url"],
        "pattern": "SOMA_TERMINAL_GRUPO",
        "triggers": [trigger_number, previous_single_digit],
        "targets": bets,
        "bets": bets,
        "passed_spins": 0,
        "spins_required": 0,
        "spins_count": 0,
        "gales": 10,
        "score": 0,
        "snapshot": numbers[:200],
        "status": "processing",
        "message": (
            f"Soma {trigger_number}+{previous_single_digit}={total} "
            f"-> terminal {terminal} -> grupo {group_name}"
        ),
        "tags": [
            "soma_terminal_grupo",
            f"grupo_{group_name}",
            f"terminal_{terminal}",
        ],
        "temp_state": None,
        "created_at": created_at,
        "timestamp": created_at,
    }
