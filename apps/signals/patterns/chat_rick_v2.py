from patterns.chat_rick import RouletteAnalyzer
from datetime import datetime

class RouletteState:
    def __init__(self) -> None:
        self.since_last: int = 2


_states = {}


def _get_state(slug: str) -> RouletteState:
    if slug not in _states:
        _states[slug] = RouletteState()
    return _states[slug]

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
        "gales": 3,
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



    analyzer = RouletteAnalyzer(numbers)
    strategy = analyzer.generate_strategy()

    state = _get_state(roulette["slug"])
    state.since_last += 1
    if state.since_last < 3:
        return None
    state.since_last = 0

    return _build_signal(
        roulette=roulette,
        numbers=numbers,
        trigger=strategy["gatilhos_X"],
        target_a=strategy["entrada_cheia_Y_12"],
        bet=strategy["entrada_cheia_Y_12"],
        pattern="CHATGPT",
    )


