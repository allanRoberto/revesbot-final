from helpers.utils.filters import (
    first_index_after,
    is_consecutive,
    is_skipped_sequence,
    any_consecutive,
    has_same_terminal,
    is_repetition,
    is_check_neigbor_two_numbers,
    appears_in_slice,
)

from helpers.utils.get_neighbords import get_neighbords
from helpers.utils.get_mirror import get_mirror

debug = False

def process_roulette(roulette, numbers):

    idxs = (0, 1, 2, 3, 4, 5, 6)
    p0, p1, p2, p3, p4, p5, p6 = [numbers[i] for i in idxs] # p2 : Base para o alvo | p3 e p4 Sequência | p5 : Gatilho

    mirror_p5 = get_mirror(p5)

    if(p4 == mirror_p5) : 
        return None
    
    if(is_consecutive(p1, p2)) : 
         return None
    
    if(p4 == p5) : 
        return None
    
    if(p3 == p5) : 
        return None
    
    if(p3 == 0 or p4 == 0 or p5 == 0) : 
        return None
    


    if(p2  == 0 or p2 == 36 or p4 == 0) :
        return None

    if(is_consecutive(p5, p6)) : 
        return None
    
    if(is_consecutive(p4, p5)) :
            return None
    
    if(is_consecutive(p2, p3)) : 
            return None
    
    if(is_consecutive(p3, p4) or is_skipped_sequence(p3, p4)) :
        target1  = p2 - 1
        target2  = p2 + 1

        if(target1 == 0 or target2 == 0 or p2 == 0) : 
            return None
        
        if(p5 == target1 or p5 == target2) : 
             return None


        p5_neignbords = get_neighbords(p5)

        bet = [*p5_neignbords, p5]

        bet.insert(0,0)
                


        return {
                "roulette_id":roulette['slug'],
                "roulette_name" : roulette["name"],
                "roulette_url" : roulette["url"],
                "pattern" : "SEQUENCIA_INVERTIDO",
                "triggers":[target1, target2],
                "targets":p5,
                "bets":bet,
                "passed_spins" : 0,
                "spins_required" : 5,
                "snapshot":numbers[:50],
                "status":"waiting",
        }

        

