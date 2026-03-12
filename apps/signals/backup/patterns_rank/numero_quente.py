from collections import Counter
from helpers.classificador import ClassificadorProximidade
from helpers.utils.filters import get_neighbords
from helpers.utils.filters import get_mirror

import requests
from datetime import datetime, timedelta


def process_roulette(roulette, numbers):


    if len(numbers) < 50 :
        return None
    
    classificador = ClassificadorProximidade(peso_principal = 3.5,
    peso_vizinhos = 1.4,
    peso_vizinhos1 = 0.8,
    peso_duzia = 0.5,
    peso_cor = 0,
    peso_puxada = 2,
    qtd_puxada = 10,
    decaimento = 0.5)

    for number in numbers[:40]:
        classificador.adicionar_numero(number)

    ranking = classificador.get_ranking()[:12]

    bet = [num for num, _ in ranking]

    trigger = bet[0]

    score = [score for _, score in ranking]

    soma_score = sum(score)
    score_arredondado = round(soma_score, 2)

  

    bet = sorted(set(bet))

    bet_set = set(bet)
   
    
    return {
            "roulette_id": roulette['slug'],
            "roulette_name" : roulette["name"],
            "roulette_url" : roulette["url"],
            "pattern" : f"TEMPORAL_{len(bet)}",
            "triggers":[numbers[0]],
            "targets":[*bet],
            "bets": bet,
            "passed_spins" : 0,
            "spins_required" : 0,
            "attempts" : 0,
            "spins_count": 0,
            "gales" : 3,
            "score" : "",
            "snapshot":numbers[:50],
            "status":"processing",
            "message" : "Gatilho encontrado!",
            "tags" : [],
            }

    return None
