import time
from helpers.utils.filters import (
    first_index_after,
    is_consecutive,
    appears_in_slice,
)
from helpers.utils.get_neighbords import get_neighbords
from helpers.utils.get_mirror import get_mirror


"""
z > x
z > x
quebrou
z > y

proxima entrada z entrar y e x com 1 vizinho
proteções 2 16

"""


debug = False

def process_roulette(roulette, numbers):

    #Teste
    #################################################
    #print(f"Roleta: {roulette}")
    #print(f"Lista extraida: {numbers}")
    #####################################################

    idxs = (0, 1, 2, 3)
    p0, p1, p2,p3 = [numbers[i] for i in idxs] # p1 : alvo | p2 : gatilho

    p1_neihbords = get_neighbords(p2)
    p2_neihbords = get_neighbords(p2)
    p2_mirror = get_mirror(p2)
    p1_mirror = get_mirror(p1)

    #Verifica se é o alvo e espelho
    if p1 in p2_mirror:
        if(debug) : print(f"001 - O número {p1} na roleta {roulette['slug']} é espelho do número {p2}") 
        return None     

    #Verifica se é vizinho
    if p1 in p2_neihbords:
        if(debug) : print(f"002 - O número {p1} na roleta {roulette['slug']} é vizinho do número {p2}") 
        return None 
    
    if p0 == 0:
       if(debug) : print(f"003 - O número {p0} na roleta {roulette['slug']} é igual ao número 0") 
       return None 

    if p3 == 0:
       if(debug) : print(f"004 - O número {p3} na roleta {roulette['slug']} é igual ao número 0") 
       return None 


    if p1 == 0:
       if(debug) : print(f"005 - O número {p1} na roleta {roulette['slug']} é igual ao número 0") 
       return None 

    if p2 == 0:
       if(debug) : print(f"006 - O número {p2} na roleta {roulette['slug']} é igual ao número 0") 
       return None 

    if p1 == p2:
       if(debug) : print(f"007 - O número {p2} na roleta {roulette['slug']} é igual ao número {p1}") 
       return None 
    
    #Verifica se algum deles é consecutivo
    
    if is_consecutive(p0,p1) == True:
        if(debug) : print(f"008 - O número {p0} na roleta {roulette['slug']} é consecutivo ao número {p1}") 
        return None
    
    if is_consecutive(p1,p2) == True:
        if(debug) : print(f"009 - O número {p1} na roleta {roulette['slug']} é consecutivo ao número {p2}") 
        return None

    if is_consecutive(p2,p3) == True:
        if(debug) : print(f"010 - O número {p2} na roleta {roulette['slug']} é consecutivo ao número {p3}") 
        return None

    
    #Não pode ter uma ocorrencia proxima do gatilho novamente
    if  appears_in_slice(p2, numbers, 3, 14):
        if(debug) : print(f"011 - O número {p2} na roleta {roulette['slug']} aparece nas proximas 13 casas") 
        return None
    
    #Procura outra ocorrencia do gatilho (lista, numero a ser encontrado, começa por)
    second_confirmation = first_index_after(numbers, p2, start=14)

    #Se não acha uma segunda ocorrencia cai fora
    if second_confirmation is None:
        if(debug) : print(f"012 - A segunda confirmação na roleta {roulette['slug']} não aconteceu") 
        return None
    
    if second_confirmation-14 < 13:
        if(debug) : print(f"013 - A segunda confirmação na roleta {roulette['slug']} aconteceu muito proxima do gatilho") 
        return None
    
    if numbers[second_confirmation-1] == 0:
       if(debug) : print(f"014 - O número {numbers[second_confirmation-1]} na roleta {roulette['slug']} é igual ao número 0") 
       return None 
    
    if numbers[second_confirmation-2] == 0:
       if(debug) : print(f"015 - O número {numbers[second_confirmation-2]} na roleta {roulette['slug']} é igual ao número 0") 
       return None 

    if second_confirmation + 1 >= len(numbers):
       if(debug) : print(f"016 - O número {second_confirmation + 1} na roleta {roulette['slug']} ultrapassou o tamanho da lista {len(numbers)}") 
       return None 

    if numbers[second_confirmation+1] == 0:
       if(debug) : print(f"017 - O número {numbers[second_confirmation+1]} na roleta {roulette['slug']} é igual ao número 0") 
       return None 
    
    #Verifica se é o alvo e espelho
    if numbers[second_confirmation-1] in p2_mirror :
        if(debug) : print(f"018 - O número {numbers[second_confirmation-1]} na roleta {roulette['slug']} é espelho do número {p2}") 
        return None    
    
    #Verifica se é os dois alvos são espelhos
    if numbers[second_confirmation-1] in p1_mirror:
        if(debug) : print(f"019 - O número {numbers[second_confirmation-1]} na roleta {roulette['slug']} é espelho do número {p1_mirror}") 
        return None    
    

    #Se o gatilho puxou o mesmo numero cai fora
    if numbers[second_confirmation-1] == p1:
        if(debug) : print(f"020 - O numero apos a segunda confirmação na roleta {roulette['slug']} é igual ao alvo") 
        return None
    
    #Verifica se é vizinho
    if numbers[second_confirmation-1] in p2_neihbords:
        if(debug) : print(f"021 - O número {numbers[second_confirmation-1]} na roleta {roulette['slug']} é vizinho do número {p2}") 
        return None 
    
    #Verifica se é vizinho
    if numbers[second_confirmation-1] in p1_neihbords:
        if(debug) : print(f"022 - O número {numbers[second_confirmation-1]} na roleta {roulette['slug']} é vizinho do número {p1}") 
        return None 
    
    #Verifica se algum deles é consecutivo
    if is_consecutive(numbers[second_confirmation-2],numbers[second_confirmation-1]) == True:
        if(debug) : print(f"023 - O número {numbers[second_confirmation-2]} na roleta {roulette['slug']} é consecutivo ao número {numbers[second_confirmation-1]}") 
        return None
    
    if is_consecutive(numbers[second_confirmation-1],p2) == True:
        if(debug) : print(f"024 - O número {numbers[second_confirmation-1]} na roleta {roulette['slug']} é consecutivo ao número {p2}") 
        return None
    
    if is_consecutive(p2,numbers[second_confirmation+1]) == True:
        if(debug) : print(f"025 - O número {p2} na roleta {roulette['slug']} é consecutivo ao número {numbers[second_confirmation+1]}") 
        return None
    
    if is_consecutive(p1,numbers[second_confirmation-1]) == True:
        if(debug) : print(f"026 - O número {p1} na roleta {roulette['slug']} é consecutivo ao número {numbers[second_confirmation+1]}") 
        return None

    #procura a terceira ocorrencia do gatilho
    third_confirmation = first_index_after(numbers, p2, start = second_confirmation+1)

    if third_confirmation is None:
        if(debug) : print(f"027 - A Terceira confirmação na roleta {roulette['slug']} não aconteceu") 
        return None
    
    if third_confirmation-second_confirmation < 13:
        if(debug) : print(f"028 - A segunda confirmação na roleta {roulette['slug']} aconteceu muito proxima do gatilho") 
        return None
    
    if numbers[third_confirmation-1] == 0:
       if(debug) : print(f"029 - O número {numbers[third_confirmation-1]} na roleta {roulette['slug']} é igual ao número 0") 
       return None 
    
    if numbers[third_confirmation-2] == 0:
       if(debug) : print(f"030 - O número {numbers[third_confirmation-2]} na roleta {roulette['slug']} é igual ao número 0") 
       return None 
    
    if third_confirmation + 1 >= len(numbers):
       if(debug) : print(f"031 - O número {third_confirmation + 1} na roleta {roulette['slug']} ultrapassou o tamanho da lista {len(numbers)}") 
       return None 

    if numbers[third_confirmation+1] == 0:
       if(debug) : print(f"032 - O número {numbers[third_confirmation+1]} na roleta {roulette['slug']} é igual ao número 0") 
       return None 
    
    if numbers[third_confirmation-1] != numbers[second_confirmation-1]:
        if(debug) : print(f"033 - O gatilho não puxou o mesmo numero que na segunda ocorrencia na {roulette['slug']}") 
        return None
    
    #Verifica se é vizinho
    if numbers[third_confirmation-1] in p2_neihbords:
        if(debug) : print(f"034 - O número {numbers[third_confirmation-1]} na roleta {roulette['slug']} é vizinho do número {p2}") 
        return None 
    
    #Verifica se algum deles é consecutivo
    if is_consecutive(numbers[third_confirmation-2],numbers[third_confirmation-1]) == True:
        if(debug) : print(f"035 - O número {numbers[third_confirmation-2]} na roleta {roulette['slug']} é consecutivo ao número {numbers[third_confirmation-1]}") 
        return None
    
    if is_consecutive(numbers[third_confirmation-1],p2) == True:
        if(debug) : print(f"036 - O número {numbers[third_confirmation-1]} na roleta {roulette['slug']} é consecutivo ao número {p2}") 
        return None
    
    if is_consecutive(p2,numbers[third_confirmation+1]) == True:
        if(debug) : print(f"037 - O número {p2} na roleta {roulette['slug']} é consecutivo ao número {numbers[third_confirmation+1]}") 
        return None
    
    #Ve se tem uma quarta Ocorrencia
    ja_pagou = first_index_after(numbers, p2, start= third_confirmation+1)
    ja_pagou_inverso = first_index_after(numbers, numbers[third_confirmation-1], start= third_confirmation+1)
    
    if ja_pagou is not None:
        ja_pagou = ja_pagou - third_confirmation

    # Se tiver uma terceira ocorrencia e ela ja pagou
    if ja_pagou is not None and ja_pagou < 13:
        if debug:print(f"038 - O gatilho apareceu muito proximo da terceira ocorrencia {roulette['slug']}")
        return None
    
    #Se o gatilho ja havia trazido o zero cai fora
    if ja_pagou_inverso != None and numbers[ja_pagou_inverso-1] == p2:
        if(debug) : print(f"039 - O gatilho puxou o alvo na {roulette['slug']} pagando invertido") 
        return None
    
    
    #zero muito proximo ao gatilho
    if  appears_in_slice(0, numbers, 0, 8):
        if(debug) : print(f"040 - Apareceu um zero muito proximo ao ultimo gatilho") 
        return None
    
    #zero muito proximo ao gatilho
    if  appears_in_slice(0, numbers, second_confirmation-7, second_confirmation+7):
        if(debug) : print(f"041 - Apareceu um zero muito proximo ao ultimo gatilho") 
        return None


    #zero muito proximo ao gatilho
    if  appears_in_slice(0, numbers, third_confirmation-7, third_confirmation+7):
        if(debug) : print(f"042 - Apareceu um zero muito proximo ao ultimo gatilho") 
        return None
 
    #Verifica se atraz do gatilho veio vizinho dos alvos
    if p3 in p1_neihbords:
        if(debug) : print(f"043 - Apareceu um vizinho alternado do alvo {p1} na {roulette['slug']}") 
        return None        
    
    target_neihbords2 = get_neighbords(numbers[second_confirmation-1])

    if numbers[second_confirmation+1] in target_neihbords2:
        if(debug) : print(f"044 - Apareceu um vizinho alternado do alvo {numbers[second_confirmation-1]} na {roulette['slug']}") 
        return None   

    if numbers[third_confirmation+1] in target_neihbords2:
        if(debug) : print(f"045 - Apareceu um vizinho alternado do alvo {numbers[second_confirmation-1]} na {roulette['slug']}") 
        return None   
    

    #Verifica se o os alvos são iguais ao vizinho do espelho ou espelho do gatilho
    if p2_mirror:
        print(f"p2_mirror: {p2_mirror[0]}")
        if p1 in get_neighbords(p2_mirror[0]):
            if(debug) : print(f"046 - O alvo {p1} é vizinho do espelho do gatilho {p2} na {roulette['slug']}") 
            return None
        
        if numbers[second_confirmation-1] in get_neighbords(p2_mirror[0]):
            if(debug) : print(f"047 - O alvo {numbers[second_confirmation-1]} é vizinho do espelho do gatilho {p2} na {roulette['slug']}")
            return None

    if p1 == p3:
        if(debug) : print(f"048 - Alternancia de numeroz exatos entre os gatilhos do numero {p1} na {roulette['slug']}") 
        return None       

    if p1 == p0:
        if(debug) : print(f"049 - repetição de {p1} na {roulette['slug']}") 
        return None      
    
    if p2 == p0:
        if(debug) : print(f"050 - repetição de {p2} na {roulette['slug']}") 
        return None   
    
    if is_consecutive(p0, p2):
        if(debug) : print(f"051 - O número {p0} na roleta {roulette['slug']} é consecutivo ao número {p2}") 
        return None

    if is_consecutive(p1, p3):
        if(debug) : print(f"052 - O número {p1} na roleta {roulette['slug']} é consecutivo ao número {p3}") 
        return None


    if numbers[second_confirmation-1] == numbers[second_confirmation+1]:
        if(debug) : print(f"053 - Alternancia de numeroz exatos entre os gatilhos do numero {numbers[second_confirmation+1]} na {roulette['slug']}") 
        return None       

    if numbers[second_confirmation-1] == numbers[second_confirmation-2]:
        if(debug) : print(f"054 - repetição de {numbers[second_confirmation-1]} na {roulette['slug']}") 
        return None      
    
    if numbers[second_confirmation-2] == numbers[second_confirmation]:
        if(debug) : print(f"054 - repetição de {numbers[second_confirmation-1]} na {roulette['slug']}") 
        return None     
    
    if is_consecutive(numbers[second_confirmation-2], numbers[second_confirmation]):
        if(debug) : print(f"055 - O número {p0} na roleta {roulette['slug']} é consecutivo ao número {p2}") 
        return None

    if is_consecutive(numbers[second_confirmation-1], numbers[second_confirmation+1]):
        if(debug) : print(f"056 - O número {p1} na roleta {roulette['slug']} é consecutivo ao número {p3}") 
        return None

    if numbers[third_confirmation-1] == numbers[third_confirmation+1]:
        if(debug) : print(f"053 - Alternancia de numeroz exatos entre os gatilhos do numero {numbers[second_confirmation+1]} na {roulette['slug']}") 
        return None       

    if numbers[third_confirmation-1] == numbers[third_confirmation-2]:
        if(debug) : print(f"054 - repetição de {numbers[third_confirmation-1]} na {roulette['slug']}") 
        return None      
    
    if numbers[third_confirmation-2] == numbers[third_confirmation]:
        if(debug) : print(f"054 - repetição de {numbers[third_confirmation-1]} na {roulette['slug']}") 
        return None     
    
    if is_consecutive(numbers[third_confirmation-2], numbers[third_confirmation]):
        if(debug) : print(f"055 - O número {p0} na roleta {roulette['slug']} é consecutivo ao número {p2}") 
        return None

    if is_consecutive(numbers[third_confirmation-1], numbers[third_confirmation+1]):
        if(debug) : print(f"056 - O número {p1} na roleta {roulette['slug']} é consecutivo ao número {p3}") 
        return None    


    #Alvo, toda bet, gatilhos
    target = [p1,numbers[second_confirmation-1]]
    target_neihbords = get_neighbords(p1)
    numbers_bet = [0]
    numbers_bet.extend(target)
    numbers_bet.extend(target_neihbords)
    numbers_bet.extend(target_neihbords2)
    mirror_list = [m for n in numbers_bet for m in get_mirror(n)]
    numbers_bet.extend(mirror_list)
    numbers_bet.insert(0, 0)
    numbers_bet = sorted(set(numbers_bet))
    mirror_p2 = get_mirror(p2)

    triggers = [p2]
    if get_mirror(p2) is not None:
        triggers.extend(mirror_p2)
    
    #TESTE
    ##########################
    tipo = "Puxa Quebra"
    print(f"Padrão = Puxa Quebra")
    print(f"Tipo = {tipo}")
    print(f"p1 = {p1}")
    print(f"p2 = {p2}")
    print(f"protecao = {numbers_bet}")
    #########################################

    return {
                "roulette_id":roulette['slug'],
                "roulette_name" : roulette["name"],
                "roulette_url" : roulette["url"],
                "pattern" : "PUXA_QUEBRA",
                "triggers":triggers,
                "targets":target,
                "bets":numbers_bet,
                "passed_spins" : 0,
                "spins_required" : 12, #Spins que não vai ter para traz o gatilho
                "filters_after_trigger" : ["consecutive", "repetition", "terminal", "alternation"], #todos os basicos, se pagou invertido
                "filters_before_trigger" : ["consecutive", "repetition", "terminal", "alternation"], #todos os basicos, se pagou invertido
                "snapshot":numbers[:8],
                "status":"waiting",
        }
    #Tem que adicionar que se der red em alternancia, o proximo gatilho que vier vai pagar o numero que quebrou a alternancia

