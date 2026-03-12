from helpers.utils.filters import (
    is_consecutive,
    is_repetition_check,
    same_terminal
)

from helpers.utils.get_neighbords import get_neighbords
from helpers.utils.get_mirror import get_mirror

debug = False

def process_roulette(roulette, numbers):

    idxs = (0, 1, 2, 3)
    p0, p1, p2, p3 = [numbers[i] for i in idxs] #  p0 e p1 Sequência | p5 : Verificação


    check1 = p0
    check2 = p1
    trigger = p2

    

    if(check1 == 16 or check1 == 17 or check1 == 18 or check1 == 19 or check1 == 0 or check2 == 16 or check2 == 17 or check2 == 18 or check2 == 19 or check2 == 0) : 
         return None

    if(same_terminal(trigger, p3)) : 
         return None


    if(is_repetition_check(trigger, check2)) : 
         return None 
    
    
    if(check1 == trigger or check2 == trigger) : 
         return None
    
    if(is_consecutive(check1, check2)) :
        
        target1_neighbords = get_neighbords(16)
        target2_neighbords = get_neighbords(17)
        target3_neighbords = get_neighbords(18)

        bet = [16, 17, 18, *target1_neighbords, *target2_neighbords, *target3_neighbords]
    

        bet.insert(0, 0)
        bet.insert(0, 19)

        bet = sorted(set(bet))

        paid = check_inversion(numbers[:10], bet)

        if paid is not None:
             return None


        return {
                "roulette_id": roulette['slug'],
                "roulette_name" : roulette["name"],
                "roulette_url" : roulette["url"],
                "pattern" : "SEQUENCIA_IMEDIATA",
                "triggers":[check1, check2],
                "targets":[16, 17, 18, 19],
                "bets":bet,
                "passed_spins" : 0,
                "spins_required" : 2,
                "snapshot":numbers[:50],
                "status":"processing",
        }

def check_inversion(history, bets):
        """
        Verifica se algum número da aposta ocorreu na janela de inversão
        imediatamente antes do gatilho (últimos PRE_WINDOW_SIZE spins),
        usando signal.snapshot.
        Retorna o número da aposta paga ou None.
        """
        # snapshot[0] é o spin mais recente (o gatilho em _process_spin),
        # então pegamos os PRE_WINDOW_SIZE spins seguintes: índices 1..PRE_WINDOW_SIZE
        nums = history

        # precisa ter ao menos PRE_WINDOW_SIZE+1 elementos (gatilho + janela)
        if len(nums) < 3 + 1:
            return None

        # elementos imediatamente antes do gatilho
        window = nums[1 : 2 + 1]

        # verifica interseção de sets para eficiência
        bets_set = set(bets or [])
        common = bets_set.intersection(window)

        print(common, "PAGOU INVERTIDO")
        return next(iter(common)) if common else None

