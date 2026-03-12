def process_roulette(roulette, numbers) : 

    if (len(numbers) < 10) :
        return None
    
    trigger = numbers[0]

    if(trigger == 22 or trigger == 33) : 

     
        
        bet = [1, 2, 4, 5, 6, 9, 13, 15, 16, 17, 19, 20, 21,23, 22, 25, 27, 28, 29, 31, 33, 34]

        bet.insert(0, 0)

        bet = sorted(set(bet))

        return {
            "roulette_id": roulette['slug'],
            "roulette_name" : roulette["name"],
            "roulette_url" : roulette["url"],
            "pattern" : "112 JOGADAS",
            "triggers":trigger,
            "targets":trigger,
            "bets":bet,
            "passed_spins" : 0,
            "spins_required" : 112,
            "spins_count": 112,
            "snapshot":numbers[:500],
            "status":"pending",
             "message" : "Gatilho identificado 112 jogadas"
    }
    else : 
        return None 