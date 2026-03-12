from helpers.utils.filters import is_skipped_sequence

from datetime import datetime

def _build_signal(*, roulette: dict, numbers: list[int], trigger: int, target_a: list, bet: list[int], pattern: str) -> dict:
    created_at = int(datetime.now().timestamp())

    return {
        "roulette_id": roulette["slug"],
        "roulette_name": roulette["name"],
        "roulette_url": roulette["url"],
        "pattern": pattern,
        "triggers": trigger,
        "targets": [*target_a],
        "bets": bet,
        "passed_spins": 0,
        "spins_required": 0,
        "spins_count": 0,
        "gales": 2,
        "score": 0,
        "snapshot": numbers[:200],
        "status": "processing",
        "message": "Gatilho encontrado! ",
        "tags": [],
        "temp_state": None,
        "created_at": created_at,
        "timestamp": created_at,
    }


def process_roulette(roulette, numbers) :


    p0 = numbers[0]
    p1 = numbers[1]
    p2 = numbers[2]


    if is_skipped_sequence(p1, p2) :

        bet = [0, 3, 6, 9, 10, 13, 16, 19, 20, 23, 26, 29, 30, 33, 36]

        return _build_signal(
                roulette=roulette,
                numbers=numbers,
                trigger=numbers[0],
                target_a=bet,
                bet=[*bet],
                pattern="PATCHOKO_SEQUENCIA_PULADA_0369",
            )

