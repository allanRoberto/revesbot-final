from helpers.utils.get_neighbords import get_neighbords
from helpers.utils.filters import (is_consecutive, appears_in_slice)

def soma_digitos(numero) :
    if 10 <= numero <= 99:
        soma = int(str(numero)[0]) + int(str(numero)[1])
        return soma
    else:
       return numero

def process_roulette(roulette, numbers) :
    idxs = (0, 1, 2, 3)
    p0, p1, p2, p3 = [numbers[i] for i in idxs] 

    if(p1 == 33 or p1 == 22 or p1 == 11) :
        
        neighbords11 = get_neighbords(11)
        neighbords22 = get_neighbords(22)
        neighbords33 = get_neighbords(33)

        bet = [11, 22, 33, *neighbords11, *neighbords22, *neighbords33]
        bet.insert(0,0)


        cancelled_numbers = [1, 10, 19, 28, 2, 11, 20, 29, 3, 12, 21, 20]

        if p0 in cancelled_numbers :
            return None

        count = soma_digitos(p0);
        
        if(count < 4) : 
            return None
        
        if(p0 == 11 or p0 == 22 or p0 == 33) :
            return None
        
        if(p2 == 11 or p2 == 22 or p2 == 33) :
            return None
        
        if(p3 == 11 or p3 == 22 or p3 == 33) :
            return None
        
        bet = sorted(set(bet))

        if(appears_in_slice(p1, numbers[2:10], 0,5)) :
            return None
        
        if(appears_in_slice(0, numbers[2:10], 0, 5)) :
            return None


        check0 = int(p0) % 10
        check1 = int(p1) % 10
        check2 = int(p2) % 10
        check3 = int(p3) % 10

        if(is_consecutive(check0, check1)) :
            return None
        
        if(is_consecutive(check0, check2)) :
            return None
        
        if(is_consecutive(check1, check2)) :
            return None
        
        if(is_consecutive(check2, check3)) :
            return None
        
        if(check0 == check1) :
            return None

        if(check0 == check2) :
            return None


        if(check1 == check2) :
            return None
        
        if(check2 == check3) :
            return None
        
        
        

        return {
            "roulette_id": roulette['slug'],
            "roulette_name" : roulette["name"],
            "roulette_url" : roulette["url"],
            "pattern" : "TERMINAL_CONTAGEM",
            "triggers":p1,
            "targets":count,
            "bets":bet,
            "passed_spins" : 0,
            "spins_required" : count,
                "spins_count": count,
            "snapshot":numbers[:50],
            "status":"pending",
            "message" : "Gatilho identificado"
        }
    
    else :
        return None
