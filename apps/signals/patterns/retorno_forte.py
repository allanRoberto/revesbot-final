"""
Sistema de Ranking para Gatilhos Pendentes
"""

from helpers.utils.filters import first_index_after, soma_digitos, is_consecutive
from helpers.utils.get_figure import get_figure
from helpers.utils.get_mirror import get_mirror
from collections import defaultdict
from typing import Callable, List, Tuple
from helpers.classificador import ClassificadorProximidade


def pagou_invertido(numbers, bet) :
    ocorrencias = []
    for i, num in enumerate(numbers, start=1):
        if num in bet:
            ocorrencias.append((i, num))
    return ocorrencias

def gerar_ranking(numbers, limite) :
    # Dicionário para contar gatilhos por soma
    ranking = defaultdict(lambda: {
        'count': 0,           # Quantidade de gatilhos pendentes
        'positions': [],      # Posições onde estão pendentes
        'trigger_numbers': [], # Números que são gatilhos
    })
    
    # Analisa os últimos 30 números
    for i, number in enumerate(numbers[2:limite]):
        
        j = first_index_after(numbers, number, i+1)
        
        if j == None:
            continue
        
        if j + 1 > len(numbers):
            continue
        
        numero_antes = numbers[j+1]

        if numero_antes == 0 :
            continue

        soma_numero_antes = soma_digitos(numero_antes)
        figuras_numero_antes = get_figure(soma_numero_antes)
        
        japagou = any(num in numbers[0:i] for num in figuras_numero_antes)
        
        if not japagou:
            ranking[soma_numero_antes]['count'] += 1
            ranking[soma_numero_antes]['positions'].append(i)
            ranking[soma_numero_antes]['trigger_numbers'].append(number)
    
    return ranking


def process_roulette(roulette, numbers):

    if len(numbers) < 30 :
        return None
    
    classificador = ClassificadorProximidade()

    for number in numbers[0:150]:
        classificador.adicionar_numero(number)

    score = classificador.get_ranking()[:5]

    

    ranking = gerar_ranking(numbers, 30)

    p0 = numbers[0]
    p1 = numbers[1]
    p0_mirror  = get_mirror(p0)
    index_numero_antes = first_index_after(numbers, p0, 1)
    
    if index_numero_antes == None or index_numero_antes + 2 > len(numbers):
        return None
        
    numero_antes = numbers[index_numero_antes+1]

    numero_antes_gatilho = numbers[index_numero_antes-1]
    numero_depois_gatilho = numbers[index_numero_antes+2]


    if (is_consecutive(p0, numero_antes)) :
        return None
    
    if (p0 == numero_antes) :
        return None
    
    if (numero_antes in p0_mirror) :
        return None
    
    if(is_consecutive(numero_depois_gatilho, numero_antes_gatilho)) :
        return None
    
    if(numero_depois_gatilho == numero_antes_gatilho) :
        return None


    if numero_antes == 0 or numero_antes_gatilho == 0 or p1 == 0 or p0 == 0:
        return None

    soma_numero_antes = soma_digitos(numero_antes)
    
    bet = get_figure(soma_numero_antes) 



    ocorrencias = pagou_invertido(numbers[2:50], bet)

    if ocorrencias:
        indice, _ = ocorrencias[0] 


    if indice  <= 20 :
        return None
    
    if(indice == index_numero_antes) :
        return None

    if ranking[soma_numero_antes]['count'] >= 1 :



        top12 = [num for num, _ in score]


        if any(num in top12 for num in bet):

            tags = [f"count_{ranking[soma_numero_antes]['count']}", f"positions_{ranking[soma_numero_antes]['count']}", f"pagou_invertido_{indice}", f"indice_numero_antes_{index_numero_antes}"]

            return {
                    "roulette_id": roulette['slug'],
                    "roulette_name" : roulette["name"],
                    "roulette_url" : roulette["url"],
                    "pattern" : "RETORNO_FORTE",
                    "triggers":[numbers[0]],
                    "targets":[*bet],
                    "bets":bet,
                    "passed_spins" : 0,
                    "spins_required" : 0,
                    "spins_count": 0,
                    "snapshot":numbers[:index_numero_antes + 4],
                    "status":"processing",
                    "message": "Gatilho encontrado!",
                    "tags": tags,  
            }


    
    return None  # ou retorna sinal se necessário