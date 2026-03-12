from helpers.utils.filters import first_index_after, is_consecutive
from helpers.utils.get_neighbords import get_neighbords
from helpers.utils.get_mirror import get_mirror


def get_index_target(numbers, target):
    """Busca o índice do target na lista de números"""
    for i in range(len(numbers)):
        if target == numbers[i]:
            return i
    return None


def process_roulette(roulette, numbers) :

    """
    Processa o padrão da roleta seguindo a lógica:
    1. Pega o trigger na posição 9 (índice 9)
    2. Busca a próxima ocorrência do trigger
    3. Pega o número após essa ocorrência (target)
    4. Verifica se o target apareceu nos 8 números após o primeiro trigger
    5. Se sim, retorna a distância e as apostas
    """

    if len(numbers) < 10:
        return None
    
    idxs = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9)


    p0, p1, p2, p3, p4, p5, p6, p7, p8, p9 = [numbers[i] for i in idxs]

    
    
    i2  = first_index_after(numbers, p9, 10)

    # Se não encontrou outra ocorrência do trigger
    if i2 is None or i2 >= len(numbers) - 1:
        return None

    trigger = p9
    target = numbers[i2 + 1]

    trigger_neighbords = get_neighbords(trigger)
    target_neighbords = get_neighbords(target)

    trigger_mirror = get_mirror(trigger)
    target_mirror = get_mirror(target)

    if any((num1 == target) for num1 in target_mirror) :
        return None
                                       

    print(numbers[i2], p9)


    if(trigger == target) :
        return None
    
    # Verifica se o target apareceu nos 8 números após o primeiro trigger (posições 10-17)
    # Busca nos 8 números após o trigger (posições 10 a 17)
    search_range = numbers[0:min(8, len(numbers))]
    index_target = get_index_target(search_range, target)
    
    # Se o target não foi encontrado nos 8 números após o trigger
    if index_target is None:
        return None
    
     
    # Calcula a distância do target em relação ao trigger
    distance = index_target + 1  # +1 porque começamos a contar do próximo número


    # Pega os vizinhos do target
    target_neighbords = get_neighbords(target)
    
    # Pega os espelhos do target
    target_mirror = get_mirror(target)
    
    # Verifica se algum espelho é igual ao target (validação adicional)
    if any((num == target) for num in target_mirror):
        return None
    
    # Monta a lista de apostas
    bets = []
    
    # Adiciona o próprio target
    bets.append(target)
    
    # Adiciona os vizinhos
    if target_neighbords:
        bets.extend(target_neighbords)
    
    # Adiciona os espelhos (se existirem e forem diferentes)
    if target_mirror:
        for mirror in target_mirror:
            if mirror not in bets:
                bets.append(mirror)
    
    # Remove duplicatas mantendo a ordem
    bets_unique = []
    for bet in bets:
        if bet not in bets_unique:
            bets_unique.append(bet)

    
    # Retorna o resultado com a distância e as apostas
    result = {
        'trigger': trigger,
        'target': target,
        'distance': distance,
        'bets': bets_unique,
        'wait_rounds': distance  # Quantas rodadas esperar após o próximo trigger
    }
    
    print(f"PADRÃO DETECTADO:")
    print(f"  Trigger: {trigger}")
    print(f"  Target: {target}")
    print(f"  Distância: {distance} rodadas")
    print(f"  Apostas: {bets_unique}")
    print(f"  últimos números: {numbers[:5]}")
    

    

    
    
    
    return None