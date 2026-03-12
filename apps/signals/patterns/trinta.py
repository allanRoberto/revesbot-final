def process_roulette(roulette, numbers) :

    if numbers[0] in [30, 31, 32, 33, 34, 35, 36] :

        return {
                "roulette_id": roulette['slug'],
                "roulette_name" : roulette["name"],
                "roulette_url" : roulette["url"],
                "pattern" : "TRINTAS",
                "triggers":[numbers[0]],
                "targets":[30, 31, 32, 33, 34, 35, 36],
                "bets": [30, 31, 32, 33, 34, 35, 36],
                "passed_spins" : 0,
                "spins_required" : 2,
                "spins_count": 0,
                "gales" : 20,
                "score" : 0,
                "snapshot":numbers[:10],
                "status":"processing",
                "message" : "Gatilho encontrado!",
                "tags" : [],
            }