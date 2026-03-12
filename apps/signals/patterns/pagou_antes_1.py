from helpers.utils.filters import first_index_after

from helpers.utils.get_neighbords import get_neighbords
from helpers.utils.get_mirror import get_mirror

def process_roulette(roulette, numbers) :

    if (len(numbers) < 50) : 
        return None
    

    idxs = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9)

    p0, p1, p2, p3, p4, p5, p6, p7, p8, p9 = [numbers[i] for i in idxs] 

    if (p4 in numbers[:12]) :
        return None

    isp4 = first_index_after(numbers, p4, 12)

    check1 = numbers[isp4 + 1]

    p3_neighbords = get_neighbords(p3)

    if(check1 in p3_neighbords or check1 == -3) :

        target = p5
        target_neihbords = get_neighbords(target)
        numbers_bet = [target, *target_neihbords, p5]
        mirror_list = [m for n in numbers_bet for m in get_mirror(n)]
        numbers_bet.extend(mirror_list)
        numbers_bet.insert(0, 0)
        numbers_bet = sorted(set(numbers_bet))
        
        mirror_triggers = get_mirror(p4)
        triggers = [p4, *mirror_triggers]


        return {
                "roulette_id":roulette['slug'],
                "roulette_name" : roulette["name"],
                "roulette_url" : roulette["url"],
                "pattern" : "PAGOU_ANTES",
                "triggers":[triggers],
                "targets":[target],
                "bets":numbers_bet,
                "passed_spins" : 0,
                "spins_required" : 0,
                "spins_count": 0,
                "snapshot":numbers[:50],
                "status":"waiting",
                "message" : "Gatilho encontrado!"
        }



    return None