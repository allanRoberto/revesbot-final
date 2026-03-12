
from datetime import datetime
from patterns.puxados_core import build_prediction_from_history

from helpers.utils.filters import first_index_after


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
        "gales": 5,
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

    if len(numbers)  < 400 :
        return None
    
    base = numbers[0]

    state = _get_state(roulette["slug"])
    state.since_last += 1
    if state.since_last < 3:
        return None
    state.since_last = 0
    
    
    suggestion, _, _ = build_prediction_from_history(
            numbers,
            target=numbers[0],
            window=3,
            top_window=11,
            top_plus1=3,
        )
    


    indice1 = first_index_after(numbers, base - 1, 1)

    if  indice1 is None:
        print ("CANCELOU DEVIDO NAO BATER INDICE 1 ")
        return None
    
    if indice1 < 10 :
        return None
    
    start1 = indice1 - 1
    end1 = indice1 - 5
    
    target1 = numbers[end1:start1]

    indice2 = first_index_after(numbers, base + 1, 1)

    if indice2 is None:
        return None
    
    if indice2 < 10 :
        return None
    
    start2 = indice2 - 1
    end2 = indice2 - 5
    
    target2 = numbers[end2:start2]

    
    suggestion.insert(0,0)

    bet = sorted(set(suggestion))


    
    

    if bool(set(target1) & set(bet))  :

        if bool(set(target2) & set(bet)) :

            return _build_signal(
                roulette=roulette,
                numbers=numbers,
                trigger=numbers[0],
                target_a=suggestion,
                bet=[*bet],
                pattern="PUXADOS",
            )
        else :
            print (f"CANCELOU DEVIDO NAO BATER INDICE 2 {target1} - {base} - {target2} - {bet}")
    else :
        print (f"CANCELOU DEVIDO NAO BATER INDICE 1 {target1} - {base} - {target2} - {bet}")


