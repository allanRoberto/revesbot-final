from core.redis import save_signal
from helpers.utils.get_neighbords import get_neighbords
from helpers.utils.get_mirror import get_mirror
from typing import List, Optional
from signal_types import Signal

def process_roulette(roulette: List[int], results) -> Optional[Signal]:

    if len(results) < 4:  
        return None
    
    pos0, pos1, pos2, pos3 = results[6], results[7], results[8], results[9]

    # Condições principais
    if (pos1 == 2 * pos2 or pos2 == 2 * pos1) and not (
        pos0 == 2 * pos1 or pos0 == 2 * pos2 or pos3 == 2 * pos1 or pos3 == 2 * pos2 or
        pos1 == 2 * pos0 or pos2 == 2 * pos0 or pos1 == 2 * pos3 or pos2 == 2 * pos3
    ):
        # Calcular o chamador
        if pos1 == 2 * pos2:
            chamador = 2 * pos1 
        elif pos2 == 2 * pos1:
            if pos1 % 2 == 0:
                chamador = pos1 // 2  # Divisão inteira para evitar valores não inteiros
            else:
                return None    
        else:
            return None  # Caso inesperado, retorna None
        
        # Verifica se o chamador é válido (não pode ser maior que 36)
        if chamador > 36:
            return None

        if chamador == 0 or pos3 ==0:
            return None

        alvo = [pos3] + get_neighbords(pos3)  # Alvo é a posição 3 com seus vizinhos

        pos3_neighbords = get_neighbords(3)
        
        #Determina as proteções
        mirror = get_mirror(pos3)
        protecao = [pos0] + get_neighbords(pos0)
        
        if mirror is not None:  
            protecao.extend(mirror)  

        bets = sorted(set(alvo + protecao))

        return {
            "roulette_id": roulette["slug"],
            "roulette_name" : roulette["name"],
            "roulette_url" : roulette["url"],
            "triggers": [chamador],
            "targets": alvo,
            "bets": bets,
            "passed_spins" : 5,
            "snapshot": results[:8],
            "status": "pending",
            "pattern": "COMUNIDADE"
        }
    
        target = p2
        target_neihbords = get_neighbords(target)
        numbers_bet = [target, *target_neihbords, p1]
        mirror_list = [m for n in numbers_bet for m in get_mirror(n)]
        numbers_bet.extend(mirror_list)
        numbers_bet.insert(0, 0)
        numbers_bet = sorted(set(numbers_bet))

        mirror_triggers = get_mirror(p1)
        triggers = [p1, *mirror_triggers]

        return {
                "roulette_id":roulette['slug'],
                "roulette_name" : roulette["name"],
                "roulette_url" : roulette["url"],
                "pattern" : "PAGOU_ANTES",
                "triggers":triggers,
                "targets":[target],
                "bets":numbers_bet,
                "passed_spins" : 0,
                "spins_required" : 12,
                "snapshot":numbers[:8],
                "status":"pending",
        }
    
    

    return None




