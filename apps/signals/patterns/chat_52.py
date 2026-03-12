def process_roulette(roulette, numbers) : 

    if (len(numbers) < 10) :
        return None
    
    trigger = numbers[0]

    if(trigger == 22 or trigger == 33) : 

     
        
        bet = [2, 4, 5, 6, 7, 8, 12, 9, 13, 16, 17, 19, 21, 34, 27, 22, 25,28, 29, 33]

        bet.insert(0, 0)

        bet = sorted(set(bet))

        return {
            "roulette_id": roulette['slug'],
            "roulette_name" : roulette["name"],
            "roulette_url" : roulette["url"],
            "pattern" : "SEQUENCIA",
            "triggers":trigger,
            "targets":trigger,
            "bets":bet,
            "passed_spins" : 0,
            "spins_required" : 26,
            "spins_count": 26,
            "snapshot":numbers[:150],
            "status":"pending",
            "message" : "Gatilho identificado 26 jogadas"
    }
    else : 
        return None 