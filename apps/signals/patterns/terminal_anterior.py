from datetime import datetime

from helpers.utils.filters import get_neighbords, get_terminal, get_numbers_by_terminal, is_consecutive, soma_digitos
from helpers.utils.get_figure import get_figure


def _build_signal(*, roulette: dict, numbers: list[int], trigger: int, target: int, bet: list[int], pattern: str) -> dict:
    created_at = int(datetime.now().timestamp())

    return {
        "roulette_id": roulette["slug"],
        "roulette_name": roulette["name"],
        "roulette_url": roulette["url"],
        "pattern": pattern,
        "triggers": trigger,
        "targets": [*target],
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

def process_roulette(roulette, numbers) :

    confirm = get_terminal(numbers[2])

    t0_c = get_terminal(numbers[0])
    t1_c = get_terminal(numbers[1])
    t2_c = get_terminal(numbers[2])

    soma_0 = soma_digitos(numbers[0])
    soma_1 = soma_digitos(numbers[1])
    soma_2 = soma_digitos(numbers[2])
    soma_t3 = soma_digitos(numbers[5])


    t1 = get_terminal(numbers[3])
    t2 = get_terminal(numbers[4])
    t3 = get_terminal(numbers[5])
    t4 = get_terminal(numbers[6])
    t5 = get_terminal(numbers[7])
    t6 = get_terminal(numbers[8])
    t7 = get_terminal(numbers[9])


    if soma_t3 == t3 :
        return None
    
    if soma_2 == t1 :
        return None

    if(t1 == t2) :

        if t1 == 0 :
            return None

        terminal_target = get_terminal(t1 - 1)
        

        numbers_target = get_numbers_by_terminal(terminal_target)
        numbers_protect = get_numbers_by_terminal(t3)

        figuras = get_figure(terminal_target)
        
        vizinhos_list = [m for n in numbers_target for m in get_neighbords(n)] 

        bet = []

        bet.extend(vizinhos_list)
        #bet.extend(figuras)
        bet.extend(numbers_target)
        #bet.extend(numbers_protect)



        pagou_antes = len(set(numbers[1:8]) & set(bet))
        pagou_antes_zero = len(set(numbers[1:4]) & set([0]))
        

        pagou_depois = len(set(numbers[0:2]) & set(bet))

   
        
        if pagou_antes_zero :
            return None
        
        if confirm == t1 :
            return None
        
        if t1 == t3 :
            return None
        
        if t3 == t4 :
            return None
        

        if t1_c == t0_c :
            return None
        
        if t1_c == t2_c :
            return None
        
        if t4 == t5 :
            return None
        
        if t5 == t6 :
            return None
        
        if t2_c == t3 :
            return None
        
        if  t1 in [t0_c, t1_c, t2_c, t3, t4, t5] :
            return None 

        if is_consecutive(t2_c, t3) :
            return None


        if is_consecutive(t2, t3) :
            return None
        
        if is_consecutive(numbers[5], numbers[6]) :
            return None

        if is_consecutive(t1, t2_c) :
            return None
        
        if is_consecutive(t1_c,  t2_c) :
            return None
        
        if is_consecutive(numbers[1], numbers[2]) :
            return None
        
        if is_consecutive(numbers[4], numbers[5]) :
            return None
        
        if is_consecutive(numbers[0], numbers[1]) :
            return None


        if(pagou_antes) :
            
            
            bet.insert(0, numbers[2])
            bet.insert(0,0)


            bet = sorted(set(bet));


            return _build_signal(
                    roulette=roulette,
                    numbers=numbers,
                    trigger=numbers[0],
                    target=[t1-1],
                    bet=bet,
                    pattern=f"TERMINAL-ANTERIOR-{pagou_antes}",
                )

      


