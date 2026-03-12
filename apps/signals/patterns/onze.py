from helpers.classificador import ClassificadorProximidade

def process_roulette(roulette, numbers) :

    if len(numbers) < 100 :
        return None
    
    p0 = numbers[0]
    
    if p0 in [11, 22, 33] :

        bet = [11, 22, 33, 16, 1, 18, 9, 36, 30]

        classificador = ClassificadorProximidade()

        for number in numbers[:100]:
            classificador.adicionar_numero(number)

        ranking = classificador.get_ranking()[:15]


        numeros = [num for num, _ in ranking]

        # Interseção preservando ordem dos candidatos (se preferir ordem do ranking, inverta a lógica)
        matches = [n for n in bet if n in numeros]

    
        bet = sorted(set(bet))

        return {
                "roulette_id": roulette['slug'],
                "roulette_name" : roulette["name"],
                "roulette_url" : roulette["url"],
                "pattern" : "GEMEOS",
                "triggers":[numbers[0]],
                "targets":[11, 22, 33],
                "bets": bet,
                "passed_spins" : 0,
                "spins_required" : 3,
                "spins_count": 0,
                "gales" :10,
                "score" : len(matches),
                "snapshot":numbers[:50],
                "status":"processing",
                "message" : "Gatilho encontrado!",
                "tags" : [],
            }
    
    return None