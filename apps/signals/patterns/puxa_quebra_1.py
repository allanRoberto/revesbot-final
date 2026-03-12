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
    #numbers = [24, 16, 12, 29, 23, 29, 27, 20, 17, 7, 20, 25, 6, 34, 23, 20, 22, 29, 9, 7, 35, 32, 31, 33, 19, 10, 24, 27, 16, 21, 3, 5, 10, 29, 30, 10, 22, 18, 32, 34, 15, 18, 21, 12, 33, 5, 17, 27, 2, 7, 16, 31, 14, 23, 0, 6, 19, 21, 19, 27, 16, 29, 10, 11, 2, 6, 35, 17, 36, 26, 30, 21, 33, 5, 7, 24, 14, 9, 15, 18, 36, 24, 12, 27, 10, 20, 3, 32, 19, 4, 4, 11, 26, 29, 32, 19, 8, 3, 10, 26, 22, 1, 19, 16, 21, 30, 20, 0, 35, 25, 27, 0, 15, 36, 25, 20, 22, 14, 5, 18, 17, 14, 3, 29, 28, 18, 27, 14, 35, 0, 13, 36, 3, 22, 12, 19, 24, 24, 20, 4, 5, 20, 28, 3, 4, 19, 16, 4, 0, 34, 30, 5, 6, 24, 5, 6, 24, 12, 1, 18, 5, 6, 24, 23, 9, 27, 17, 14, 14, 29, 15, 18, 35, 29, 2, 23, 36, 6, 8, 8, 6, 21, 22, 26, 35, 9, 15, 34, 18, 23, 10, 33, 21, 28, 35, 35, 4, 24, 30, 10]
    #####################################################

    idxs = (0, 1, 2, 3)
    p0, p1, p2,p3 = [numbers[i] for i in idxs] # p1 : alvo | p2 : gatilho
    #####################################################################
    #####################################################################
    p1_neihbords = get_neighbords(p2)
    p2_neihbords = get_neighbords(p2)
    p2_mirror = get_mirror(p2)
    p1_mirror = get_mirror(p1)
    lista1 = [3,15,30]
    lista2 = [12, 21, 24, 6]
    lista3 = [13, 31, 26]
    lista4 = [2, 20, 22]
    target = [p0,p1]
    triggers = [p2]
    aux = []
    aux0 = []
    aux1 = []   
    aux2 = []
    aux3 = []


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
    
    if p2 not in lista1 and p2 not in lista2 and p2 not in lista3 and p2 not in lista4:
       if(debug) : print(f"005 - O número {p2} na roleta {roulette['slug']} não é um gatilho de quebra") 
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


    if p2 in lista1:
       aux = lista1
    elif p2 in lista2:
       aux = lista2
    elif p2 in lista3:
       aux = lista3
    elif p2 in lista4:
       aux = lista4
    else:
       if(debug) : print(f"057 - O gatilho {p2} não é um gatilho de quebra") 
       return None


    if p1 in lista1:
       aux0 = lista1
    elif p1 in lista2:
       aux0 = lista2
    elif p1 in lista3:
       aux0 = lista3
    elif p1 in lista4:
       aux0 = lista4
    else:
       aux0 = [] 

    if numbers[second_confirmation-1] in lista1:
       aux1 = lista1
    elif numbers[second_confirmation-1] in lista2:
       aux1 = lista2
    elif numbers[second_confirmation-1] in lista3:
       aux1 = lista3
    elif numbers[second_confirmation-1] in lista4:
       aux1 = lista4
    else:
        if(debug) : print(f"058 - O número {numbers[second_confirmation-1]} não é um gatilho de quebra") 
        return None

    if numbers[third_confirmation-1] in lista1:
       aux2 = lista1
    elif numbers[third_confirmation-1] in lista2:
       aux2 = lista2
    elif numbers[third_confirmation-1] in lista3:
       aux2 = lista3
    elif numbers[third_confirmation-1] in lista4:
       aux2 = lista4
    else:
        if(debug) : print(f"059 - O número {numbers[third_confirmation-1]} não é um gatilho de quebra") 
        return None


    if numbers[ja_pagou-1] in lista1:
       aux3 = lista1
    elif numbers[ja_pagou-1] in lista2:
       aux3 = lista2
    elif numbers[ja_pagou-1] in lista3:
       aux3 = lista3
    elif numbers[ja_pagou-1] in lista4:
       aux3 = lista4
    else:
        aux3 = []

    if aux0 == aux:
        if(debug) : print(f"056 - O número {numbers[second_confirmation-1]} na roleta {roulette['slug']} é da mesma lista do gatilho {p2}") 
        return None

    if aux1 != aux:
        if(debug) : print(f"057 - O número {numbers[second_confirmation-1]} na roleta {roulette['slug']} não é da mesma lista do gatilho {p2}") 
        return None

    if aux2 != aux:
        if(debug) : print(f"058 - O número {numbers[third_confirmation-1]} na roleta {roulette['slug']} não é da mesma lista do gatilho {p2}") 
        return None

    if aux3 == aux:
        if(debug) : print(f"056 - O número {numbers[ja_pagou-1]} na roleta {roulette['slug']} é da mesma lista do gatilho {p2}") 
        return None

    #Alvo, toda bet, gatilhos
    triggers = [p2]

    target = []
    target.extend(aux)
    
    numbers_bet = [0]
    numbers_bet.extend(target)

    neighbors = [m for n in aux for m in get_neighbords(n)]
    numbers_bet.extend(neighbors)

    mirror_list = [m for n in numbers_bet for m in get_mirror(n)]
    numbers_bet.extend(mirror_list)
    numbers_bet.insert(0, 0)
    numbers_bet = sorted(set(numbers_bet))

    
    #TESTE
    ##########################
    tipo = "Puxa Quebra que se puxam"
    print(f"Tipo = {tipo}")
    print(f"p1 = {p1}")
    print(f"p2 = {p2}")
    print(f"protecao = {numbers_bet}")
    #########################################

    return {
                "roulette_id":roulette['slug'],
                "roulette_name" : roulette["name"],
                "roulette_url" : roulette["url"],
                "pattern" : "PUXA_QUEBRA_SE_PUXA",
                "triggers":triggers,
                "targets":target,
                "bets":numbers_bet,
                "passed_spins" : 0,
                "spins_required" : 12, #Spins que não vai ter para traz o gatilho
                "snapshot":numbers[:8],
                "status":"waiting",
                "message" : "Gatilho encontrado!"
        }
    #Tem que adicionar que se der red em alternancia, o proximo gatilho que vier vai pagar o numero que quebrou a alternancia

