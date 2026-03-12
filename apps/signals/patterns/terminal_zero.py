from helpers.utils.filters import first_index_after, get_terminal, get_numbers_by_terminal, get_neighbords
from datetime import datetime

def _build_signal(*, roulette: dict, numbers: list[int], trigger: int, target_a: list, bet: list[int], pattern: str, status : str) -> dict:
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
        "status": status,
        "message": "Gatilho encontrado! ",
        "tags": [],
        "temp_state": None,
        "created_at": created_at,
        "timestamp": created_at,
    }

def process_roulette(roulette, numbers) :

    base = numbers[5]
    print(numbers[0], roulette["slug"])
    

    indice1 =  first_index_after(numbers, base, 7) 
    indice2 =  first_index_after(numbers, base, indice1 + 1) 

    if indice1 is None :
        return None
    elif indice2 is None:
        return None
    
    after_zero_1 = numbers[indice1 - 1]
    after_zero_2 = numbers[indice2 - 1]

    terminal_after_zero_1 = get_terminal(after_zero_1)
    terminal_after_zero_2 = get_terminal(after_zero_2)

    bet = []

    if terminal_after_zero_1 == terminal_after_zero_2 :
        print("FORMOU GATILHO", roulette["slug"])

        base_numbers = get_numbers_by_terminal(terminal_after_zero_1)

        vizinhos_list = [m for n in base_numbers for m in get_neighbords(n)] 
        bet.extend(vizinhos_list)
        bet.extend(base_numbers)
 

        if terminal_after_zero_1 == 5 :
            bet.insert(0, 26)
        elif terminal_after_zero_1 == 9 :
            bet.insert(0, 32)
        elif terminal_after_zero_1 == 2 :
            bet.insert(0, 19)
        elif terminal_after_zero_1 == 6 :
            bet.insert(0, 35)

        bet.insert(0,0)

        if bet in numbers[0:4] :
            return None
        

        tem_comum = bool(set(numbers[1:4]) & set(bet))

        if tem_comum :

            return _build_signal(
                    roulette=roulette,
                    numbers=numbers,
                    trigger=numbers[0],
                    target_a=[terminal_after_zero_1],
                    bet=[*bet],
                    pattern="TERMINAL_PUXADO",
                    status="processing"
            )

