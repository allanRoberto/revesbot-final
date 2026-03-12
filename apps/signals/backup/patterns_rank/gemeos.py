def process_roulette(roulette, numbers) :
  if numbers[0] in [11, 22, 33] and numbers[1] not in [11, 22, 33]:
    trigger = numbers[1]

    bet = [0, 18, 22, 9, 1, 33, 16, 11, 30, 36]

    return {
                "roulette_id": roulette['slug'],
                "roulette_name" : roulette["name"],
                "roulette_url" : roulette["url"],
                "pattern" : "GEMEOS",
                "triggers":[trigger],
                "targets":[11, 22, 33],
                "bets": bet,
                "passed_spins" : 0,
                "spins_required" : 2,
                "spins_count": 0,
                "gales" : 20,
                "score" : 0,
                "snapshot":numbers[:50],
                "status": "processing",
                "message" : "Gatilho encontrado!",
                "tags" : [],
            }


