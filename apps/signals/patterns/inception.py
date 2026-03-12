import time
from helpers.utils.filters import (find_relationship,first_index_after, is_consecutive,
    any_consecutive,
    has_same_terminal,
    is_repetition,
    is_check_neigbor_two_numbers,
    appears_in_slice)



"""
inception:

o zero veio duas vezes e puxou o mesmo número 

exemplo: 

0 > 5 

0 > 5 

o próximo 5 que vier após 12  rodadas desse ultimo 05 vai puxar o 0 no 7 sorteio. 

Proteção: 5 10 

se o zero vier sem ter  sido puxado pelo 5 ele vai puxar o 5 no 7 sorteio


confirmação 100000000% de assertividade:


nas duas vezes que veio o 05 o número os 2 números que vieram após o 5 precisam ter algum tipo de relação, seja por duzia da mesma cor , terminal, vizinhos, espelhos, somas

na terceira vez que o 5 vier se ele vier junto com essa conexão, vai pagar o 0 1000%


"""


debug = True

def process_roulette(roulette, numbers):


    idxs = (0, 1, 2, 3)
    p0, p1, p2,p3 = [numbers[i] for i in idxs] # p1 : gatilho | p2 : alvo

    #O alvo tem que ser igual a zero
    if p2 != 0:
        #if(debug) : print(f"[{roulette['slug']}] - O número {p2} na roleta {roulette['slug']} não é igual a zero") 
        return None

    #Não pode ter uma ocorrencia proxima do 0 novamente
    if  appears_in_slice(p2, numbers, 3, 14):
        if(debug) : print(f"[{roulette['slug']}] - O número {p2} na roleta {roulette['slug']} aparece nas proximas 12 casas") 
        return None
    
    #Procura outra ocorrencia do gatilho (lista, numero a ser encontrado, começa por)
    second_confirmation = first_index_after(numbers, p2, start=14)

    #Se não acha uma segunda ocorrencia cai fora
    if second_confirmation is None:
        if(debug) : print(f"[{roulette['slug']}] - A segunda confirmação na roleta {roulette['slug']} não aconteceu") 
        return None
    
    #Se o 0 não puxou o mesmo numero cai fora
    if numbers[second_confirmation-1] != p1:
        if(debug) : print(f"[{roulette['slug']}] - O numero apos a segunda confirmação na roleta {roulette['slug']} não é igual ao gatilho") 
        return None


    #Ve se os dois numeros depois do gatilho tem uma relação
 
    relacao = find_relationship(p0,numbers[second_confirmation-2])

    #Se os dois numeros não tiverem uma relação cai fora
    if relacao == None:
        if(debug) : print(f"[{roulette['slug']}] - Os numeros apos o gatilho na roleta {roulette['slug']} não tem relacao") 
        return None

    #Ve se tem uma terceira Ocorrencia
    ja_pagou = first_index_after(numbers, p2, start= second_confirmation+1)
    ja_pagou_inverso = first_index_after(numbers, p1, start= second_confirmation+1)

    #Se tiver uma terceira ocorrencia e ela ja pagou
    if ja_pagou < 13:
        if(debug) : print(f"[{roulette['slug']}] - O 0 puxou o gatilho uma terceira vez na {roulette['slug']}") 
        return None
    
    #Se o gatilho ja havia trazido o zero cai fora
    if ja_pagou_inverso != None and numbers[ja_pagou_inverso-1] == p2:
        if(debug) : print(f"[{roulette['slug']}] - O gatilho puxou o 0 na {roulette['slug']} pagando invertido") 
        return None
 

    #Alvo, toda bet, gatilhos
    target = p2
    numbers_bet = [target, 10, p1]
    triggers = [p1,p2]
  


    return {
            "roulette_id": roulette['slug'],
            "roulette_name" : roulette["name"],
            "roulette_url" : roulette["url"],
            "pattern" : "PULADA",
            "triggers":[triggers],
            "targets":[target],
            "bets":numbers_bet,
            "passed_spins" : 0,
            "spins_required" : 0,
            "spins_count": 0,
            "snapshot":numbers[:50],
            "status":"waiting",
            "message": "Gatilho encontrado!",
            "tags": [],  # Adicionando as tags coletadas
    }

    return None
    

