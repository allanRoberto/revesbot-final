from helpers.utils.filters import (
    first_index_after,
    is_consecutive,
    any_consecutive,
    has_same_terminal,
    is_repetition,
    is_check_neigbor_two_numbers,
    appears_in_slice,
)

from helpers.utils.get_neighbords import get_neighbords
from helpers.utils.get_mirror import get_mirror

debug = False

def process_roulette(roulette, numbers):
        
    idxs = (0, 1, 2)
    p0, p1, p2 = [numbers[i] for i in idxs] # p1 : Gatilho | p2 : Alvo


    if (p1 == 0 or p2 == 0) :
        return None

    """ Gatilho não pode aparecer nas últimas 12 jogadas
    
    O gatilho não pode ser formado com uma diferença de menos de 12 jogadas entre a primeira e a segunda aparição da formação, ex:

    [10, 21, 30 x, x, x (Aqui precisa ter 12 spins no mínimo) x, x, x, 21, 5]
     
     """
    
    if (appears_in_slice(p1, numbers, 2, 12)) : 
        if(debug) : print(f"001 - [{roulette['name']}] URL: http://localhost:8000/history/{roulette['slug']} - O número {p1} na roleta {roulette['slug']} aparece nas últimas 12 posições")
        return None   
    
    # 1 ) Procura outra ocorrência do gatilho
    second_confirmation = first_index_after(numbers, p1, start=12)

    # 2 ) Verifica se encontrou a segunda ocorrência do gatilho
    if second_confirmation is None:
        if(debug) : print(f"002 - [{roulette['name']}] - [{roulette['slug']}] {p1} não aparece novamente nas últimas 200 posições apartir da décima posição")
        return None

    # 2.1 ) Verifica se após a segunda ocorrência, existe um número
    try:
        # 2.2 ) Grava o número após a segunda ocorrência
        next_val = numbers[second_confirmation + 1]
    except IndexError:

        if(debug) : print(f"003 - [{roulette['name']}] URL: http://localhost:8000/history/{roulette['slug']} - [{roulette['slug']}] - {p1} Não há número suficiente após a primeira confirmação, pulando...")
        return None
    

    if(next_val == 0) :
        if(debug) : print(f"004 - [{roulette['name']}] URL: http://localhost:8000/history/{roulette['slug']} - [{roulette['slug']}] - {p1} O número que forma o gatilho na segunda formação não pode ser um zero")
        return None
    
    if(p2 == 0) :
        if(debug) : print(f"005 - [{roulette['name']}] URL: http://localhost:8000/history/{roulette['slug']} - [{roulette['slug']}] - {p1}  O número que forma o gatilho na primeira formação não pode ser um zero")
        return None
    
    if(p2 == 0) :
        if(debug) : print(f"006 - [{roulette['name']}] URL: http://localhost:8000/history/{roulette['slug']} - [{roulette['slug']}] - {p1} O alvo não pode ser um zero")
        return None
    
    #Confirma a formação do gatilho
    if (is_check_neigbor_two_numbers(next_val, p0)):

        """ Gatilho não pode se formar com vizinhos ou números iguais

        A formação do gatilho não pode ser composta de números iguais ou vizinhos, ex : 
        [10, 21, 5 x, x, x, x, x, x, 21, 5]

        O número 5 está na primeira aparição e também na segunda. 
        Outro exemplo, agora com vizinho do 5 : 
        [10, 21, 24 x, x, x, x, x, x, 21, 5] 
        
        """
        neighbords_next_val = get_neighbords(next_val)
        if(p2 == next_val or numbers[second_confirmation - 1] in neighbords_next_val) : 
            if(debug) : print(f"007 - [{roulette['name']}] URL: http://localhost:8000/history/{roulette['slug']} - [{roulette['slug']}] O número atrás do gatilho({p1}) - {numbers[second_confirmation - 1]} é igual ou vizinho na primeira aparição. {next_val}")
        
            return None
    
        """ Formação do gatilho não pode ter uma sequência, alternância ou repetição de terminal

            Todos os exemplos abaixo fazem com que o gatilho seja cancelado :

            Sequência detectada na primeira aparição (21, 20)
            [1, 21, 24 x, x, x, x, x, x, 21, 20]

            Sequência detectada na segunda aparição (22, 21)
            [1, 21, 22 x, x, x, x, x, x, 21, 20]

            Alternância detectada na primeira aparição (21, 20, 21)
            [1, 21, 30, x, x, x, x, x, x, 21, 20, 21]

            Alternância detectada na segunda aparição (21, 30, 21)
            [1, 21, 30 ,21, x, x, x, x, x, 21, 20]

            Repetição de terminal detectada na primeira aparição (21, 11)
            [30, 21, 05, x, x, x, x, x, 21, 11]

            Repetição de terminal detectada na segunda aparição (21, 11)
            [10, 21, 11, x, x, x, x, x, 21, 5] """
        
        # val (2) others : [3, 5, 6, 9, 10]

        #gatiho 20
        # [1, 20, 13, 15] false
        # [1, 20, 13, 20] true
        # [1, 20, 13, 15 xxxxxx 13 , 20, 12, 25, 26, 15, 20  true
        # 20 (19, 12)

     
        if(any_consecutive(p1, [p2, p0])):
            if(debug) : print(f" 008 - [{roulette['name']}] URL: http://localhost:8000/history/{roulette['slug']} - O número {p1} vem de uma sequência crescente ou decrescente com o {p2} ou o {p0}")
            return None
        
        # [12, 20, 31 xxxxx 21, 20, 13]
        if(any_consecutive(p1,[next_val, numbers[second_confirmation - 1]])) : 
            if(debug) : print(f" 009 - [{roulette['name']}] URL: http://localhost:8000/history/{roulette['slug']} - O número {p1} vem de uma sequência crescente ou decrescente com o {next_val} ou o {numbers[second_confirmation - 1]}")
            return None
        
        if(appears_in_slice(p1, [numbers[0], numbers[2], numbers[3]], 0, 3))  : 
            if(debug) : print(f"010a - [{roulette['name']}] URL: http://localhost:8000/history/{roulette['slug']} - O número {p1} vem de uma alternância com os números  {numbers[second_confirmation+1:second_confirmation+3]}")
            return None
        
        if(appears_in_slice(p1, numbers, second_confirmation + 1, second_confirmation + 3)) : 
            if(debug) : print(f"010b - [{roulette['name']}] URL: http://localhost:8000/history/{roulette['slug']} - O número {p1} vem de uma alternância com os números  {numbers[second_confirmation+1:second_confirmation+3]}")
            return None
        
        # if(has_same_terminal([(p2, p0), (next_val, numbers[second_confirmation + 2]), (next_val, numbers[second_confirmation - 1])], p1)) : 
        #     if(debug) : print(f"011 - [{roulette['name']}] URL: http://localhost:8000/history/{roulette['slug']} - O número {p1} vem de uma repeticão de terminais com os números {p0} ou {p2} na segunda aparição ou uma repetição com os números {next_val} e {numbers[second_confirmation - 1]} {numbers[second_confirmation + 2]},  com o {next_val} ou o {numbers[second_confirmation - 1]}")
        #     return None

        """ Formação não pode vir de uma repetição do gatilho ou do seu espelho
            [2, 21, 05, x, x, x, x, x, 21, 21]

            [2, 21, 05, x, x, x, x, x, 21, 12] """
        

        mirror_p1 = get_mirror(p1)


        if p1 == next_val or next_val in mirror_p1 :
            if(debug) : print(f"012 - [{roulette['name']}] URL: http://localhost:8000/history/{roulette['slug']} - O número {p1} é igual ao {next_val} ou é espelho dele")
            return None
        
        """
        Formação não pode vir de uma sequência

        Sequência na primeira formação  
        [31, 21, 05, x, x, x, x, 10, 21, 9]

        Sequência na segunda formação
        [31, 21, 30, x, x, x, x, x, 21, 14]

        Sequência entre as duas formações
        [31, 21, 30, x, x, x, x, 29, 21, 14]
        
        """

        if (
            is_consecutive(next_val, numbers[second_confirmation - 1]) or
            is_consecutive(p0, p2)  
            ) : 
            if(debug) :  print(f"013 - [{roulette['name']}] - O número {p1} vem de uma sequência.")
            return None

        if (next_val == numbers[second_confirmation - 1]) : 
            if (debug) : print(f"014 - [{roulette['name']}] URL : http://localhost:8000/history/{roulette['slug']} - {p1} Repetição detectada na primeira aparição com os números {next_val} e {numbers[second_confirmation - 1]}")
            return None

        if (next_val == numbers[second_confirmation]) : 
            if (debug) : print(f"015 - [{roulette['name']}] URL : http://localhost:8000/history/{roulette['slug']} - {p1} Repetição detectada na primeira aparição com os números {next_val} e {numbers[second_confirmation]}")
            return None
        
        if(numbers[second_confirmation + 1] == numbers[second_confirmation + 2]) : 
            if (debug) : print(f"016 - [{roulette['name']}] URL : http://localhost:8000/history/{roulette['slug']} - {p1} Repetição detectada na primeira aparição com os números {numbers[second_confirmation + 1]} e {numbers[second_confirmation + 2]}")
            return None
        
        if (p1 == p2) : 
            if (debug) : print(f"017 - [{roulette['name']}] URL : http://localhost:8000/history/{roulette['slug']} - {p1} Repetição detectada na segunda aparição com os números {p1} e {p2}")
            return None
        
        if (p0 == p1) : 
            if (debug) : print(f"018 - [{roulette['name']}] URL : http://localhost:8000/history/{roulette['slug']} - {p1} Repetição detectada na segunda aparição com os números {p0} e {p1}")
            return None

        p1_neihbords = get_neighbords(p1)

        if(next_val in p1_neihbords) : 
            if (debug) : print(f"019 - [{roulette['name']}] URL : http://localhost:8000/history/{roulette['slug']} - {p1} O {next_val} não pode ser vizinho de  {p1}")
            return None

        second_confirmation_before_mirror = get_mirror(numbers[second_confirmation - 1]) or []
        if(next_val in second_confirmation_before_mirror) : 
            if (debug) : print(f"020a - [{roulette['name']}] URL : http://localhost:8000/history/{roulette['slug']} - {p1} O {next_val} não pode ser espelho de  {numbers[second_confirmation - 1]}")
            return None
        
        if(next_val in p1_neihbords) : 
            if (debug) : print(f"020b - [{roulette['name']}] URL : http://localhost:8000/history/{roulette['slug']} - {p1} O {next_val} não pode ser espelho de  {numbers[second_confirmation - 1]}")
            return None
        
        first_confirmation_after_mirror = get_mirror(p2) or []
        if(p1 in first_confirmation_after_mirror) : 
            if (debug) : print(f"020c - [{roulette['name']}] URL : http://localhost:8000/history/{roulette['slug']} - {p1} O {next_val} não pode ser espelho de  {p1}")
            return None
        
        first_confirmation_before_mirror = get_mirror(p0) or []
        if(p1 in first_confirmation_before_mirror) : 
            if (debug) : print(f"020d - [{roulette['name']}] URL : http://localhost:8000/history/{roulette['slug']} - {p1} O {p0} não pode ser espelho de  {p1}")
            return None
        
        second_confirmation_after_neihbords = get_mirror(next_val) or []
        if(next_val in second_confirmation_after_neihbords) : 
            if (debug) : print(f"020e - [{roulette['name']}] URL : http://localhost:8000/history/{roulette['slug']} - {p1} O {next_val} não pode ser espelho de  {p1}")
            return None


        if(is_consecutive(p2, numbers[second_confirmation -1])) : 
            if (debug) : print(f"021 - [{roulette['name']}] URL : http://localhost:8000/history/{roulette['slug']} - {p1} O número após a primeira aparição {p2} é sequencial com o número após a segunda aparição {numbers[second_confirmation -1]}")
            return None

        if(is_consecutive(numbers[second_confirmation + 1], numbers[second_confirmation + 2])) : 
            if (debug) : print(f"021 - [{roulette['name']}] URL : http://localhost:8000/history/{roulette['slug']} - {p1} A primeira aparição do número veio de uma sequência {numbers[second_confirmation + 1]} - {numbers[second_confirmation + 2]}")
            return None

        # if(any_consecutive(next_val, p1_neihbords)) : 
        #     if (debug) : print(f"022 - [{roulette['name']}] URL : http://localhost:8000/history/{roulette['slug']} - {p1} A primeira aparição do número veio de uma sequência de vizinhos {p1_neihbords} - {next_val}")
        #     return None

        
        
        if(p0 == next_val) : 
            if (debug) : print(f"023 - [{roulette['name']}] URL : http://localhost:8000/history/{roulette['slug']} - {p1} O número antes da segunda aparição - {next_val} não pode ser igual o número após a primeira aparição {p0}")
            return None
        

        #Passou em todas as validações, agora montamos o sinal 
        target = p2
        target_neihbords = get_neighbords(target)
        numbers_bet = [target, *target_neihbords, p1]
        mirror_list = [m for n in numbers_bet for m in get_mirror(n)]
        numbers_bet.extend(mirror_list)
        numbers_bet.insert(0, 0)
        numbers_bet = sorted(set(numbers_bet))

        mirror_triggers = get_mirror(p1)
        triggers = [p1, *mirror_triggers]

        return {
                "roulette_id":roulette['slug'],
                "roulette_name" : roulette["name"],
                "roulette_url" : roulette["url"],
                "pattern" : "PAGOU_ANTES",
                "triggers":triggers,
                "targets":[target],
                "bets":numbers_bet,
                "passed_spins" : 0,
                "spins_required" : 11,
                "snapshot":numbers[:50],
                "status":"pending",
        }

    if(debug) : print(f"[{roulette['name']}] - Não tem nenhum gatilho ativo")    
    return None
        
                
        
    