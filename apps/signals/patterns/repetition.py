from helpers.utils.filters import (
    first_index_after,
    is_consecutive,
    is_repetition_check,
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

    idxs = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9)
    p0, p1, p2, p3, p4, p5, p6, p7, p8, p9 = [numbers[i] for i in idxs] # p2 : Base para o alvo | p3 e p4 Sequência | p5 : Gatilho

    pos0 = p0
    pos1 = p1
    pos2 = p2
    target = p3
    check1 = p4
    check2 = p5
    trigger = p6
    pos7 = p7
    pos8 = p8
    pos9 = p9

    if(is_consecutive(trigger, pos7)) : 
         return None
    
    if(is_consecutive(pos8, pos9)) : 
         return None
    
    if(is_consecutive(pos0, pos1)) : 
         return None
    
    
    if(is_consecutive(check2, pos7)) : 
         return None
    
    if(is_consecutive(pos7, pos8)) : 
         return None
    
    if(is_repetition_check(trigger, pos7)) :
         return None
    
    if(pos1 == pos2) :
         return None
    
    if(is_repetition_check(trigger, target)) :
         return None
    
    
    if(pos7 == pos8) :
          return None
    
    if(is_consecutive(target, check1)) : 
         return None
    
    if(is_consecutive(pos2, target)) : 
         return None

    if(is_repetition_check(target, check1)) : 
         return None

    if(is_repetition_check(trigger, check2)) : 
         return None 
    
    if(is_repetition_check(target, check1)) : 
         return None
    
    if(is_repetition_check(check2, target)) :
         return None
    
    if(is_repetition_check(check1, target)) :
         return None
    
    if(is_repetition_check(pos2, pos7)) : 
         return None
    
    if(target == 0 or target == 36 or trigger == 0 or pos7 == 0 or check1 == 0 or check2 == 0) :
        return None

    if(is_consecutive(check1, target) or is_consecutive(check2, target)) : 
         return None
    
    if(check1 == trigger or check2 == trigger) : 
         return None
    
    if(is_consecutive(check1, check2) or is_skipped_sequence(check1, check2)) :
        
        if(is_consecutive(check1, check2)) :
        
            target1  =  target - 1
            target2  =  target + 1

        elif (is_skipped_sequence(check1, check2)) :

            target1  =  target - 2
            target2  =  target + 2

        if(target1 == 0 or target2 == 0) : 
            return None
        
        if(trigger == target1 or trigger == target2) : 
             return None
        
        if (is_consecutive(trigger, target1) or is_consecutive(trigger, target2)) :
             return None

        target1_neighbords = get_neighbords(target1)
        target2_neighbords = get_neighbords(target2)

        bet = [target1, target2, *target1_neighbords, *target2_neighbords]
        
        mirror_list = [m for n in bet for m in get_mirror(n)]

        bet.extend(mirror_list)

        bet.insert(0, 0)

        bet = sorted(set(bet))

        return {
                "roulette_id": roulette['slug'],
                "roulette_name" : roulette["name"],
                "roulette_url" : roulette["url"],
                "pattern" : "SEQUENCIA",
                "triggers":[trigger],
                "targets":[target1, target2],
                "bets":bet,
                "passed_spins" : 0,
                "spins_required" : 2,
                "snapshot":numbers[:50],
                "status":"pending",
        }

        
