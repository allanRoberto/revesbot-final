import time
from helpers.utils.filters import (
    first_index_after,
    is_consecutive,
    any_consecutive,
    has_same_terminal,
    is_repetition,
    is_check_neigbor_two_numbers,
    appears_in_slice,
    find_terminal,
    same_terminal,
    get_neighbords,
    get_mirror
)


"""
É assim: 

Repetição de terminal 

O primeiro número da repetição se torna o gatilho 

O numero que vier no quinto sorteio se torna o alvo 

Entao 

3 23 X X X X 4 

Próximo 3 jogar 4 com 1 vizinho 

Nao pode haver outra repetição de terminal 3 com o 3 

Ou outra repetição no meio ou no quinto sorteio

Os filtros de entrada se aplicam

Não pode ter tripla repeticao de terminal

Não pode ter dupla repetição de terminal

"""


debug = False

def process_roulette(roulette, numbers):

    #Teste
    #################################################
    #print(f"Roleta: {roulette}")
    #print(f"Lista extraida: {numbers}")
    #####################################################

    idxs = (0, 1, 2, 3,4, 5, 6,7,8,9,10,11)
    p0, p1, p2,p3,p4, p5, p6, p7,p8,p9,p10,p11 = [numbers[i] for i in idxs] # p2 e p1 : alvo | p9 : gatilho

    Tp0 = find_terminal(p0)
    Tp1 = find_terminal(p1)
    Tp2 = find_terminal(p2)
    Tp3 = find_terminal(p3)
    Tp4 = find_terminal(p4)
    Tp5 = find_terminal(p5)
    Tp6 = find_terminal(p6)
    Tp7 = find_terminal(p7)
    Tp8 = find_terminal(p8)
    Tp9 = find_terminal(p9)
    Tp10 = find_terminal(p10)
    Tp11 = find_terminal(p11)

    terminals = [
    find_terminal(p0),
    find_terminal(p1),
    find_terminal(p2),
    find_terminal(p3),
    find_terminal(p4),
    find_terminal(p5),
    find_terminal(p6),
    find_terminal(p7),
    find_terminal(p8),
    find_terminal(p9),
    find_terminal(p10),
]
    pairs = [(10,9), (8,7), (7,6),(6,5), (5,4), (4,3), (3,2), (2,1), (1,0)]

    

    #Verifica se p7 e p8 tem terminais diferentes
    if Tp9 != Tp8:
        if(debug) : print(f"001 - O número {p7} e {p8} na roleta {roulette['slug']} tem terminais diferentes") 
        return None
    
    if Tp10 == Tp7:
        if(debug) : print(f"001 - O número {p7} e {p10} na roleta {roulette['slug']} tem terminais iguais") 
        return None
    
    #Verifica sep0 e p7 tem terminais iguais
    if Tp1 == Tp9:
        if(debug) : print(f"002 - O número {p0} e {p8} na roleta {roulette['slug']} tem terminais iguais") 
        return None
    
    #Verifica se tem algum terminal repetido
    for hi, lo in pairs:
        if terminals[hi] == terminals[lo]:
            if(debug) : print(f"003 - O número {numbers[hi]} e {numbers[lo]} na roleta {roulette['slug']} tem terminais iguais") 
            return None

    if  appears_in_slice(0, numbers, 0, 12):
        if(debug) : print(f"004 - O número 0 na roleta {roulette['slug']} aparece nas proximas 13 casas") 
        return None
    
    if Tp9 == Tp10 or Tp9 == Tp11:
        if(debug) : print(f"006 - O terminal {Tp7} na roleta {roulette['slug']} aparece muito proximo do gatilho") 
        return None
    
    if appears_in_slice(p9, numbers, 0, 8):
        if(debug) : print(f"008 - O numero {p8} na roleta {roulette['slug']} esta no meio da jogada do gatilho") 
        return None
    
    if appears_in_slice(p8, numbers, 0, 7):
        if(debug) : print(f"008 - O terminal {p6} na roleta {roulette['slug']} esta no meio da jogada do gatilho") 
        return None
    
    if appears_in_slice(p2, numbers, 3, 11):
        if(debug) : print(f"008 - O terminal {p1} na roleta {roulette['slug']} esta no meio da jogada do gatilho") 
        return None
    
    if p2 == p1 or p3 == p1:
        if(debug) : print(f"007 - O número {p0} ou {p2} na roleta {roulette['slug']} alterna com um numero depois da formação")
        return None
    
    if appears_in_slice(p3, numbers, 4, 11):
        if(debug) : print(f"008 - O numero {p2} na roleta {roulette['slug']} esta no meio da jogada do gatilho") 
        return None
    
    if is_consecutive(p9, p10):
        if(debug) : print(f"009 - A lista {numbers} na roleta {roulette['slug']} é consecutiva")
        return None

    if is_consecutive(p2, p9):
        if(debug) : print(f"009 - A lista {numbers} na roleta {roulette['slug']} é consecutiva")
        return None

    if is_consecutive(p3, p9):
        if(debug) : print(f"009 - A lista {numbers} na roleta {roulette['slug']} é consecutiva")
        return None

    if same_terminal(p6,p9):
        if(debug) : print(f"009 - A lista {numbers} na roleta {roulette['slug']} é consecutiva")
        return None       

    if p5 in get_neighbords(p9):
        if(debug) : print(f"009 - A lista {numbers} na roleta {roulette['slug']} é consecutiva")
        return None       
    
    if Tp2 == Tp8 or Tp3 == Tp8:
        if(debug) : print(f"010 - O terminal {Tp1} na roleta {roulette['slug']} é igual ao gatilho") 
        return None
    
    if is_consecutive(p0, p1):
        if(debug) : print(f"011 - A lista {numbers} na roleta {roulette['slug']} é consecutiva")
        return None
    
    if p2 == p1:
        if(debug) : print(f"012 - os alvos na roleta {roulette['slug']} é repetição")
        return None
    
    if p2 == p9 or p2 == p8 or p1 == p9 or p1 == p8:
        if(debug) : print(f"013 - os alvos na roleta {roulette['slug']} é igual ao gatilho")
        return None
    
    if  p9 in get_mirror(p2) or p8 in get_mirror(p2) or p9 in get_mirror(p1) or p8 in get_mirror(p1):
        if(debug) : print(f"014 - os alvos na roleta {roulette['slug']} é igual ao gatilho")
        return None
    
    if is_consecutive(p2,p1):
        if(debug) : print(f"015 - os alvos na roleta {roulette['slug']} são consecutivos")
        return None

    if Tp9 == 1 and p10 == 10:
        if(debug) : print(f"016 - o gatilho na roleta {roulette['slug']} é 1 e o próximo é 10")
        return None
    
    elif Tp9 == 2 and p10 == 20:
        if(debug) : print(f"017 - o gatilho na roleta {roulette['slug']} é 2 e o próximo é 20")
        return None
    
    elif Tp9 == 3 and p10 == 30:
        if(debug) : print(f"018 - o gatilho na roleta {roulette['slug']} é 3 e o próximo é 30")
        return None
    
    second_confirmation = first_index_after(numbers, p9, start=12)
    if second_confirmation is not None:
        if numbers[second_confirmation-1] == p8:
            if(debug) : print(f"019 - Essa sequencia na roleta {roulette['slug']} Ja se repetiu")
            return None
        
    if is_consecutive(p8,p9):
        if(debug) : print(f"020 - o gatilho na roleta {roulette['slug']} esta preso num exodia consecutivo")

    #Alvo, toda bet, gatilhos
    target = [p2,p1]
    target_neihbords1 = get_neighbords(p2)
    target_neihbords2 = get_neighbords(p1)
    numbers_bet = [*target, *target_neihbords1,*target_neihbords2 ,0]
    mirror_list = [m for n in numbers_bet for m in get_mirror(n)]
    numbers_bet.extend(mirror_list)
    numbers_bet.insert(0, 0)
    numbers_bet = sorted(set(numbers_bet))
    triggers = [p9]

    
    #TESTE
    ##########################
    tipo = "Repeticao de terminal"
    print(f"Tipo = {tipo}")
    print(f"p1 = {p1}")
    print(f"p2 = {p2}")
    print(f"protecao = {numbers_bet}")
    #########################################

    return {
                "roulette_id":roulette['slug'],
                "roulette_name" : roulette["name"],
                "roulette_url" : roulette["url"],
                "pattern" : "Repeticao de terminal",
                "triggers":triggers,
                "targets":target,
                "bets":numbers_bet,
                "passed_spins" : 0,
                "spins_required" : 20, #Spins que não vai ter para traz o gatilho
                "snapshot":numbers[:50],
                "status":"waiting",
                "message" : "Gatilho encontrado!"
        }

