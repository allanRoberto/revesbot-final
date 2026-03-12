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
Procuramos uma repetição de número exato no histórico que não tenha pago exodia por exemplo:

7 34 34 9

Jogada: Próximo 34 entrar 7 e 9 com 1 vizinho

Proteção todos os espelhos: 26 13 6
Total: 10 fichas com 0

IMPORTANTE:

⚠️Se houver qualquer repetição nas rodadas 5 6 tem que adicionar + 2 rodadas na contagem pois vai atrasar.

⚠️ Se o gatilho vier e na sequencia pagar um alvo ou repetir, ta cancelada a jogada.

🚫 O alvo não pode ser vizinho ou terminal da repetição
🚫 o alvo não pode ser crescente/decrescente da repetição
🚫 a repetição de mesmo número não pode ter ocorrido antes em 500 números (exodia invencivel)
"""
def soma_digitos(n):
    return sum(int(d) for d in str(n))

debug = True

def process_roulette(roulette, numbers):

    if (len(numbers) < 40) : 
        return None

    idxs = (0, 1, 2, 3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35)
    pos0, pos1, pos2, pos3, pos4, pos5, pos6, pos7, pos8, pos9, pos10, pos11, pos12, pos13, pos14, pos15, pos16, pos17, pos18, pos19, pos20, pos21, pos22, pos23, pos24, pos25, pos26, pos27, pos28, pos29, pos30, pos31, pos32, pos33, pos34, pos35 = numbers[0], numbers[1], numbers[2], numbers[3], numbers[4], numbers[5], numbers[6], numbers[7], numbers[8], numbers[9], numbers[10], numbers[11], numbers[12], numbers[13], numbers[14], numbers[15], numbers[16], numbers[17], numbers[18], numbers[19], numbers[20], numbers[21], numbers[22], numbers[23], numbers[24], numbers[25], numbers[26], numbers[27], numbers[28], numbers[29], numbers[30], numbers[31], numbers[32], numbers[33], numbers[34], numbers[35] = [numbers[i] for i in idxs] # 
    
    target = [pos12,pos9]
    form1 = pos11
    form2 = pos10  
    form3 = pos13
    form4 = pos14
    form5 = pos8
    form6 = pos7
    trigger_mirror = get_mirror(form1)

    if form1 != form2:
        #if(debug) : print(f"001 - O padrão não foi encontrado na roleta {roulette['slug']} porque os números {form1} e {form2} são diferentes")
        return None
    
    if appears_in_slice(0, numbers, 0, 16):
        if(debug) : print(f"001 - O padrão não foi encontrado na roleta {roulette['slug']} porque o número 0 já apareceu nas primeiras 8 rodadas")
        return None

    if len(trigger_mirror) > 0:
        if appears_in_slice(trigger_mirror[0], numbers, 0, 16):
            if(debug) : print(f"002 - O padrão não foi encontrado na roleta {roulette['slug']} porque o número {trigger_mirror} já apareceu nas primeiras 8 rodadas")
            return None


    if appears_in_slice(form1, numbers, 0, 9):
        if(debug) : print(f"003 - O padrão não foi encontrado na roleta {roulette['slug']} porque o número {form1} já apareceu nas primeiras 12 rodadas")
        return None

    if appears_in_slice(form1, numbers, 12, 16):
        if(debug) : print(f"004 - O padrão não foi encontrado na roleta {roulette['slug']} porque o número {form1} já apareceu nas primeiras 12 rodadas")
        return None
    
    if target[0] == target[1]:
        if(debug) : print(f"005 - O padrão não foi encontrado na roleta {roulette['slug']} porque os números {target[0]} e {target[1]} são iguais")
        return None
    
    if target[0] == form1 or target[1] == form1:
        if(debug) : print(f"006 - O padrão não foi encontrado na roleta {roulette['slug']} porque o número {form1} é igual ao alvo {target[0]} ou {target[1]}")
        return None
    
    if is_consecutive(target[0], target[1]):
        if(debug) : print(f"007 - O padrão não foi encontrado na roleta {roulette['slug']} porque os números {target[0]} e {target[1]} são consecutivos")
        return None
    
    if is_consecutive(target[0], form1) or is_consecutive(target[1], form1):
        if(debug) : print(f"008 - O padrão não foi encontrado na roleta {roulette['slug']} porque o número {form1} é consecutivo ao alvo {target[0]} ou {target[1]}")
        return None
    
    if is_check_neigbor_two_numbers(target[0], target[1]):
        if(debug) : print(f"009 - O padrão não foi encontrado na roleta {roulette['slug']} porque o alvo {target[0]} ou {target[1]} é vizinho de {form1}")
        return None
    
    if is_check_neigbor_two_numbers(target[0], form1) or is_check_neigbor_two_numbers(target[1], form1):
        if(debug) : print(f"010 - O padrão não foi encontrado na roleta {roulette['slug']} porque o número {form1} é vizinho do alvo {target[0]} ou {target[1]}")
        return None
    
    if same_terminal(target[0], target[1]):
        if(debug) : print(f"011 - O padrão não foi encontrado na roleta {roulette['slug']} porque os números {target[0]} e {target[1]} têm o mesmo terminal")
        return None

    # Verifica se há repetição consecutiva de form1 a partir da posição 13
    for i in range(13, len(numbers) - 1):
        if numbers[i] == form1 and numbers[i + 1] == form1:
            if(debug):
                print(f"012 - O padrão foi cancelado porque houve repetição consecutiva de {form1} nas posições {i} e {i+1} em {numbers[i:]}")
            return None
        
    if target[0] in numbers[7:9] or target[1] in numbers[7:9]:
        if(debug) : print(f"013 - O padrão não foi encontrado na roleta {roulette['slug']} porque o alvo {target[0]} ou {target[1]} está na sublista {numbers[8:11]}")
        return None
    
    if pos8 == pos7 or pos8 == pos6 or pos7 == pos6:
        if(debug) : print(f"014 - O padrão não foi encontrado na roleta {roulette['slug']} porque os números {pos8}, {pos7} ou {pos6} são iguais")
        return None
    
    target_neihbords = get_neighbords(target[0])
    target_neihbords2 = get_neighbords(form3)
    target_neihbords3 = get_neighbords(target[1])
    target_neihbords4 = get_neighbords(form5)
    # Verificar interseção
    comum = set(target_neihbords) & set(target_neihbords2)
    if comum:
        if len(comum) == 1:
            novo_alvo = int(next(iter(comum)))
            target[0] = novo_alvo

    comum = set(target_neihbords3) & set(target_neihbords4)
    if comum:
        if len(comum) == 1:
            novo_alvo = int(next(iter(comum)))
            target[0] = novo_alvo
    
    if find_terminal(target[1]) == find_terminal(form6):
        target[1] = form6
    
    if find_terminal(target[0]) == find_terminal(form3):
        target[0] = form4


                
    target_neihbords = get_neighbords(target[0])
    target_neihbords2 = get_neighbords(target[1])
    numbers_bet = [0]
    numbers_bet.extend(target)
    numbers_bet.extend(target_neihbords)
    numbers_bet.extend(target_neihbords2)
    mirror_list = [m for n in numbers_bet for m in get_mirror(n)]
    numbers_bet.extend(mirror_list)
    numbers_bet.insert(0, 0)
    numbers_bet = sorted(set(numbers_bet))
    trigger_mirror = get_mirror(form1)
    triggers = [form1]
    triggers.extend(trigger_mirror)


    sublista2 = numbers[6:9]
    comum = set(numbers_bet) & set(sublista2) 
    if comum:
        if(debug) : print(f"015 - O padrão não foi encontrado na roleta {roulette['slug']} porque os alvos {comum} estão na sublista {sublista2}")
        return None
    
    sublista3 = numbers[13:15]
    comum = set(numbers_bet) & set(sublista3) 
    if comum:
        if(debug) : print(f"016 - O padrão não foi encontrado na roleta {roulette['slug']} porque os alvos {comum} estão na sublista {sublista3}")
        return None

    #TESTE
    ##########################
    tipo = "EXODIA INVENCIVEL"
    print(f"Padrão = Puxa Quebra")
    print(f"Tipo = {tipo}")
    print(f"protecao = {numbers_bet}")
    #########################################

    return {
                "roulette_id":roulette['slug'],
                "roulette_name" : roulette["name"],
                "roulette_url" : roulette["url"],
                "pattern" : "EXODIA_INVENCIVEL",
                "triggers":triggers,
                "targets":target,
                "bets":numbers_bet,
                "passed_spins" : 0,
                "spins_required" : 0, 
                "filters_after_trigger" : ["consecutive", "repetition", "terminal", "alternation"], #todos os basicos, se pagou invertido
                "filters_before_trigger" : ["consecutive", "repetition", "terminal", "alternation"], #todos os basicos, se pagou invertido
                "snapshot":numbers[:50],
                "status":"waiting",
        }


